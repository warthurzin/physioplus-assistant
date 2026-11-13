from fastapi import APIRouter, Depends, HTTPException

from app.actions.service import ActionService
from app.api.dependencies import get_access_token, get_action_service, get_chat_service
from app.core.config import Settings, get_settings
from app.schemas.chat import (
    ChatDebug,
    ChatRequest,
    ChatResponse,
    ChatSource,
    ConfirmRequest,
    ConfirmResponse,
    Proposal,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings),
    access_token: str | None = Depends(get_access_token),
) -> ChatResponse:
    result = service.answer(
        payload.message,
        [item.model_dump() for item in payload.history],
        access_token,
    )

    return ChatResponse(
        answer=result.answer,
        intent=result.intent,
        grounded=result.grounded,
        abstained=result.abstained,
        sources=[
            ChatSource(
                number=source.number,
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                title=source.title,
                section=source.section,
                score=source.score,
            )
            for source in result.sources
        ],
        data_source=result.data_source,
        proposal=Proposal(**result.proposal) if result.proposal else None,
        debug=ChatDebug(**result.debug) if settings.enable_debug_endpoints else None,
    )


@router.post("/confirm", response_model=ConfirmResponse)
def confirm(
    payload: ConfirmRequest,
    service: ActionService = Depends(get_action_service),
    access_token: str | None = Depends(get_access_token),
) -> ConfirmResponse:
    if not access_token:
        raise HTTPException(status_code=401, detail="Autenticação necessária")

    result = service.confirm(payload.proposal, access_token)

    return ConfirmResponse(status=result.status, message=result.message, action=result.action)