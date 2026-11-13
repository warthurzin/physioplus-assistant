import logging
import secrets
from contextlib import asynccontextmanager

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import build_router
from app.core.config import get_settings
from app.actions.service import ActionService
from app.actions.signer import ProposalSigner
from app.core.exceptions import (
    ActionsDisabledError,
    AssistantError,
    IndexNotLoadedError,
    LLMConfigError,
    LLMEmptyResponseError,
    LLMRequestError,
    LLMUnavailableError,
)
from app.integrations.physio_api import PhysioApiClient
from app.llm.base import LLMClient
from app.rag.embeddings import Embedder
from app.services.chat_service import ChatService
from app.services.retrieval_service import RetrievalService
from app.tools.service import DataToolService

logger = logging.getLogger("physioplus.assistant")


def create_app(
    retrieval_service: RetrievalService | None = None,
    llm_client: LLMClient | None = None,
    data_service: DataToolService | None = None,
    action_service: ActionService | None = None,
) -> FastAPI:
    settings = get_settings()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service = retrieval_service or RetrievalService(
            settings,
            Embedder(settings.embedding_model_name),
        )

        try:
            service.load()
            service.warm_up()
        except AssistantError as error:
            logger.error("Falha ao carregar o índice: %s", error)

        llm = llm_client

        if llm is None:
            try:
                from app.llm.groq_client import GroqLLMClient

                llm = GroqLLMClient(settings)
                logger.info(
                    "Groq configurado: modelo=%s chaves=%d",
                    llm.model_name,
                    llm.key_count,
                )
            except LLMConfigError as error:
                logger.warning("%s", error)

        app.state.retrieval_service = service
        today_fn = lambda: datetime.now(ZoneInfo(settings.timezone)).date()
        tools = data_service
        actions = action_service
        api = None

        if (tools is None or actions is None) and settings.data_tools_enabled:
            api = PhysioApiClient(
                settings.physio_api_base_url,
                settings.physio_api_timeout_seconds,
                force_ipv4=settings.force_ipv4,
            )

        if tools is None and api is not None:
            tools = DataToolService(api, settings.tool_max_items, today_fn)

        if actions is None and api is not None and settings.actions_enabled:
            secret = settings.assistant_signing_secret

            if not secret:
                secret = secrets.token_urlsafe(32)
                logger.warning(
                    "ASSISTANT_SIGNING_SECRET não definido: usando chave temporária. "
                    "As propostas deixam de valer ao reiniciar."
                )

            actions = ActionService(
                api,
                ProposalSigner(secret, settings.proposal_ttl_seconds),
                today_fn,
                settings.default_appointment_minutes,
                settings.patient_actions_enabled,
            )

        app.state.action_service = actions
        app.state.chat_service = ChatService(settings, service, llm, tools, actions) if llm else None

        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def error_response(status_code: int):
        async def handler(request: Request, error: AssistantError):
            return JSONResponse(status_code=status_code, content={"detail": str(error)})

        return handler

    app.add_exception_handler(IndexNotLoadedError, error_response(503))
    app.add_exception_handler(LLMConfigError, error_response(503))
    app.add_exception_handler(ActionsDisabledError, error_response(503))
    app.add_exception_handler(LLMUnavailableError, error_response(503))
    app.add_exception_handler(LLMRequestError, error_response(502))
    app.add_exception_handler(LLMEmptyResponseError, error_response(502))

    app.include_router(build_router(settings))

    return app


app = create_app()