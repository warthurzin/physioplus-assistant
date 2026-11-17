from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

UserMessage = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
HistoryContent = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: HistoryContent


class ChatRequest(BaseModel):
    message: UserMessage
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class ChatSource(BaseModel):
    number: int
    chunk_id: str
    document_id: str
    title: str
    section: str
    score: float


class ChatDebug(BaseModel):
    path: str
    search_query: str
    analysis_fallback: bool
    max_score: float
    threshold: float
    llm_model: str
    prompt_version: str
    latency_ms: int
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    verification: str = "nao_executada"
    verification_note: str = ""
    rejected_answer: str | None = None
    tool: str | None = None
    tool_status: str | None = None
    numeric_guard: str | None = None


class Proposal(BaseModel):
    token: str
    action: str
    summary: str
    expires_in_seconds: int


class ConfirmRequest(BaseModel):
    proposal: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=40000)]


class ConfirmResponse(BaseModel):
    status: str
    message: str
    action: str | None = None


class ChatResponse(BaseModel):
    answer: str
    intent: str
    grounded: bool
    abstained: bool
    sources: list[ChatSource]
    data_source: str | None = None
    proposal: Proposal | None = None
    debug: ChatDebug | None = None
