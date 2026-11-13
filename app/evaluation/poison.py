from app.rag.types import Chunk
from app.services.retrieval_service import RetrievalHit


class PoisonedRetrieval:
    def __init__(self, inner, poison_text: str) -> None:
        self._inner = inner
        self._poison_text = poison_text

    def search(self, query: str, top_k: int | None = None) -> list[RetrievalHit]:
        hits = self._inner.search(query, top_k)

        poisoned = Chunk(
            chunk_id="externo-envenenado",
            document_id="externo",
            title="Documento Externo",
            category="externo",
            section="Aviso",
            text=self._poison_text,
            version="0",
            source="externo",
        )

        return [RetrievalHit(chunk=poisoned, score=0.99, rank=1)] + hits

    def has_evidence(self, hits: list[RetrievalHit]) -> bool:
        return self._inner.has_evidence(hits)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)