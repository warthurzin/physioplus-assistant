import base64
import hashlib
import json
import time

from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import ActionsDisabledError


class ProposalError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProposalSigner:
    def __init__(self, secret: str, ttl_seconds: int, clock=time.time) -> None:
        if not isinstance(secret, str) or len(secret.strip()) < 32:
            raise ActionsDisabledError("ASSISTANT_SIGNING_SECRET deve conter pelo menos 32 caracteres.")

        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)
        self._ttl = ttl_seconds
        self._clock = clock

    @property
    def ttl(self) -> int:
        return self._ttl

    def sign(self, payload: dict) -> str:
        data = {**payload, "exp": int(self._clock() + self._ttl)}
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        return self._fernet.encrypt_at_time(body, int(self._clock())).decode("ascii")

    def verify(self, token: str) -> dict:
        try:
            body = self._fernet.decrypt(token.encode("ascii"))
            data = json.loads(body)
        except (InvalidToken, ValueError, TypeError, UnicodeEncodeError) as error:
            raise ProposalError("invalid") from error

        expires = data.get("exp") if isinstance(data, dict) else None

        if not isinstance(expires, (int, float)):
            raise ProposalError("invalid")

        if expires < self._clock():
            raise ProposalError("expired")

        return data
