import base64
import json


def user_id_from_token(token: str | None) -> str | None:
    if not token:
        return None

    parts = token.split(".")

    if len(parts) != 3:
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return None

    subject = payload.get("sub") if isinstance(payload, dict) else None

    return str(subject) if subject else None