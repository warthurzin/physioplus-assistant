from datetime import datetime, timezone

from app.core.config import Settings
from app.core.exceptions import KnowledgeBaseError
from app.rag.chunking import chunk_documents
from app.rag.embeddings import TextEncoder
from app.rag.index_store import build_faiss_index, save_index
from app.rag.knowledge import compute_fingerprint, load_documents


def chunk_settings_signature(settings: Settings) -> str:
    return f"{settings.chunk_max_words}:{settings.chunk_overlap_sentences}"


def build_knowledge_index(
    settings: Settings,
    encoder: TextEncoder,
    show_progress: bool = False,
) -> dict:
    documents = load_documents(settings.manifest_path)

    chunks = chunk_documents(
        documents,
        settings.chunk_max_words,
        settings.chunk_overlap_sentences,
    )

    if not chunks:
        raise KnowledgeBaseError("Nenhum chunk foi gerado a partir dos documentos")

    texts = [chunk.embedding_text for chunk in chunks]

    vectors = encoder.encode(texts, show_progress=show_progress)
    token_counts = encoder.count_tokens(texts)
    index = build_faiss_index(vectors)

    meta = {
        "embedding_model": encoder.model_name,
        "dimension": int(vectors.shape[1]),
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "chunk_max_words": settings.chunk_max_words,
        "chunk_overlap_sentences": settings.chunk_overlap_sentences,
        "max_seq_length": encoder.max_seq_length,
        "max_chunk_tokens": max(token_counts),
        "chunks_over_token_limit": sum(
            1 for count in token_counts if count > encoder.max_seq_length
        ),
        "knowledge_fingerprint": compute_fingerprint(
            documents,
            chunk_settings_signature(settings),
        ),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }

    save_index(settings.index_dir, index, chunks, meta)

    return meta
