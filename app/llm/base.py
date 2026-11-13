import json
import re
from dataclasses import dataclass
from typing import Protocol, Sequence

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    key_index: int = 0


class LLMClient(Protocol):
    model_name: str

    def complete(
        self,
        messages: Sequence[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 600,
        json_mode: bool = False,
    ) -> LLMResponse: ...


def strip_thinking(text: str) -> str:
    cleaned = THINK_BLOCK.sub("", text)

    if "<think>" in cleaned:
        cleaned = cleaned.split("<think>", 1)[0]

    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1]

    return cleaned.strip()


def extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("a resposta não contém um objeto JSON")

    data = json.loads(text[start : end + 1])

    if not isinstance(data, dict):
        raise ValueError("o JSON retornado não é um objeto")

    return data