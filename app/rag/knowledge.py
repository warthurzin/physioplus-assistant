import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import KnowledgeBaseError


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    title: str
    category: str
    version: str
    source: str
    content: str


def load_documents(manifest_path: Path) -> list[KnowledgeDocument]:
    if not manifest_path.exists():
        raise KnowledgeBaseError(f"Manifesto não encontrado em {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("documents", [])

    if not entries:
        raise KnowledgeBaseError("O manifesto não lista nenhum documento")

    documents: list[KnowledgeDocument] = []
    seen_ids: set[str] = set()

    for entry in entries:
        document_id = entry["id"]

        if document_id in seen_ids:
            raise KnowledgeBaseError(f"Identificador de documento duplicado: {document_id}")

        seen_ids.add(document_id)

        file_path = manifest_path.parent / entry["file"]

        if not file_path.exists():
            raise KnowledgeBaseError(f"Arquivo não encontrado: {file_path}")

        documents.append(
            KnowledgeDocument(
                document_id=document_id,
                title=entry["title"],
                category=entry.get("category", ""),
                version=entry.get("version", "1.0"),
                source=entry.get("source", ""),
                content=file_path.read_text(encoding="utf-8"),
            )
        )

    return documents


def compute_fingerprint(documents: list[KnowledgeDocument], chunk_settings: str) -> str:
    digest = hashlib.sha256()
    digest.update(chunk_settings.encode("utf-8"))

    for document in sorted(documents, key=lambda item: item.document_id):
        digest.update(document.document_id.encode("utf-8"))
        digest.update(document.version.encode("utf-8"))
        digest.update(document.content.encode("utf-8"))

    return digest.hexdigest()
