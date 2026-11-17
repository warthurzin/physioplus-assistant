import time
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.actions.schemas import PATIENT_ACTIONS
from app.actions.service import ActionService
from app.actions.command_signer import AssistantCommandSigner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from pydantic import SecretStr
from app.actions.signer import ProposalSigner
from app.core.config import Settings
from app.core.exceptions import ActionsDisabledError
from app.integrations.physio_api import PhysioApiClient
from app.services.retrieval_service import RetrievalService

# model_construct does not read environment files or process credentials.
with patch("app.core.config.get_settings", new=lambda: Settings.model_construct()):
    from app import main


USER_ID = "00000000-0000-4000-8000-000000000001"
OTHER_USER_ID = "00000000-0000-4000-8000-000000000002"
TEST_SECRET = "isolated-test-signing-key-not-for-production"
EXECUTORS = {
    "create_patient": "_exec_create_patient",
    "update_patient": "_exec_update_patient",
    "deactivate_patient": "_exec_deactivate_patient",
    "reactivate_patient": "_exec_reactivate_patient",
    "create_appointment": "_exec_create",
    "cancel_appointment": "_exec_cancel",
    "confirm_appointment": "_exec_confirm",
    "set_session_payment": "_exec_payment",
}


class ActionSafetyChecks(unittest.TestCase):
    def setUp(self):
        transport = patch(
            "httpx.HTTPTransport.handle_request",
            side_effect=AssertionError("Real HTTP is forbidden in these checks"),
        )
        transport.start()
        self.addCleanup(transport.stop)
        self.api = Mock(spec=PhysioApiClient)
        self.api.get_current_user.return_value = {"id": USER_ID}
        self.now = time.time()
        self.signer = ProposalSigner(TEST_SECRET, 60, clock=lambda: self.now)
        self.key = Ed25519PrivateKey.generate()
        self.command_signer = AssistantCommandSigner("test", self.key, clock=lambda: int(self.now))
        self.service = ActionService(self.api, self.signer, command_signer=self.command_signer)
        def execute(_token, envelope):
            import base64, json
            command = json.loads(base64.urlsafe_b64decode(envelope["command"] + "=" * (-len(envelope["command"]) % 4)))
            status = "expired" if command["expires_at"] <= self.now else "executed"
            return {"state": "rejected" if status == "expired" else "completed", "result": {
                "status": status, "message": "Synthetic result", "action": command["action"],
            }}
        self.api.execute_assistant_command.side_effect = execute

    def proposal(self, action="create_patient", user_id=USER_ID):
        return self.service._proposal(action, user_id, {}, "Simulated proposal").proposal["token"]

    def assert_no_execution(self):
        self.api.execute_assistant_command.assert_not_called()
        self.assertTrue(all(call[0] in {"get_current_user", "close"} for call in self.api.method_calls))

    @contextmanager
    def client(self, injected=None, **overrides):
        settings = Settings.model_construct(
            **{
                "assistant_signing_secret": TEST_SECRET,
                "assistant_executions_enabled": True,
                "assistant_command_key_id": "test",
                "assistant_command_private_key": SecretStr(self.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()),
                "enable_debug_endpoints": False,
                **overrides,
            }
        )
        retrieval = Mock(spec=RetrievalService)
        graph = Mock()
        graph.invoke.return_value = {
            "answer": "Simulated read-only answer",
            "path": "abstencao",
            "intent": "DOCUMENTACAO",
            "usage": {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
        }
        with (
            patch.object(main, "get_settings", return_value=settings),
            patch.object(main, "PhysioApiClient", return_value=self.api),
            patch("app.services.chat_service.build_assistant_graph", return_value=graph),
        ):
            app = main.create_app(
                retrieval_service=retrieval,
                llm_client=SimpleNamespace(model_name="isolated-model"),
                action_service=injected,
            )
            with TestClient(app) as client:
                yield client, app

    def test_proposals_issued_before_patient_disable_are_rejected(self):
        for action in PATIENT_ACTIONS:
            with self.subTest(action=action):
                token = self.proposal(action)
                disabled = ActionService(self.api, self.signer, patient_actions_enabled=False)
                for name in EXECUTORS.values():
                    setattr(disabled, name, Mock(side_effect=AssertionError("Execution forbidden")))
                result = disabled.confirm(token, "simulated-access")
                self.assertEqual(result.status, "rejected")
                self.assertEqual(result.action, action)
        self.assert_no_execution()

    def test_patient_flag_is_checked_again_in_same_service(self):
        token = self.proposal()
        self.service._patient_actions = False
        self.assertEqual(self.service.confirm(token, "simulated-access").status, "rejected")
        self.assert_no_execution()

    def test_patient_proposals_remain_blocked(self):
        self.service._patient_actions = False
        for action in PATIENT_ACTIONS:
            with self.subTest(action=action):
                self.assertEqual(self.service.propose(action, {}, "simulated-access").status, "unsupported")
        self.assert_no_execution()

    def test_patient_flag_does_not_block_other_actions(self):
        self.service._patient_actions = False
        for action in EXECUTORS.keys() - PATIENT_ACTIONS:
            with self.subTest(action=action):
                self.assertEqual(self.service.confirm(self.proposal(action), "simulated-access").status, "executed")
                self.assertEqual(self.api.execute_assistant_command.call_args.args[0], "simulated-access")

    def test_invalid_expired_and_other_user_proposals_are_rejected(self):
        expired = self.proposal()
        self.now += 61
        cases = [
            ("not-a-valid-proposal", "invalid"),
            (expired, "expired"),
            (self.proposal(user_id=OTHER_USER_ID), "invalid"),
        ]
        for token, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.service.confirm(token, "simulated-access").status, expected)
        self.assertEqual(self.api.execute_assistant_command.call_count, 1)

    def test_missing_blank_short_and_non_string_secrets_are_rejected(self):
        for secret in (None, "", " " * 64, "short", "x" * 31, "  " + "x" * 31 + "  "):
            with self.subTest():
                with self.assertRaises(ActionsDisabledError):
                    ProposalSigner(secret, 60)

    def test_valid_secret_preserves_token_format_and_cross_instance_verification(self):
        other_signer = ProposalSigner(TEST_SECRET, 60, clock=lambda: self.now)
        self.assertEqual(other_signer.verify(self.proposal())["uid"], USER_ID)

    def test_global_flags_block_all_actions_even_with_injected_service(self):
        for flag in ("data_tools_enabled", "actions_enabled", "assistant_executions_enabled"):
            with self.subTest(flag=flag), self.client(injected=self.service, **{flag: False}) as (client, app):
                self.assertIsNone(app.state.action_service)
                for action in EXECUTORS:
                    response = client.post(
                        "/chat/confirm",
                        json={"proposal": self.proposal(action)},
                        headers={"Authorization": "Bearer simulated-access"},
                    )
                    self.assertEqual(response.status_code, 503)
                    self.assertIn("detail", response.json())
        self.assert_no_execution()

    def test_missing_or_invalid_secret_disables_actions_without_stopping_startup(self):
        for secret in ("", " " * 64, "short"):
            with self.subTest(), self.client(injected=self.service, assistant_signing_secret=secret) as (client, app):
                self.assertIsNone(app.state.action_service)
                response = client.post(
                    "/chat/confirm",
                    json={"proposal": self.proposal()},
                    headers={"Authorization": "Bearer simulated-access"},
                )
                self.assertEqual(response.status_code, 503)
                response = client.post(
                    "/chat",
                    json={"message": "Read-only question"},
                    headers={"Authorization": "Bearer simulated-access"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["proposal"])
        self.assert_no_execution()

    def test_valid_secret_and_enabled_actions_initialize_service(self):
        with self.client() as (_, app):
            self.assertIsInstance(app.state.action_service, ActionService)
            self.assertEqual(app.state.action_service._signer.verify(self.proposal())["uid"], USER_ID)
        self.assert_no_execution()

    def test_patient_flag_from_settings_rejects_existing_proposal_via_route(self):
        with self.client(patient_actions_enabled=False) as (client, _):
            response = client.post(
                "/chat/confirm",
                json={"proposal": self.proposal()},
                headers={"Authorization": "Bearer simulated-access"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "rejected")
            self.assertEqual(response.json()["action"], "create_patient")
        self.assert_no_execution()

    def test_read_only_chat_works_without_signing_secret_when_actions_disabled(self):
        with self.client(actions_enabled=False, assistant_signing_secret="") as (client, app):
            self.assertIsNone(app.state.action_service)
            response = client.post(
                "/chat",
                json={"message": "Read-only question"},
                headers={"Authorization": "Bearer simulated-access"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["proposal"])
        self.assert_no_execution()


if __name__ == "__main__":
    unittest.main(verbosity=2)
