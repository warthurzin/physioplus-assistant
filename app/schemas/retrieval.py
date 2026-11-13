from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class SearchRequest(BaseModel):
    query: Query
    top_k: int | None = Field(default=None, ge=1, le=20)


class SearchHit(BaseModel):
    rank: int
    chunk_id: str
    document_id: str
    title: str
    section: str
    score: float
    text: str


class SearchResponse(BaseModel):
    query: str
    top_k: int
    threshold: float
    max_score: float
    evidence_sufficient: bool
    hits: list[SearchHit]