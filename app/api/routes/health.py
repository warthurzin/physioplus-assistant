from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_retrieval_service
from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse
from app.services.retrieval_service import RetrievalService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(
    request: Request,
    service: RetrievalService = Depends(get_retrieval_service),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    chat_service = request.app.state.chat_service

    return HealthResponse(
        status="ok" if service.is_loaded and chat_service is not None else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        index_loaded=service.is_loaded,
        index_stale=service.is_stale,
        chunk_count=service.chunk_count,
        document_count=service.document_count,
        embedding_model=service.embedding_model,
        llm_configured=chat_service is not None,
        llm_model=chat_service.llm_model if chat_service is not None else None,
    )