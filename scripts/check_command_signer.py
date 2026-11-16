import argparse
import base64
import json
import logging
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from app.actions.command_signer import (
    ACTIONS,
    MAX_SAFE_INTEGER,
    AssistantCommandSigner,
    AssistantCommandSigningError,
)

NOW = 1800000000
PROFESSIONAL_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"


def decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class SigningFixture:
    def setUp(self):
        self.key = ed25519.Ed25519PrivateKey.generate()
        self.signer = AssistantCommandSigner("test-key", self.key, clock=lambda: NOW)

    def signed(self, **overrides):
        return self.signer.sign(**{
            "professional_id": PROFESSIONAL_ID,
            "action": "deactivate_patient",
            "parameters": {"patient_id": OTHER_ID},
            "preconditions": {},
            **overrides,
        })

    def assert_rejected(self, operation, code):
        with self.assertRaises(AssistantCommandSigningError) as error:
            operation()
        self.assertEqual(error.exception.code, code)


class SignerChecks(SigningFixture, unittest.TestCase):
    def test_exact_envelope_command_fields_and_original_signature_bytes(self):
        envelope = self.signed()
        self.assertEqual(set(envelope), {"key_id", "command", "signature"})
        raw = decode(envelope["command"])
        payload = json.loads(raw)
        self.assertEqual(set(payload), {
            "version", "purpose", "execution_id", "professional_id", "action",
            "issued_at", "expires_at", "parameters", "preconditions",
        })
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["purpose"], "physioplus.assistant.execute")
        self.assertEqual(payload["issued_at"], NOW)
        self.assertEqual(payload["expires_at"], NOW + 300)
        self.assertEqual(payload["professional_id"], PROFESSIONAL_ID)
        self.assertEqual(payload["parameters"], {"patient_id": OTHER_ID})
        self.assertEqual(UUID(payload["execution_id"]).version, 4)
        expected = b"PhysioPlus/assistant-command/v1\x00test-key\x00" + raw
        self.key.public_key().verify(decode(envelope["signature"]), expected)
        for field in ("command", "signature"):
            self.assertNotIn("=", envelope[field])
            self.assertEqual(encode(decode(envelope[field])), envelope[field])
        self.assertEqual(len(decode(envelope["signature"])), 64)

    def test_every_signing_call_creates_a_new_uuid_v4(self):
        first = json.loads(decode(self.signed()["command"]))["execution_id"]
        second = json.loads(decode(self.signed()["command"]))["execution_id"]
        self.assertNotEqual(first, second)
        self.assertEqual(UUID(first).version, 4)
        self.assertEqual(UUID(second).version, 4)

    def test_all_current_actions_are_supported(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                payload = json.loads(decode(self.signed(action=action)["command"]))
                self.assertEqual(payload["action"], action)

    def test_key_must_be_an_ed25519_private_key_object(self):
        invalid = [None, "not-a-private-key", b"not-a-private-key", self.key.public_key(),
                   ec.generate_private_key(ec.SECP256R1())]
        for index, key in enumerate(invalid):
            with self.subTest(index=index):
                self.assert_rejected(lambda: AssistantCommandSigner("test-key", key), "INVALID_KEY")

    def test_key_ids_have_strict_ascii_format(self):
        for key_id in (None, "", "key\n", "key\x00alias", "https://invalid.example/key", "á", "x" * 65):
            with self.subTest():
                self.assert_rejected(lambda: AssistantCommandSigner(key_id, self.key), "INVALID_KEY_ID")

    def test_invalid_identifiers_actions_and_object_roots_are_rejected(self):
        cases = [
            {"professional_id": "not-a-uuid"},
            {"professional_id": PROFESSIONAL_ID + "\n"},
            {"professional_id": "00000000-0000-0000-0000-000000000000"},
            {"action": "delete_database"},
            {"action": []},
            {"parameters": []},
            {"parameters": None},
            {"preconditions": "invalid"},
        ]
        for case in cases:
            with self.subTest():
                self.assert_rejected(lambda: self.signed(**case), "INVALID_COMMAND")

    def test_non_json_numbers_values_and_unsafe_properties_are_rejected(self):
        cases = [
            {"value": float("nan")}, {"value": float("inf")}, {"value": -float("inf")},
            {"value": MAX_SAFE_INTEGER + 1}, {"value": b"bytes"}, {"value": (1, 2)},
            {"value": {1, 2}}, {"value": object()}, {1: "numeric-key"},
            {"constructor": "blocked"}, {"__proto__": "blocked"}, {"prototype": "blocked"},
            {"field\n": "blocked"}, {"text": "\ud800"},
        ]
        for value in cases:
            for field in ("parameters", "preconditions"):
                with self.subTest(field=field):
                    self.assert_rejected(lambda: self.signed(**{field: value}), "INVALID_COMMAND")

    def test_structural_limits_and_cycles_are_rejected(self):
        nested = True
        for _ in range(9):
            nested = {"next": nested}
        cycle = {}
        cycle["next"] = cycle
        cases = [
            {"text": "x" * 2049}, {"text": "😀" * 1025}, {"items": [None] * 101},
            {f"key{i}": None for i in range(65)}, nested, cycle,
        ]
        for value in cases:
            with self.subTest():
                self.assert_rejected(lambda: self.signed(parameters=value), "INVALID_COMMAND")

    def test_oversized_utf8_command_is_not_signed(self):
        for parameters in (
            {f"field{i}": "x" * 2048 for i in range(10)},
            {f"field{i}": "😀" * 1024 for i in range(4)},
        ):
            with self.subTest():
                self.assert_rejected(lambda: self.signed(parameters=parameters), "COMMAND_TOO_LARGE")

    def test_valid_structural_boundaries_and_utf8_are_preserved(self):
        nested = True
        for _ in range(7):
            nested = {"next": nested}
        parameters = {"text": "😀" * 1024, "items": [None] * 100, "nested": nested,
                      "maximum": MAX_SAFE_INTEGER, "decimal": 0.25, "boolean": True}
        envelope = self.signed(parameters=parameters)
        raw = decode(envelope["command"])
        self.assertIn("😀".encode("utf-8"), raw)
        self.assertEqual(json.loads(raw)["parameters"], parameters)

    def test_ttl_clock_types_and_safe_integer_bounds(self):
        for ttl in (False, 0, -1, 301, 1.5, "60"):
            with self.subTest():
                self.assert_rejected(lambda: self.signed(ttl_seconds=ttl), "INVALID_TIME")
        for now in (False, 0, -1, NOW + 0.5, float("inf"), MAX_SAFE_INTEGER):
            with self.subTest():
                self.signer = AssistantCommandSigner("test-key", self.key, clock=lambda: now)
                self.assert_rejected(self.signed, "INVALID_TIME")
        self.assert_rejected(
            lambda: AssistantCommandSigner("test-key", self.key, clock=0), "INVALID_TIME",
        )

    def test_clock_is_read_once_and_one_second_ttl_is_valid(self):
        clock = Mock(return_value=NOW)
        self.signer = AssistantCommandSigner("test-key", self.key, clock=clock)
        payload = json.loads(decode(self.signed(ttl_seconds=1)["command"]))
        clock.assert_called_once_with()
        self.assertEqual(payload["expires_at"] - payload["issued_at"], 1)

    def test_default_clock_uses_integer_unix_seconds(self):
        before = int(time.time())
        self.signer = AssistantCommandSigner("test-key", self.key)
        payload = json.loads(decode(self.signed()["command"]))
        self.assertIs(type(payload["issued_at"]), int)
        self.assertLessEqual(before, payload["issued_at"])
        self.assertLessEqual(payload["issued_at"], int(time.time()))

    def test_signing_does_not_log_or_print(self):
        with patch.object(logging.Logger, "_log") as log, patch("builtins.print") as output:
            self.signed()
            self.assert_rejected(lambda: self.signed(action="invalid"), "INVALID_COMMAND")
            log.assert_not_called()
            output.assert_not_called()


class NodeInteropChecks(SigningFixture, unittest.TestCase):
    verifier_path: Path
    node_executable: str

    def verify_in_node(self, cases, public_keys=None, now=NOW):
        public_pem = self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        payload = {"public_keys": public_keys or {"test-key": public_pem}, "now": now, "cases": cases}
        bridge = Path(__file__).with_name("assistant_command_bridge.cjs")
        process = subprocess.run(
            [self.node_executable, str(bridge), str(self.verifier_path)],
            input=json.dumps(payload, ensure_ascii=False, allow_nan=False),
            text=True, encoding="utf-8", capture_output=True, timeout=15, check=False,
        )
        self.assertEqual(process.returncode, 0, "Isolated Node bridge failed")
        self.assertEqual(process.stderr, "")
        return json.loads(process.stdout)

    def case(self, envelope=None, **overrides):
        return {"envelope": envelope or self.signed(), "professional_id": PROFESSIONAL_ID, **overrides}

    def sign_invalid_fixture(self, payload):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        signed = b"PhysioPlus/assistant-command/v1\x00test-key\x00" + raw
        return {"key_id": "test-key", "command": encode(raw), "signature": encode(self.key.sign(signed))}

    def test_python_signature_original_bytes_and_utf8_are_accepted_by_real_node_module(self):
        parameters = {"name": "Paciente fictício — ação, coração e 😀", "nested": {"text": "{ : } [ ]"}}
        envelope = self.signed(parameters=parameters)
        expected_bytes = b"PhysioPlus/assistant-command/v1\x00test-key\x00" + decode(envelope["command"])
        result = self.verify_in_node([self.case(
            envelope, expected_signed_bytes=encode(expected_bytes), expected_parameters=parameters,
        )])
        self.assertEqual(result, [{"accepted": True, "bytes_match": True,
                                   "raw_signature_valid": True, "utf8_preserved": True}])

    def test_all_eight_actions_and_structural_boundaries_interoperate(self):
        nested = True
        for _ in range(7):
            nested = {"next": nested}
        parameters = {"text": "😀" * 1024, "items": [None] * 100, "maximum": MAX_SAFE_INTEGER,
                      "nested": nested}
        preconditions = {f"field{i}": None for i in range(64)}
        cases = [self.case(self.signed(action=action, parameters=parameters, preconditions=preconditions))
                 for action in sorted(ACTIONS)]
        self.assertEqual(self.verify_in_node(cases), [{"accepted": True}] * len(ACTIONS))

    def test_tampered_command_is_rejected(self):
        envelope = self.signed()
        payload = json.loads(decode(envelope["command"]))
        payload["action"] = "reactivate_patient"
        envelope["command"] = encode(json.dumps(payload).encode("utf-8"))
        self.assertEqual(self.verify_in_node([self.case(envelope)]), [
            {"accepted": False, "code": "INVALID_SIGNATURE"},
        ])

    def test_key_id_is_signed_even_when_an_alias_uses_the_same_public_key(self):
        public_pem = self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        envelope = self.signed()
        envelope["key_id"] = "alias-key"
        keys = {"test-key": public_pem, "alias-key": public_pem}
        self.assertEqual(self.verify_in_node([self.case(envelope)], keys), [
            {"accepted": False, "code": "INVALID_SIGNATURE"},
        ])

    def test_unknown_key_is_rejected(self):
        envelope = self.signed()
        envelope["key_id"] = "unknown-key"
        self.assertEqual(self.verify_in_node([self.case(envelope)]), [
            {"accepted": False, "code": "UNKNOWN_KEY"},
        ])

    def test_another_public_key_does_not_verify_the_signature(self):
        other_key = ed25519.Ed25519PrivateKey.generate()
        keys = {"test-key": other_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")}
        self.assertEqual(self.verify_in_node([self.case()], keys), [
            {"accepted": False, "code": "INVALID_SIGNATURE"},
        ])

    def test_authenticated_user_must_match(self):
        self.assertEqual(self.verify_in_node([self.case(professional_id=OTHER_ID)]), [
            {"accepted": False, "code": "IDENTITY_MISMATCH"},
        ])

    def test_incompatible_version_purpose_and_times_are_rejected_by_node(self):
        base = json.loads(decode(self.signed()["command"]))
        cases = [
            ({"version": 2}, "UNSUPPORTED_VERSION"),
            ({"purpose": "login"}, "INVALID_PURPOSE"),
            ({"issued_at": NOW - 60, "expires_at": NOW}, "EXPIRED_COMMAND"),
            ({"issued_at": NOW - 61, "expires_at": NOW - 1}, "EXPIRED_COMMAND"),
            ({"expires_at": NOW + 301}, "INVALID_TIME"),
            ({"issued_at": NOW + 31, "expires_at": NOW + 300}, "INVALID_TIME"),
        ]
        results = self.verify_in_node([
            self.case(self.sign_invalid_fixture({**base, **changes, "execution_id": str(uuid4())}))
            for changes, _ in cases
        ])
        self.assertEqual(results, [{"accepted": False, "code": code} for _, code in cases])

    def test_a_later_node_clock_expires_an_unchanged_python_command(self):
        envelope = self.signed(ttl_seconds=1)
        self.assertEqual(self.verify_in_node([self.case(envelope)], now=NOW + 1), [
            {"accepted": False, "code": "EXPIRED_COMMAND"},
        ])


def main():
    parser = argparse.ArgumentParser(description="Isolated Python/Node Ed25519 interoperability checks")
    parser.add_argument("--node-backend", required=True, type=Path, help="Path to physioPlus-backend")
    parser.add_argument("--node-executable", default="node", help="Node executable or path")
    args = parser.parse_args()
    verifier = args.node_backend.resolve() / "src" / "utils" / "assistantCommandVerifier.js"
    if not verifier.is_file():
        parser.error("Node verifier not found in the provided backend")
    node = shutil.which(args.node_executable)
    if node is None:
        parser.error("Node executable not found")
    NodeInteropChecks.verifier_path = verifier
    NodeInteropChecks.node_executable = node
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(SignerChecks),
        unittest.defaultTestLoader.loadTestsFromTestCase(NodeInteropChecks),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
