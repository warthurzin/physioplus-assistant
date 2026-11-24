import logging
from dataclasses import dataclass

from app.core.config import Settings
from app.core.exceptions import (
    AssistantError,
    IndexMismatchError,
    IndexNotLoadedError,
)
from app.rag.embeddings import TextEncoder
from app.rag.index_store import StoredIndex, load_index
from app.rag.ingestion import chunk_settings_signature
from app.rag.knowledge import compute_fingerprint, load_documents
from app.rag.types import Chunk

logger = logging.getLogger("physioplus.retrieval")


@dataclass(frozen=True)
class RetrievalHit:
    chunk: Chunk
    score: float
    rank: int


class RetrievalService:
    def __init__(self, settings: Settings, encoder: TextEncoder) -> None:
        self._settings = settings
        self._encoder = encoder
        self._stored: StoredIndex | None = None
        self._stale = False

    @property
    def is_loaded(self) -> bool:
        return self._stored is not None

    @property
    def is_stale(self) -> bool:
        return self._stale

    @property
    def default_top_k(self) -> int:
        return self._settings.top_k

    @property
    def threshold(self) -> float:
        return self._settings.evidence_threshold

    @property
    def embedding_model(self) -> str:
        return self._settings.embedding_model_name

    @property
    def chunk_count(self) -> int | None:
        return len(self._stored.chunks) if self._stored else None

    @property
    def document_count(self) -> int | None:
        return self._stored.meta.get("document_count") if self._stored else None

    def load(self) -> None:
        stored = load_index(self._settings.index_dir)

        built_with = stored.meta.get("embedding_model")

        if built_with != self._settings.embedding_model_name:
            raise IndexMismatchError(
                f"O índice foi construído com '{built_with}', mas a configuração atual usa "
                f"'{self._settings.embedding_model_name}'. Reconstrua o índice."
            )

        self._stored = stored
        self._stale = self._detect_stale(stored)

        if self._stale:
            logger.warning(
                "A base de conhecimento mudou desde a construção do índice. "
                "Execute 'python -m scripts.build_index'."
            )

        logger.info("Índice carregado: %d chunks", len(stored.chunks))

    def _detect_stale(self, stored: StoredIndex) -> bool:
        try:
            documents = load_documents(self._settings.manifest_path)
        except AssistantError:
            return True

        current = compute_fingerprint(documents, chunk_settings_signature(self._settings))

        return current != stored.meta.get("knowledge_fingerprint")

    def warm_up(self) -> None:
        self._encoder.encode(["aquecimento"])

    def search(self, query: str, top_k: int | None = None) -> list[RetrievalHit]:
        if self._stored is None:
            raise IndexNotLoadedError(
                "O índice não está carregado. Execute 'python -m scripts.build_index' "
                "e reinicie o serviço."
            )

        limit = min(top_k or self._settings.top_k, self._stored.index.ntotal)

        vector = self._encoder.encode([query])
        scores, positions = self._stored.index.search(vector, limit)

        hits: list[RetrievalHit] = []

        for rank, (score, position) in enumerate(zip(scores[0], positions[0]), start=1):
            if position < 0:
                continue

            hits.append(
                RetrievalHit(
                    chunk=self._stored.chunks[position],
                    score=float(score),
                    rank=rank,
                )
            )

        logger.info(
            "Busca: query_chars=%d hits=%d score_max=%.4f",
            len(query),
            len(hits),
            hits[0].score if hits else 0.0,
        )

        return hits

    def has_evidence(self, hits: list[RetrievalHit]) -> bool:
        return bool(hits) and hits[0].score >= self._settings.evidence_threshold
