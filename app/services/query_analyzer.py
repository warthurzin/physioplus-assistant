import logging
from dataclasses import dataclass
from types import ModuleType
from typing import Literal

from pydantic import BaseModel

from app.core.exceptions import LLMError
from app.llm.base import LLMClient, LLMResponse, extract_json
from app.services.operational_intent import operational_intent

logger = logging.getLogger("physioplus.analyzer")

Intent = Literal["DOCUMENTACAO", "DADOS_OU_ACAO", "SAUDACAO", "FORA_ESCOPO"]
VALID_INTENTS = {"DOCUMENTACAO", "DADOS_OU_ACAO", "SAUDACAO", "FORA_ESCOPO"}
MAX_STANDALONE_CHARS = 500


class QueryAnalysis(BaseModel):
    intent: Intent
    standalone_question: str
    fallback: bool = False


@dataclass(frozen=True)
class AnalysisResult:
    analysis: QueryAnalysis
    response: LLMResponse | None


class QueryAnalyzer:
    def __init__(self, llm: LLMClient, prompts: ModuleType, enabled: bool = True) -> None:
        self._llm = llm
        self._prompts = prompts
        self._enabled = enabled

    def _fallback(self, message: str, flagged: bool) -> QueryAnalysis:
        return QueryAnalysis(
            intent="DOCUMENTACAO",
            standalone_question=message,
            fallback=flagged,
        )

    def analyze(self, message: str, history_text: str = "") -> AnalysisResult:
        if operational_intent(message, history_text):
            return AnalysisResult(QueryAnalysis(intent="DADOS_OU_ACAO", standalone_question=message), None)
        if not self._enabled:
            return AnalysisResult(self._fallback(message, False), None)

        messages = self._prompts.build_analysis_messages(message, history_text)
        response = None

        try:
            response = self._llm.complete(
                messages,
                temperature=0.0,
                max_tokens=600,
                json_mode=True,
            )
            data = extract_json(response.text)

            intent = str(data.get("intent", "")).strip().upper()

            if intent not in VALID_INTENTS:
                raise ValueError(f"intent inválida: {intent!r}")

            standalone = str(data.get("standalone_question", "")).strip()[:MAX_STANDALONE_CHARS]

            analysis = QueryAnalysis(
                intent=intent,
                standalone_question=standalone or message,
            )
        except (LLMError, ValueError) as error:
            logger.warning(
                "Análise falhou (%s). Seguindo com a pergunta original.",
                type(error).__name__,
            )
            return AnalysisResult(self._fallback(message, True), response)

        return AnalysisResult(analysis, response)
