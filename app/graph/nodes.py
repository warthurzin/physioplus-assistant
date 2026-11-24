import json
import logging
from types import ModuleType
from typing import Literal

from langchain_core.runnables import RunnableConfig

from app.actions.schemas import ACTION_MODELS
from app.actions.service import ActionService
from app.core.config import Settings
from app.core.exceptions import LLMEmptyResponseError, LLMError
from app.graph.state import AssistantState
from app.llm.base import LLMClient, LLMResponse
from app.prompts import actions as action_prompts
from app.prompts import data as data_prompts
from app.services.answer_verifier import REJECTED, AnswerVerifier
from app.services.data_planner import INVALID, INVALID_ACTION, UNSUPPORTED, DataPlanner
from app.services.query_analyzer import QueryAnalyzer
from app.services.retrieval_service import RetrievalService
from app.services.text_utils import normalize_text
from app.tools.guard import unsupported_number
from app.tools.outcome import OK
from app.tools.service import DataToolService

logger = logging.getLogger("physioplus.graph")

EMPTY_USAGE = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def merge_usage(current: dict | None, response: LLMResponse | None) -> dict:
    usage = dict(current or EMPTY_USAGE)

    if response is not None:
        usage["llm_calls"] += 1
        usage["prompt_tokens"] += response.prompt_tokens
        usage["completion_tokens"] += response.completion_tokens

    return usage


