import re
import unicodedata

from app.rag.knowledge import KnowledgeDocument
from app.rag.types import Chunk

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
DEFAULT_SECTION = "Visão geral"


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug or "secao"


def split_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = DEFAULT_SECTION
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_title, body))

    for line in markdown.splitlines():
        match = HEADING_PATTERN.match(line)

        if match:
            level = len(match.group(1))

            if level == 1:
                continue

            if level == 2:
                flush()
                current_title = match.group(2).strip()
                current_lines = []
                continue

            current_lines.append(match.group(2))
            continue

        current_lines.append(line)

    flush()

    return sections


def extract_units(body: str) -> list[str]:
    units: list[str] = []

    for line in body.splitlines():
        cleaned = BULLET_PATTERN.sub("", line).replace("**", "").replace("`", "").strip()

        if not cleaned:
            continue

        if not cleaned.endswith((".", "!", "?", ":", ";")):
            cleaned += "."

        for sentence in SENTENCE_BOUNDARY.split(cleaned):
            sentence = sentence.strip()
            if sentence:
                units.append(sentence)

    return units


def pack_units(units: list[str], max_words: int, overlap: int) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    count = 0

    for unit in units:
        words = len(unit.split())

        if current and count + words > max_words:
            groups.append(current)
            current = current[-overlap:] if overlap > 0 else []
            count = sum(len(item.split()) for item in current)

            if count + words > max_words:
                current = []
                count = 0

        current.append(unit)
        count += words

    if current:
        groups.append(current)

    return groups


def chunk_document(
    document: KnowledgeDocument,
    max_words: int,
    overlap_sentences: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []

    for section_index, (section, body) in enumerate(split_sections(document.content), start=1):
        groups = pack_units(extract_units(body), max_words, overlap_sentences)

        for part, group in enumerate(groups, start=1):
            chunks.append(
                Chunk(
                    chunk_id=f"{document.document_id}-{section_index:02d}-{slugify(section)}-{part}",
                    document_id=document.document_id,
                    title=document.title,
                    category=document.category,
                    section=section,
                    text=" ".join(group),
                    version=document.version,
                    source=document.source,
                )
            )

    return chunks


def chunk_documents(
    documents: list[KnowledgeDocument],
    max_words: int,
    overlap_sentences: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []

    for document in documents:
        chunks.extend(chunk_document(document, max_words, overlap_sentences))

    return chunks
