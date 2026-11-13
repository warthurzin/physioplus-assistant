from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.actions.service import ActionService
from app.core.exceptions import ActionsDisabledError, LLMConfigError
from app.services.chat_service import ChatService
from app.services.retrieval_service import RetrievalService

bearer_scheme = HTTPBearer(auto_error=False, description="Token de acesso do PhysioPlus, sem o prefixo Bearer")


def get_retrieval_service(request: Request) -> RetrievalService:
    return request.app.state.retrieval_service


def get_chat_service(request: Request) -> ChatService:
    service = request.app.state.chat_service

    if service is None:
        raise LLMConfigError(
            "O modelo de linguagem não está configurado. Defina GROQ_API_KEYS no arquivo .env."
        )

    return service


def get_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None

    return credentials.credentials.strip() or None


def get_action_service(request: Request) -> ActionService:
    service = request.app.state.action_service

    if service is None:
        raise ActionsDisabledError("As ações do assistente não estão habilitadas.")

    return service