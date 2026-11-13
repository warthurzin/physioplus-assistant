from fastapi import APIRouter, Depends

from app.api.dependencies import get_retrieval_service
from app.schemas.retrieval import SearchHit, SearchRequest, SearchResponse
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/debug/retrieval", tags=["debug"])


@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    service: RetrievalService = Depends(get_retrieval_service),
) -> SearchResponse:
    top_k = payload.top_k or service.default_top_k
    hits = service.search(payload.query, top_k)

    return SearchResponse(
        query=payload.query,
        top_k=top_k,
        threshold=service.threshold,
        max_score=hits[0].score if hits else 0.0,
        evidence_sufficient=service.has_evidence(hits),
        hits=[
            SearchHit(
                rank=hit.rank,
                chunk_id=hit.chunk.chunk_id,
                document_id=hit.chunk.document_id,
                title=hit.chunk.title,
                section=hit.chunk.section,
                score=hit.score,
                text=hit.chunk.text,
            )
            for hit in hits
        ],
    )
