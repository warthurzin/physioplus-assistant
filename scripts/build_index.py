import json
import logging

from app.core.config import get_settings
from app.rag.embeddings import Embedder
from app.rag.ingestion import build_knowledge_index


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = get_settings()
    encoder = Embedder(settings.embedding_model_name)

    print(f"Base: {settings.knowledge_dir}")
    print(f"Modelo de embeddings: {settings.embedding_model_name}")

    meta = build_knowledge_index(settings, encoder, show_progress=True)

    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"Índice salvo em {settings.index_dir}")

    if meta["chunks_over_token_limit"]:
        print(
            f"Atenção: {meta['chunks_over_token_limit']} chunks excedem "
            f"{meta['max_seq_length']} tokens e serão truncados na vetorização. "
            "Reduza CHUNK_MAX_WORDS."
        )


if __name__ == "__main__":
    main()
