import logging
from uuid import UUID

from app.core.exceptions import (
    UpstreamAuthError,
    UpstreamError,
    UpstreamNotFoundError,
    UpstreamUnavailableError,
)
from app.integrations.physio_api import PhysioApiClient

logger = logging.getLogger("physioplus.auth")


def authenticated_user_id(api: PhysioApiClient, token: str) -> str:
    if not token:
        raise UpstreamAuthError("Autenticação necessária")

    try:
        user = api.get_current_user(token)
    except (UpstreamAuthError, UpstreamNotFoundError) as error:
        raise UpstreamAuthError("Sessão inválida ou expirada") from error
    except UpstreamError as error:
        logger.warning("Falha ao consultar auth/me (%s)", type(error).__name__)
        raise UpstreamUnavailableError("Serviço de autenticação indisponível") from error

    user_id = user.get("id") if isinstance(user, dict) else None
    try:
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("missing identity")
        UUID(user_id)
    except ValueError as error:
        logger.warning("Resposta de auth/me sem identidade UUID válida")
        raise UpstreamAuthError("Não foi possível validar a sessão") from error

    return user_id
