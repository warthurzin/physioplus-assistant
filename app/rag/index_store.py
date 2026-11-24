import json
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from app.core.exceptions import IndexNotLoadedError
from app.rag.types import Chunk

FAISS_FILE = "faiss.index"
CHUNKS_FILE = "chunks.json"
META_FILE = "meta.json"


@dataclass
class StoredIndex:
    index: faiss.Index
    chunks: list[Chunk]
    meta: dict


def build_faiss_index(vectors: np.ndarray) -> faiss.Index:
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    return index


def save_index(directory: Path, index: faiss.Index, chunks: list[Chunk], meta: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(directory / FAISS_FILE))

    (directory / CHUNKS_FILE).write_text(
        json.dumps([chunk.to_dict() for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (directory / META_FILE).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_index(directory: Path) -> StoredIndex:
    paths = [directory / FAISS_FILE, directory / CHUNKS_FILE, directory / META_FILE]

    if not all(path.exists() for path in paths):
        raise IndexNotLoadedError(
            f"Índice não encontrado em {directory}. Execute 'python -m scripts.build_index'."
        )

    index = faiss.read_index(str(paths[0]))
    chunks = [
        Chunk.from_dict(item)
        for item in json.loads(paths[1].read_text(encoding="utf-8"))
    ]
    meta = json.loads(paths[2].read_text(encoding="utf-8"))

    if index.ntotal != len(chunks):
        raise IndexNotLoadedError(
            "Índice inconsistente: quantidade de vetores diferente da quantidade de chunks. "
            "Reconstrua o índice."
        )

    return StoredIndex(index=index, chunks=chunks, meta=meta)
