import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.actions.schemas import ACTION_MODELS, AppointmentDraft
from app.core.exceptions import LLMError
from app.llm.base import LLMClient, LLMResponse, extract_json
from app.prompts.data import build_planner_messages
from app.services.operational_intent import scheduling_request
from app.services.text_utils import normalize_text
from app.tools.schemas import ARGUMENT_MODELS

logger = logging.getLogger("physioplus.planner")

UNSUPPORTED = "unsupported"
INVALID = "invalid"
INVALID_ACTION = "invalid_action"
ALL_MODELS = {**ARGUMENT_MODELS, **ACTION_MODELS}
WEEKDAYS = [
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
]


@dataclass(frozen=True)
class PlanResult:
    tool: str
    arguments: dict = field(default_factory=dict)
    response: LLMResponse | None = None


class DataPlanner:
    def __init__(self, llm: LLMClient, timezone: str) -> None:
        self._llm = llm
        self._timezone = ZoneInfo(timezone)

    def _now(self) -> datetime:
        return datetime.now(self._timezone)

    def today_text(self) -> str:
        now = self._now()
        return f"{now.strftime('%d/%m/%Y')} ({WEEKDAYS[now.weekday()]})"

    def plan(self, message: str, history_text: str = "") -> PlanResult:
        if normalize_text(message).strip(".! ") in {"sim", "confirmo", "pode fazer", "pode confirmar", "confirmar", "ok"}:
            return PlanResult(INVALID)
        messages = build_planner_messages(message, history_text, self.today_text(), self._now().year)
        response = None

        try:
            response = self._llm.complete(
                messages,
                temperature=0.0,
                max_tokens=300,
                json_mode=True,
            )
            data = extract_json(response.text)
            tool = str(data.get("tool", "")).strip()

            if tool == UNSUPPORTED:
                return PlanResult(UNSUPPORTED, {}, response)

            if tool == "clarify":
                if scheduling_request(message):
                    return PlanResult("create_appointment", AppointmentDraft().model_dump(), response)
                return PlanResult(INVALID, {}, response)

            model = AppointmentDraft if tool == "create_appointment" else ALL_MODELS.get(tool)

            if model is None:
                raise ValueError(f"ferramenta desconhecida: {tool!r}")

            try:
                arguments = model.model_validate(data.get("arguments") or {}).model_dump()
            except ValueError:
                if tool in ACTION_MODELS:
                    return PlanResult(INVALID_ACTION, {}, response)

                raise
        except (LLMError, ValueError) as error:
            logger.warning("Planejamento falhou (%s)", type(error).__name__)
            return PlanResult(INVALID, {}, response)

        return PlanResult(tool, arguments, response)
