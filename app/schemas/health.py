from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    index_loaded: bool
    index_stale: bool
    chunk_count: int | None = None
    document_count: int | None = None
    embedding_model: str
    llm_configured: bool
    llm_model: str | None = None