import re
import unicodedata

from app.services.text_utils import CITATION_PATTERN, strip_citations

CONTEXT_SOURCE_PATTERN = re.compile(r"^\[Fonte\s+(\d+)\s+-", re.MULTILINE)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def missing_facts(answer: str, groups: list[list[str]]) -> list[str]:
    normalized = normalize(answer)

    return [
        group[0]
        for group in groups
        if not any(normalize(alternative) in normalized for alternative in group)
    ]


def forbidden_found(answer: str, forbidden: list[str]) -> list[str]:
    normalized = normalize(answer)

    return [item for item in forbidden if normalize(item) in normalized]


def citation_problems(answer: str, context: str) -> list[str]:
    cited = [int(number) for number in CITATION_PATTERN.findall(answer)]
    available = {int(number) for number in CONTEXT_SOURCE_PATTERN.findall(context)}
    problems = []

    if not cited:
        problems.append("sem citação")

    invalid = sorted({number for number in cited if number not in available})

    if invalid:
        problems.append(f"citações inválidas: {invalid}")

    return problems