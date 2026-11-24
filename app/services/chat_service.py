import logging
import re
import time
from dataclasses import dataclass, field

from app.actions.service import ActionService
from app.core.config import Settings
from app.graph.builder import build_assistant_graph
from app.graph.nodes import EMPTY_USAGE, GraphNodes
from app.llm.base import LLMClient
from app.prompts import get_prompts
from app.services.answer_verifier import AnswerVerifier
from app.services.data_planner import DataPlanner
from app.services.query_analyzer import QueryAnalyzer
from app.services.retrieval_service import RetrievalService
from app.tools.service import DataToolService

logger = logging.getLogger("physioplus.chat")

CITATION_PATTERN = re.compile(r"\[Fonte\s+(\d+)\]", re.IGNORECASE)
HISTORY_MESSAGE_MAX_CHARS = 500


@dataclass(frozen=True)
class SourceRef:
    number: int
    chunk_id: str
    document_id: str
    title: str
    section: str
    score: float


@dataclass(frozen=True)
class ChatResult:
    answer: str
    intent: str
    grounded: bool
    abstained: bool
    sources: list[SourceRef]
    debug: dict = field(default_factory=dict)
    context: str = ""
    data_source: str | None = None
    proposal: dict | None = None
    report: dict | None = None
    title: str | None = None


def format_history(history: list[dict], max_turns: int) -> str:
    if max_turns <= 0 or not history:
        return ""

    lines = []

    for item in history[-(max_turns * 2) :]:
        label = "Usuário" if item["role"] == "user" else "Assistente"
        content = item["content"].strip()[:HISTORY_MESSAGE_MAX_CHARS]
        lines.append(f"{label}: {content}")

    return "\n".join(lines)


def extract_cited_sources(answer: str, hits: list) -> list[SourceRef]:
    numbers: list[int] = []

    for match in CITATION_PATTERN.findall(answer):
        number = int(match)

        if 1 <= number <= len(hits) and number not in numbers:
            numbers.append(number)

    sources = []

    for number in numbers:
        hit = hits[number - 1]
        sources.append(
            SourceRef(
                number=number,
                chunk_id=hit.chunk.chunk_id,
                document_id=hit.chunk.document_id,
                title=hit.chunk.title,
                section=hit.chunk.section,
                score=hit.score,
            )
        )

    return sources


class ChatService:
    def __init__(
        self,
        settings: Settings,
        retrieval: RetrievalService,
        llm: LLMClient,
        data_service: DataToolService | None = None,
        action_service: ActionService | None = None,
    ) -> None:
        self._settings = settings
        self.llm_model = llm.model_name

        prompts = get_prompts(settings.prompt_version)
        analyzer = QueryAnalyzer(llm, prompts, enabled=settings.query_analysis_enabled)
        verifier = AnswerVerifier(llm) if settings.verify_answers else None
        planner = DataPlanner(llm, settings.timezone) if data_service is not None else None
        nodes = GraphNodes(settings, retrieval, analyzer, llm, prompts, verifier, planner, data_service, action_service)

        self._graph = build_assistant_graph(
            nodes,
            verify_enabled=verifier is not None,
            data_enabled=data_service is not None,
        )

    def answer(
        self,
        message: str,
        history: list[dict] | None = None,
        access_token: str | None = None,
    ) -> ChatResult:
        started = time.perf_counter()

        state = self._graph.invoke(
            {
                "message": message,
                "history_text": format_history(history or [], self._settings.history_max_turns),
                "usage": dict(EMPTY_USAGE),
                "has_token": bool(access_token),
            },
            config={"configurable": {"access_token": access_token or ""}},
        )

        hits = state.get("hits", [])
        answer = state["answer"]
        path = state["path"]
        abstained = state.get("abstained", False)

        sources = (
            extract_cited_sources(answer, hits)
            if path == "documentacao_resposta"
            else []
        )

        latency_ms = round((time.perf_counter() - started) * 1000)

        logger.info(
            "Chat: path=%s intent=%s llm_calls=%d latency_ms=%d",
            path,
            state.get("intent"),
            state["usage"]["llm_calls"],
            latency_ms,
        )

        return ChatResult(
            answer=re.sub(r"[ \t]+(?=[.,;:!?])", "", re.sub(r"[ \t]+\n", "\n", CITATION_PATTERN.sub("", answer))).strip(),
            intent=state.get("intent", ""),
            grounded=path == "documentacao_resposta" and bool(sources),
            abstained=abstained,
            sources=sources,
            context=state.get("context", ""),
            data_source=state.get("plan_tool") if path == "dados_resposta" else None,
            proposal=state.get("proposal"),
            report=state.get("tool_data", {}).get("report") if state.get("plan_tool") == "get_financial_summary" and state.get("tool_status") == "ok" else None,
            title=(f"Agendamento de {state['plan_args']['patient_name']}" if state.get("plan_tool") == "create_appointment" and state.get("plan_args", {}).get("patient_name") else None),
            debug={
                "path": path,
                "search_query": state.get("standalone_question", ""),
                "analysis_fallback": state.get("analysis_fallback", False),
                "max_score": state.get("max_score", 0.0),
                "threshold": self._settings.evidence_threshold,
                "llm_model": self.llm_model,
                "prompt_version": self._settings.prompt_version,
                "latency_ms": latency_ms,
                "verification": state.get("verification", "nao_executada"),
                "verification_note": state.get("verification_note", ""),
                "rejected_answer": state.get("rejected_answer"),
                "tool": state.get("plan_tool"),
                "tool_status": state.get("tool_status"),
                "numeric_guard": state.get("numeric_guard"),
                **state["usage"],
            },
        )