class GraphNodes:
    def __init__(
        self,
        settings: Settings,
        retrieval: RetrievalService,
        analyzer: QueryAnalyzer,
        llm: LLMClient,
        prompts: ModuleType,
        verifier: AnswerVerifier | None = None,
        planner: DataPlanner | None = None,
        data_service: DataToolService | None = None,
        action_service: ActionService | None = None,
    ) -> None:
        self._settings = settings
        self._retrieval = retrieval
        self._analyzer = analyzer
        self._llm = llm
        self._prompts = prompts
        self._verifier = verifier
        self._planner = planner
        self._data_service = data_service
        self._action_service = action_service

    def analyze(self, state: AssistantState) -> dict:
        result = self._analyzer.analyze(state["message"], state.get("history_text", ""))

        return {
            "intent": result.analysis.intent,
            "standalone_question": result.analysis.standalone_question,
            "analysis_fallback": result.analysis.fallback,
            "usage": merge_usage(state.get("usage"), result.response),
        }

    def route_intent(
        self, state: AssistantState
    ) -> Literal[
        "retrieve", "greet", "data_unavailable", "data_needs_auth", "plan_data", "out_of_scope"
    ]:
        intent = state["intent"]

        if intent == "DADOS_OU_ACAO":
            if self._planner is None or self._data_service is None:
                return "data_unavailable"

            return "plan_data" if state.get("has_token") else "data_needs_auth"

        return {
            "DOCUMENTACAO": "retrieve",
            "SAUDACAO": "greet",
        }.get(intent, "out_of_scope")

    def retrieve(self, state: AssistantState) -> dict:
        hits = self._retrieval.search(state["standalone_question"], self._settings.top_k)

        return {
            "hits": hits,
            "max_score": hits[0].score if hits else 0.0,
        }

    def route_evidence(self, state: AssistantState) -> Literal["generate", "abstain"]:
        if self._retrieval.has_evidence(state["hits"]):
            return "generate"

        return "abstain"

    def generate(self, state: AssistantState) -> dict:
        context = self._prompts.format_context(state["hits"])

        messages = self._prompts.build_generation_messages(
            state["message"],
            state["standalone_question"],
            state.get("history_text", ""),
            context,
        )

        response = self._llm.complete(
            messages,
            temperature=0.1,
            max_tokens=self._settings.generation_max_tokens,
        )

        if not response.text:
            raise LLMEmptyResponseError(
                f"O modelo devolveu resposta vazia (finish_reason={response.finish_reason})."
            )

        abstained = response.text.lower().startswith(self._prompts.ABSTAIN_PREFIX)

        return {
            "context": context,
            "answer": response.text,
            "abstained": abstained,
            "path": "documentacao_abstencao_modelo" if abstained else "documentacao_resposta",
            "usage": merge_usage(state.get("usage"), response),
        }

    def route_after_generate(self, state: AssistantState) -> Literal["verify", "done"]:
        if self._verifier is None or state.get("abstained"):
            return "done"

        return "verify"

    def verify(self, state: AssistantState) -> dict:
        result = self._verifier.verify(state["context"], state["answer"])

        return {
            "verification": result.verdict,
            "verification_note": result.note,
            "usage": merge_usage(state.get("usage"), result.response),
        }

    def route_verification(self, state: AssistantState) -> Literal["accept", "reject"]:
        return "reject" if state.get("verification") == REJECTED else "accept"

    def reject(self, state: AssistantState) -> dict:
        return {
            "rejected_answer": state["answer"],
            "answer": self._prompts.ABSTAIN_MESSAGE,
            "abstained": True,
            "path": "verificacao_rejeitada",
        }

    def abstain(self, state: AssistantState) -> dict:
        return {
            "answer": self._prompts.ABSTAIN_MESSAGE,
            "abstained": True,
            "path": "documentacao_sem_evidencia",
        }

    def greet(self, state: AssistantState) -> dict:
        return {
            "answer": self._prompts.GREETING_MESSAGE,
            "abstained": False,
            "path": "saudacao",
        }

    def plan_data(self, state: AssistantState) -> dict:
        result = self._planner.plan(state["message"], state.get("history_text", ""))

        return {
            "plan_tool": result.tool,
            "plan_args": result.arguments,
            "usage": merge_usage(state.get("usage"), result.response),
        }

    def route_plan(
        self, state: AssistantState
    ) -> Literal[
        "execute_tool", "data_unavailable", "data_clarify", "data_clarify_action", "propose_action"
    ]:
        tool = state["plan_tool"]

        if tool == UNSUPPORTED:
            return "data_unavailable"

        if tool == INVALID:
            return "data_clarify"

        if tool == INVALID_ACTION:
            return "data_clarify_action"

        if tool in ACTION_MODELS:
            return "propose_action"

        return "execute_tool"

    def propose_action(self, state: AssistantState, config: RunnableConfig) -> dict:
        if self._action_service is None:
            return {
                "answer": action_prompts.ACTIONS_UNAVAILABLE_MESSAGE,
                "abstained": False,
                "path": "acao_indisponivel",
            }

        token = ((config or {}).get("configurable") or {}).get("access_token") or ""
        outcome = self._action_service.propose(state["plan_tool"], state["plan_args"], token)

        return {
            "answer": outcome.text,
            "abstained": False,
            "path": f"acao_{outcome.status}",
            "proposal": outcome.proposal,
        }

    def data_clarify_action(self, state: AssistantState) -> dict:
        return {
            "answer": action_prompts.ACTION_CLARIFY_MESSAGE,
            "abstained": False,
            "path": "acao_esclarecimento",
        }

    def execute_tool(self, state: AssistantState, config: RunnableConfig) -> dict:
        token = ((config or {}).get("configurable") or {}).get("access_token") or ""
        outcome = self._data_service.run(state["plan_tool"], state["plan_args"], token)

        return {
            "tool_status": outcome.status,
            "tool_data": outcome.data,
            "tool_text": outcome.text,
        }

    def route_tool(self, state: AssistantState) -> Literal["compose_data", "data_message"]:
        return "compose_data" if state["tool_status"] == OK else "data_message"

    def compose_data(self, state: AssistantState) -> dict:
        data = state["tool_data"]
        fallback = state["tool_text"]
        usage = state.get("usage")

        if state.get("plan_tool") == "get_financial_summary":
            question = normalize_text(state["message"])
            groups = ("pendentes",) if any(word in question for word in ("pendente", "em aberto", "devendo")) else (
                ("pagas",) if any(word in question for word in ("recebi", "recebido", "pagou")) else ("pendentes", "pagas")
            )
            lines = [fallback, "Período pela data da sessão; a API não informa a data de recebimento."]
            for group in groups:
                for item in data[group]:
                    lines.append(f"- {item['paciente'] or 'Paciente não informado'}: {item['data']}, {item['inicio']}, {item['valor']} ({'pendente' if group == 'pendentes' else 'pago'}).")
                if data[f"{group}_omitidas"]:
                    lines.append(f"Mais {data[f'{group}_omitidas']} sessões {group} no PDF completo.")
            return {"answer": "\n".join(lines), "abstained": False, "path": "dados_resposta", "numeric_guard": "deterministico"}

        messages = data_prompts.build_compose_messages(
            state["message"], state.get("history_text", ""), data
        )

        try:
            response = self._llm.complete(
                messages,
                temperature=0.1,
                max_tokens=self._settings.generation_max_tokens,
            )
        except LLMError:
            return {
                "answer": fallback,
                "abstained": False,
                "path": "dados_resposta",
                "numeric_guard": "llm_indisponivel",
            }

        usage = merge_usage(usage, response)
        allowed = json.dumps(data, ensure_ascii=False) + " " + state["message"]
        offending = unsupported_number(response.text, allowed) if response.text else "vazio"

        if not response.text or offending:
            logger.warning("Guarda numérica acionada, usando o resumo determinístico")
            return {
                "answer": fallback,
                "abstained": False,
                "path": "dados_resposta",
                "numeric_guard": "resumo_deterministico",
                "usage": usage,
            }

        return {
            "answer": response.text,
            "abstained": False,
            "path": "dados_resposta",
            "numeric_guard": "aprovada",
            "usage": usage,
        }

    def data_message(self, state: AssistantState) -> dict:
        return {
            "answer": state["tool_text"],
            "abstained": False,
            "path": f"dados_{state['tool_status']}",
        }

    def data_clarify(self, state: AssistantState) -> dict:
        return {
            "answer": data_prompts.CLARIFY_MESSAGE,
            "abstained": False,
            "path": "dados_esclarecimento",
        }

    def data_needs_auth(self, state: AssistantState) -> dict:
        return {
            "answer": data_prompts.AUTH_REQUIRED_MESSAGE,
            "abstained": False,
            "path": "dados_sem_autenticacao",
        }

    def data_unavailable(self, state: AssistantState) -> dict:
        return {
            "answer": data_prompts.UNSUPPORTED_MESSAGE if self._planner is not None else self._prompts.DATA_UNAVAILABLE_MESSAGE,
            "abstained": False,
            "path": "dados_ou_acao",
        }

    def out_of_scope(self, state: AssistantState) -> dict:
        return {
            "answer": self._prompts.OUT_OF_SCOPE_MESSAGE,
            "abstained": False,
            "path": "fora_escopo",
        }
