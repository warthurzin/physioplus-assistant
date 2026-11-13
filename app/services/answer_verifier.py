import logging
from dataclasses import dataclass

from app.core.exceptions import LLMError
from app.llm.base import LLMClient, LLMResponse, extract_json
from app.prompts.verification import build_verification_messages
from app.services.text_utils import strip_citations

logger = logging.getLogger("physioplus.verifier")

APPROVED = "aprovada"
REJECTED = "rejeitada"
UNAVAILABLE = "indisponivel"
MAX_NOTE_CHARS = 300


@dataclass(frozen=True)
class VerificationResult:
    verdict: str
    note: str
    response: LLMResponse | None


class AnswerVerifier:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def verify(self, context: str, answer: str) -> VerificationResult:
        messages = build_verification_messages(context, strip_citations(answer))
        response = None

        try:
            response = self._llm.complete(
                messages,
                temperature=0.0,
                max_tokens=300,
                json_mode=True,
            )
            data = extract_json(response.text)
            supported = data.get("suportada")

            if not isinstance(supported, bool):
                raise ValueError("campo suportada ausente ou inválido")
        except (LLMError, ValueError) as error:
            logger.warning("Verificação indisponível (%s). Resposta mantida.", type(error).__name__)
            return VerificationResult(UNAVAILABLE, type(error).__name__, response)

        return VerificationResult(
            APPROVED if supported else REJECTED,
            str(data.get("observacao", ""))[:MAX_NOTE_CHARS],
            response,
        )