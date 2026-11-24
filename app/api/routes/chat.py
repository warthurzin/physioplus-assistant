from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.actions.service import ActionService
from app.api.dependencies import get_access_token, get_action_service, get_chat_service
from app.core.config import Settings, get_settings
from app.core.exceptions import UpstreamNotFoundError
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
    request: Request,
    access_token: str = Depends(get_access_token),
    service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    api = request.app.state.physio_api_client
    conversation_id = str(payload.conversation_id) if payload.conversation_id else None
    history = [item.model_dump() for item in payload.history]
    if conversation_id:
        try:
            conversation = api.get_conversation(access_token, conversation_id)
        except UpstreamNotFoundError:
            raise HTTPException(404, "Conversa não encontrada") from None
        history = conversation["messages"][-20:]
    result = service.answer(
        payload.message,
        history,
        access_token,
    )
    report_message_index = None
    if conversation_id:
        try:
            saved = api.append_conversation(
                access_token,
                conversation_id,
                payload.message,
                (
                    "Proposta registrada (histórico; não executável).\n"
                    + result.proposal["summary"]
                    if result.proposal
                    else result.answer
                ),
                result.title,
                **({"report": result.report} if result.report else {}),
            )
            if result.report:
                report_message_index = len(saved["messages"]) - 1
        except UpstreamNotFoundError:
            raise HTTPException(404, "Conversa não encontrada") from None

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
        conversation_id=conversation_id,
        report=result.report,
        report_message_index=report_message_index,
    )


@router.get("/conversations")
def list_conversations(request: Request, token: str = Depends(get_access_token)):
    return request.app.state.physio_api_client.list_conversations(token)


@router.post("/conversations", status_code=201)
def create_conversation(request: Request, token: str = Depends(get_access_token)):
    return request.app.state.physio_api_client.create_conversation(token)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: UUID, request: Request, token: str = Depends(get_access_token)
):
    try:
        return request.app.state.physio_api_client.get_conversation(
            token, str(conversation_id)
        )
    except UpstreamNotFoundError:
        raise HTTPException(404, "Conversa não encontrada") from None


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID, request: Request, token: str = Depends(get_access_token)
):
    request.app.state.physio_api_client.delete_conversation(token, str(conversation_id))
    return Response(status_code=204)


@router.get("/reports/financial")
def financial_report(
    request: Request,
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    token: str = Depends(get_access_token),
):
    from app.services.financial_report import build_financial_pdf

    summary = request.app.state.physio_api_client.financial_summary(token, month, year)
    return Response(
        build_financial_pdf(summary, month, year),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="financeiro-{year}-{month:02d}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/conversations/{conversation_id}/reports/{message_index}")
def conversation_report(
    conversation_id: UUID,
    message_index: int,
    request: Request,
    token: str = Depends(get_access_token),
):
    from app.services.financial_report import build_financial_pdf
    from app.services.report_metadata import financial_snapshot

    api = request.app.state.physio_api_client
    try:
        conversation = api.get_conversation(token, str(conversation_id))
    except UpstreamNotFoundError:
        raise HTTPException(404, "Conversa não encontrada") from None
    messages = conversation.get("messages", [])
    if message_index < 0 or message_index >= len(messages):
        raise HTTPException(404, "Relatório não encontrado")
    message = messages[message_index]
    report = message.get("report") or {}
    month, year = report.get("month"), report.get("year")
    if (
        message.get("role") != "assistant"
        or report.get("type") != "financial"
        or type(month) is not int
        or not 1 <= month <= 12
        or type(year) is not int
        or not 2000 <= year <= 2100
    ):
        raise HTTPException(404, "Relatório não encontrado")
    summary = api.financial_summary(token, month, year)
    original = report.get("snapshot_hash")
    updated = (
        str(financial_snapshot(summary) != original).lower() if original else "unknown"
    )
    return Response(
        build_financial_pdf(summary, month, year),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="financeiro-{year}-{month:02d}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Report-Updated": updated,
        },
    )


@router.post("/confirm", response_model=ConfirmResponse)
def confirm(
    payload: ConfirmRequest,
    request: Request,
    access_token: str = Depends(get_access_token),
    service: ActionService = Depends(get_action_service),
) -> ConfirmResponse:
    api = request.app.state.physio_api_client
    if payload.conversation_id:
        try:
            api.get_conversation(access_token, str(payload.conversation_id))
        except UpstreamNotFoundError:
            raise HTTPException(404, "Conversa não encontrada") from None
    result = service.confirm(payload.proposal, access_token)
    if payload.conversation_id and result.status not in {"auth", "unavailable"}:
        import logging

        from app.core.exceptions import UpstreamError

        try:
            api.append_conversation(
                access_token,
                str(payload.conversation_id),
                "Confirmação explícita pelo botão de ação.",
                result.message,
                None,
            )
        except UpstreamError:
            # A successful execution must not be retried because history storage failed.
            logging.getLogger("physioplus.chat").warning(
                "Resultado confirmado; histórico indisponível"
            )

    return ConfirmResponse(
        status=result.status, message=result.message, action=result.action
    )


@router.post("/result", response_model=ConfirmResponse)
def recover_result(
    payload: ConfirmRequest,
    access_token: str = Depends(get_access_token),
    service: ActionService = Depends(get_action_service),
) -> ConfirmResponse:
    result = service.recover(payload.proposal, access_token)
    return ConfirmResponse(
        status=result.status, message=result.message, action=result.action
    )
