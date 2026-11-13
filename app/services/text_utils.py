import re
import unicodedata

CITATION_PATTERN = re.compile(r"\[Fonte\s+(\d+)\]")


def strip_citations(text: str) -> str:
    return CITATION_PATTERN.sub("", text).strip()


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower().strip()