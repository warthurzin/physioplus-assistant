import re

NUMBER_PATTERN = re.compile(r"\d[\d.,/:]*")
LIST_MARKER_PATTERN = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)


def unsupported_number(answer: str, allowed_text: str) -> str | None:
    cleaned = LIST_MARKER_PATTERN.sub("", answer)

    for token in NUMBER_PATTERN.findall(cleaned):
        token = token.rstrip(".,:/")

        if token and token not in allowed_text:
            return token

    return None