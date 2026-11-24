import hashlib
import json
from pathlib import Path
from typing import Sequence

from app.llm.base import LLMClient, LLMResponse


class CachingLLMClient:
    def __init__(
        self,
        inner: LLMClient,
        cache_dir: Path,
        use_cache: bool = True,
        resample: bool = False,
    ) -> None:
        self.model_name = inner.model_name
        self._inner = inner
        self._cache_dir = cache_dir
        self._use_cache = use_cache
        self._resample = resample
        self.hits = 0
        self.misses = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

        cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, messages, temperature, max_tokens, json_mode) -> str:
        payload = json.dumps(
            {
                "model": self.model_name,
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def complete(
        self,
        messages: Sequence[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 600,
        json_mode: bool = False,
    ) -> LLMResponse:
        path = self._cache_dir / f"{self._key(messages, temperature, max_tokens, json_mode)}.json"
        sampling = self._resample and temperature > 0

        if self._use_cache and not sampling and path.exists():
            self.hits += 1
            return LLMResponse(**json.loads(path.read_text(encoding="utf-8")))

        response = self._inner.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

        self.misses += 1
        self.prompt_tokens += response.prompt_tokens
        self.completion_tokens += response.completion_tokens

        if response.text and not sampling:
            path.write_text(
                json.dumps(
                    {
                        "text": response.text,
                        "finish_reason": response.finish_reason,
                        "prompt_tokens": response.prompt_tokens,
                        "completion_tokens": response.completion_tokens,
                        "key_index": response.key_index,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        return response