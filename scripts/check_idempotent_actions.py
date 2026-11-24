"""Isolated transport and proposal lifecycle checks; no environment file or real HTTP."""
import base64
import json
import unittest
from datetime import date
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.actions.command_signer import AssistantCommandSigner
from app.actions.service import ActionService
from app.actions.signer import ProposalSigner
from app.integrations.physio_api import PhysioApiClient

USER = "11111111-1111-4111-8111-111111111111"
PATIENT = "22222222-2222-4222-8222-222222222222"
APPOINTMENT = "33333333-3333-4333-8333-333333333333"
SESSION = "44444444-4444-4444-8444-444444444444"


class IntegrationChecks(unittest.TestCase):
    def setUp(self):
        forbidden = patch("httpx.HTTPTransport.handle_request", side_effect=AssertionError("Real network forbidden"))
        forbidden.start()
        self.addCleanup(forbidden.stop)
        self.now = 1800000000
        self.calls = []
        self.mode = "success"
        self.saved = None
        self.patient = {"id": PATIENT, "user_id": USER, "full_name": "Pessoa Sintética", "is_active": True,
                        "session_value": "100.00", "cpf": "11144477735", "phone": "81999990000", "assistant_revision": "3"}
        self.appointment = {"id": APPOINTMENT, "patient_id": PATIENT, "date": "2030-01-02", "start_time": "08:00",
                            "end_time": "09:00", "status": "scheduled", "assistant_revision": "5"}
        self.session = {"id": SESSION, "patient_id": PATIENT, "date": "2030-01-02", "start_time": "08:00",
                        "end_time": "09:00", "payment_status": "pending", "session_value": "100.00", "assistant_revision": "7"}
        self.api = PhysioApiClient("https://synthetic.invalid/api/v1", 1, transport=httpx.MockTransport(self.handle))
        self.addCleanup(self.api.close)
        self.signer = ProposalSigner("synthetic-fernet-secret-not-for-production", 300, clock=lambda: self.now)
        self.command_signer = AssistantCommandSigner("test", Ed25519PrivateKey.generate(), clock=lambda: self.now)
        self.service = ActionService(self.api, self.signer, today_fn=lambda: date(2030, 1, 1), command_signer=self.command_signer)

    def handle(self, request):
        self.calls.append(request)
        self.assertEqual(request.headers["authorization"], "Bearer synthetic-access")
        path = request.url.path
        if path.endswith("/auth/me"):
            return httpx.Response(200, json={"data": {"id": USER}})
        if path.endswith("/patients"):
            query = request.url.params.get("search", "")
            return httpx.Response(200, json={"data": [] if query.isdigit() else [self.patient]})
        if path.endswith("/appointments") and request.method == "GET":
            return httpx.Response(200, json={"data": [self.appointment]})
        if path.endswith("/schedule/day") and request.method == "GET":
            return httpx.Response(200, json={"data": []})
        if "/assistant/context/" in path:
            return httpx.Response(200, json={"data": {"patient": self.patient, "appointments": [self.appointment], "sessions": [self.session]}})
        if path.endswith("/assistant/executions") and request.method == "POST":
            envelope = json.loads(request.content)
            command = self.decode(envelope)
            self.saved = {"execution_id": command["execution_id"], "state": "completed", "result": {
                "status": "executed", "message": "Operação executada.", "action": command["action"]}}
            if self.mode in {"lost", "both_lost"}:
                raise httpx.ReadTimeout("synthetic timeout")
            if self.mode == "auth":
                return httpx.Response(401)
            if self.mode == "refused":
                return httpx.Response(422, json={"error": True})
            if self.mode == "invalid_result":
                return httpx.Response(200, json={"data": {"state": "completed", "result": {"status": "executed"}}})
            return httpx.Response(200, json={"data": self.saved})
        if "/assistant/executions/" in path and request.method == "GET":
            if self.mode == "both_lost":
                raise httpx.ConnectError("synthetic failure")
            return httpx.Response(200, json={"data": self.saved})
        raise AssertionError("Unexpected HTTP route; legacy writes are forbidden")

    @staticmethod
    def decode(envelope):
        raw = envelope["command"]
        return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))

    def propose(self):
        return self.service.propose("create_appointment", {"patient_name": "Pessoa Sintética", "date": "2030-01-02", "start_time": "10:00"}, "synthetic-access").proposal["token"]

    def writes(self):
        return [call for call in self.calls if call.method == "POST"]

    def test_all_eight_actions_capture_real_revisions(self):
        base = {"patient_name": "Pessoa Sintética", "date": "2030-01-02"}
        actions = {
            "create_appointment": {**base, "start_time": "10:00"},
            "cancel_appointment": base, "confirm_appointment": base,
            "set_session_payment": {**base, "paid": True},
            "create_patient": {"full_name": "Pessoa Nova", "cpf": "52998224725", "phone": "81999990000", "session_value": 100},
            "update_patient": {**base, "changes": {"phone": "81988880000"}},
            "deactivate_patient": base, "reactivate_patient": base,
        }
        for action, args in actions.items():
            with self.subTest(action=action):
                self.patient["is_active"] = action != "reactivate_patient"
                result = self.service.propose(action, args, "synthetic-access")
                self.assertEqual(result.status, "proposed")
                payload = self.signer.verify(result.proposal["token"])
                command = self.decode(payload["command"])
                self.assertEqual(command["action"], action)
                self.assertEqual(command["execution_id"], payload["execution_id"])
                if action != "create_patient":
                    self.assertEqual(command["preconditions"]["patient_revision"], "3")
                self.assertNotIn("_appointments", command["parameters"])
        self.assertFalse(self.writes())

    def test_explicit_repeat_preserves_uuid_and_original_bytes(self):
        token = self.propose()
        for _ in range(2):
            self.assertEqual(self.service.confirm(token, "synthetic-access").status, "executed")
        self.assertEqual(self.writes()[0].content, self.writes()[1].content)
        count = len(self.writes())
        self.assertEqual(self.service.recover(token, "synthetic-access").status, "executed")
        self.assertEqual(len(self.writes()), count)

    def test_lost_response_uses_get_and_never_repeats_post(self):
        token = self.propose()
        self.mode = "lost"
        self.assertEqual(self.service.confirm(token, "synthetic-access").status, "executed")
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.calls[-1].method, "GET")

    def test_unresolved_response_stays_uncertain(self):
        token = self.propose()
        self.mode = "both_lost"
        self.assertEqual(self.service.confirm(token, "synthetic-access").status, "unavailable")
        self.assertEqual(len(self.writes()), 1)

    def test_401_and_422_never_retry_or_recover_automatically(self):
        for mode, expected in [("auth", "auth"), ("refused", "invalid")]:
            token = self.propose()
            self.mode = mode
            previous = len(self.writes())
            self.assertEqual(self.service.confirm(token, "synthetic-access").status, expected)
            self.assertEqual(len(self.writes()), previous + 1)
            self.assertEqual(self.calls[-1].method, "POST")

    def test_old_unsigned_proposals_and_other_users_never_write(self):
        for payload in [{"v": 1, "uid": USER, "act": "create_appointment", "p": {}},
                        {"v": 2, "uid": PATIENT, "command": {}, "execution_id": APPOINTMENT}]:
            self.assertEqual(self.service.confirm(self.signer.sign(payload), "synthetic-access").status, "invalid")
        self.assertFalse(self.writes())

    def test_recovery_after_expiry_is_read_only(self):
        token = self.propose()
        self.service.confirm(token, "synthetic-access")
        self.now += 1000
        self.assertEqual(self.service.recover(token, "synthetic-access").status, "executed")
        self.assertEqual(len(self.writes()), 1)

    def test_disabled_flags_and_missing_revision_do_not_write(self):
        token = self.propose()
        self.service._enabled = lambda: False
        self.assertEqual(self.service.confirm(token, "synthetic-access").status, "rejected")
        self.service._enabled = lambda: True
        self.patient.pop("assistant_revision")
        result = self.service.propose("deactivate_patient", {"patient_name": "Pessoa Sintética"}, "synthetic-access")
        self.assertEqual(result.status, "unavailable")
        self.assertFalse(self.writes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
