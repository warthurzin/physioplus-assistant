import logging
import math
import threading
import time
from typing import Callable, Sequence

import groq
import httpx
from groq import Groq

from app.core.config import Settings
from app.core.exceptions import LLMConfigError, LLMRequestError, LLMUnavailableError
from app.llm.base import LLMResponse, strip_thinking

logger = logging.getLogger("physioplus.llm")

RATE_LIMIT_DEFAULT_COOLDOWN = 60.0
KEY_FAILURE_COOLDOWN = 600.0
TRANSIENT_COOLDOWN = 5.0
MAX_COOLDOWN = 300.0
MAX_ATTEMPT_ROUNDS = 6

REQUEST_ERRORS = (
    groq.BadRequestError,
    groq.NotFoundError,
    groq.UnprocessableEntityError,
)
KEY_ERRORS = (groq.AuthenticationError, groq.PermissionDeniedError)
TRANSIENT_ERRORS = (groq.APIConnectionError, groq.InternalServerError)


def _retry_after_seconds(error: groq.RateLimitError) -> float:
    try:
        header = error.response.headers.get("retry-after")
        if header:
            return min(max(float(header), 1.0), MAX_COOLDOWN)
    except (AttributeError, ValueError):
        pass

    return RATE_LIMIT_DEFAULT_COOLDOWN


class GroqLLMClient:
    def __init__(
        self,
        settings: Settings,
        clients: list | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model_name = settings.groq_model
        self._reasoning_effort = settings.groq_reasoning_effort.strip()
        self._max_wait = settings.llm_rate_limit_max_wait_seconds
        self._min_interval = settings.llm_min_interval_seconds
        self._sleep = sleep

        if clients is None:
            keys = settings.groq_key_list

            if not keys:
                raise LLMConfigError(
                    "Nenhuma chave do Groq configurada. Defina GROQ_API_KEYS no arquivo .env."
                )

            retries = 0 if len(keys) > 1 else 2
            timeout = httpx.Timeout(
                settings.llm_timeout_seconds,
                connect=settings.llm_connect_timeout_seconds,
            )

            def build_client(key: str) -> Groq:
                http_client = None

                if settings.force_ipv4:
                    http_client = httpx.Client(
                        timeout=timeout,
                        transport=httpx.HTTPTransport(local_address="0.0.0.0"),
                    )

                return Groq(api_key=key, timeout=timeout, max_retries=retries, http_client=http_client)

            clients = [build_client(key) for key in keys]

        self._clients = clients
        self._cooldown_until = [0.0] * len(clients)
        self._last_call = [-math.inf] * len(clients)
        self._cursor = len(clients) - 1
        self._lock = threading.Lock()

    @property
    def key_count(self) -> int:
        return len(self._clients)

    def _reserve(self) -> tuple[int | None, float]:
        now = time.monotonic()

        with self._lock:
            total = len(self._clients)
            order = [(self._cursor + 1 + offset) % total for offset in range(total)]
            available = [i for i in order if self._cooldown_until[i] <= now]

            if not available:
                return None, max(min(self._cooldown_until) - now, 0.0)

            best = min(available, key=lambda i: self._last_call[i])
            start = max(now, self._last_call[best] + self._min_interval)

            self._last_call[best] = start
            self._cursor = best

            return best, max(start - now, 0.0)

    def _cool(self, index: int, seconds: float) -> None:
        with self._lock:
            self._cooldown_until[index] = time.monotonic() + seconds

    def complete(
        self,
        messages: Sequence[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 600,
        json_mode: bool = False,
    ) -> LLMResponse:
        params: dict = {
            "model": self.model_name,
            "messages": list(messages),
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }

        if self._reasoning_effort:
            params["extra_body"] = {"reasoning_effort": self._reasoning_effort}

        if json_mode:
            params["response_format"] = {"type": "json_object"}

        for _ in range(MAX_ATTEMPT_ROUNDS * len(self._clients)):
            index, wait = self._reserve()

            if index is None:
                if wait > self._max_wait:
                    break

                logger.info("Todas as chaves pausadas, aguardando %.1fs", wait)
                self._sleep(wait)
                continue

            if wait > 0:
                self._sleep(wait)

            try:
                result = self._clients[index].chat.completions.create(**params)
            except REQUEST_ERRORS as error:
                raise LLMRequestError(f"Requisição recusada pelo Groq: {error}") from error
            except groq.RateLimitError as error:
                seconds = _retry_after_seconds(error)
                self._cool(index, seconds)
                logger.warning("Chave %d com limite de uso, pausada por %.0fs", index, seconds)
            except KEY_ERRORS as error:
                self._cool(index, KEY_FAILURE_COOLDOWN)
                logger.error("Chave %d recusada pelo Groq (%s)", index, type(error).__name__)
            except TRANSIENT_ERRORS as error:
                self._cool(index, TRANSIENT_COOLDOWN)
                logger.warning("Falha transitória na chave %d (%s)", index, type(error).__name__)
            else:
                choice = result.choices[0]
                usage = getattr(result, "usage", None)

                return LLMResponse(
                    text=strip_thinking(choice.message.content or ""),
                    finish_reason=str(choice.finish_reason),
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    key_index=index,
                )

        raise LLMUnavailableError(
            "Todas as chaves do Groq estão indisponíveis no momento. Tente novamente em instantes."
        )