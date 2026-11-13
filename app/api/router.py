from fastapi import APIRouter

from app.api.routes import chat, health, retrieval
from app.core.config import Settings


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    router.include_router(health.router)
    router.include_router(chat.router)

    if settings.enable_debug_endpoints:
        router.include_router(retrieval.router)

    return router