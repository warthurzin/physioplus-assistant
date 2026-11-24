import base64
import json
import math
import re
import time
from typing import Callable
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DOMAIN = b"PhysioPlus/assistant-command/v1\x00"
PURPOSE = "physioplus.assistant.execute"
MAX_COMMAND_BYTES = 16 * 1024
MAX_SAFE_INTEGER = (1 << 53) - 1
MAX_LIFETIME_SECONDS = 300
KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
ACTIONS = frozenset({
    "create_patient",
    "update_patient",
    "deactivate_patient",
    "reactivate_patient",
    "create_appointment",
    "cancel_appointment",
    "confirm_appointment",
    "set_session_payment",
})

MESSAGES = {
    "INVALID_KEY": "A chave deve ser uma chave privada Ed25519.",
    "INVALID_KEY_ID": "Identificador de chave inválido.",
    "INVALID_COMMAND": "Formato do comando inválido.",
    "INVALID_TIME": "Limites temporais do comando inválidos.",
    "COMMAND_TOO_LARGE": "Comando excede o tamanho permitido.",
}


class AssistantCommandSigningError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(MESSAGES[code])
        self.code = code


def _validate_json(value, remaining: list[int], depth: int = 0) -> None:
    remaining[0] -= 1
    if depth > 8 or remaining[0] < 0:
        raise AssistantCommandSigningError("INVALID_COMMAND")
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        try:
            length = len(value.encode("utf-16-le")) // 2
        except UnicodeEncodeError:
            raise AssistantCommandSigningError("INVALID_COMMAND") from None
        if length <= 2048:
            return
    elif type(value) in (int, float):
        if abs(value) <= MAX_SAFE_INTEGER and (type(value) is int or math.isfinite(value)):
            return
    elif type(value) is list and len(value) <= 100:
        for item in value:
            _validate_json(item, remaining, depth + 1)
        return
    elif type(value) is dict and len(value) <= 64:
        for key, item in value.items():
            if (
                type(key) is not str
                or not FIELD_NAME.fullmatch(key)
                or key in {"__proto__", "prototype", "constructor"}
            ):
                raise AssistantCommandSigningError("INVALID_COMMAND")
            _validate_json(item, remaining, depth + 1)
        return
    raise AssistantCommandSigningError("INVALID_COMMAND")


def _serialize(command: dict) -> bytes:
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    parts = []
    size = 0
    for part in encoder.iterencode(command):
        encoded = part.encode("utf-8")
        size += len(encoded)
        if size > MAX_COMMAND_BYTES:
            raise AssistantCommandSigningError("COMMAND_TOO_LARGE")
        parts.append(encoded)
    return b"".join(parts)


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class AssistantCommandSigner:
    def __init__(
        self,
        key_id: str,
        private_key: Ed25519PrivateKey,
        clock: Callable[[], int] = lambda: int(time.time()),
    ) -> None:
        if not isinstance(private_key, Ed25519PrivateKey):
            raise AssistantCommandSigningError("INVALID_KEY")
        if type(key_id) is not str or not KEY_ID.fullmatch(key_id):
            raise AssistantCommandSigningError("INVALID_KEY_ID")
        if not callable(clock):
            raise AssistantCommandSigningError("INVALID_TIME")
        self._key_id = key_id
        self._private_key = private_key
        self._clock = clock

    def sign(
        self,
        *,
        professional_id: str,
        action: str,
        parameters: dict,
        preconditions: dict,
        ttl_seconds: int = MAX_LIFETIME_SECONDS,
    ) -> dict[str, str]:
        if (
            type(professional_id) is not str
            or not UUID.fullmatch(professional_id)
            or type(action) is not str
            or action not in ACTIONS
            or type(parameters) is not dict
            or type(preconditions) is not dict
        ):
            raise AssistantCommandSigningError("INVALID_COMMAND")
        remaining = [MAX_COMMAND_BYTES]
        _validate_json(parameters, remaining)
        _validate_json(preconditions, remaining)
        issued_at = self._clock()
        if (
            type(issued_at) is not int
            or issued_at <= 0
            or type(ttl_seconds) is not int
            or not 1 <= ttl_seconds <= MAX_LIFETIME_SECONDS
            or issued_at + ttl_seconds > MAX_SAFE_INTEGER
        ):
            raise AssistantCommandSigningError("INVALID_TIME")
        command_bytes = _serialize({
            "version": 1,
            "purpose": PURPOSE,
            "execution_id": str(uuid4()),
            "professional_id": professional_id,
            "action": action,
            "issued_at": issued_at,
            "expires_at": issued_at + ttl_seconds,
            "parameters": parameters,
            "preconditions": preconditions,
        })
        signed_bytes = DOMAIN + self._key_id.encode("ascii") + b"\x00" + command_bytes
        signature = self._private_key.sign(signed_bytes)
        return {
            "key_id": self._key_id,
            "command": _base64url(command_bytes),
            "signature": _base64url(signature),
        }
