import logging
from datetime import date
from typing import Callable

from app.core.exceptions import (
    UpstreamAuthError,
    UpstreamNotFoundError,
    UpstreamUnavailableError,
    UpstreamValidationError,
)
from app.integrations.physio_api import PhysioApiClient
from app.prompts import data as messages
from app.tools import financial, patients, schedule
from app.tools.dates import resolve_date
from app.tools.outcome import AUTH, NOT_FOUND, UNAVAILABLE, VALIDATION, ToolOutcome

logger = logging.getLogger("physioplus.tools")


class DataToolService:
    def __init__(
        self,
        api: PhysioApiClient,
        max_items: int,
        today_fn: Callable[[], date] = date.today,
    ) -> None:
        self._api = api
        self._max_items = max_items
        self._today = today_fn

    def run(self, tool: str, arguments: dict, token: str) -> ToolOutcome:
        try:
            if tool == "search_patients":
                outcome = patients.search_patients(
                    self._api, token, arguments.get("query"), arguments.get("active", True), self._max_items
                )
            elif tool == "get_patient_profile":
                outcome = patients.get_patient_profile(
                    self._api, token, arguments["patient_name"], self._max_items
                )
            elif tool == "get_financial_summary":
                outcome = financial.get_financial_summary(
                    self._api, token, arguments["month"], arguments["year"], self._max_items
                )
            elif tool in ("get_schedule_day", "get_schedule_week"):
                target = resolve_date(
                    arguments.get("date"),
                    arguments.get("relative"),
                    arguments.get("weekday"),
                    arguments.get("direction", "next"),
                    self._today(),
                )
                runner = schedule.get_schedule_day if tool == "get_schedule_day" else schedule.get_schedule_week
                outcome = runner(self._api, token, target, self._max_items)
            else:
                return ToolOutcome(tool, VALIDATION, {}, messages.CLARIFY_MESSAGE)
        except UpstreamAuthError:
            outcome = ToolOutcome(tool, AUTH, {}, messages.AUTH_EXPIRED_MESSAGE)
        except UpstreamNotFoundError:
            outcome = ToolOutcome(tool, NOT_FOUND, {}, messages.PATIENT_NOT_FOUND_MESSAGE)
        except UpstreamValidationError:
            outcome = ToolOutcome(tool, VALIDATION, {}, messages.VALIDATION_MESSAGE)
        except UpstreamUnavailableError:
            outcome = ToolOutcome(tool, UNAVAILABLE, {}, messages.UNAVAILABLE_MESSAGE)

        if outcome.status == NOT_FOUND and not outcome.text:
            outcome = ToolOutcome(tool, NOT_FOUND, {}, messages.PATIENT_NOT_FOUND_MESSAGE)

        logger.info("Consulta: tool=%s status=%s", tool, outcome.status)

        return outcome