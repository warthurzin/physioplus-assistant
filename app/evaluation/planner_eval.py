import re
from dataclasses import dataclass, field
from datetime import datetime

from app.services.data_planner import DataPlanner
from app.services.text_utils import normalize_text

NAME_KEYS = {"query", "patient_name", "full_name"}
DIGIT_KEYS = {"cpf", "phone"}


def resolve_expected(value, now: datetime, field_name: str):
    if isinstance(value, str) and value.startswith("thisyear:"):
        return f"{now.year}-{value.split(':', 1)[1]}"

    if value == "current":
        return now.month if field_name == "month" else now.year

    if value == "previous":
        previous_month = now.month - 1 or 12
        previous_year = now.year - 1 if now.month == 1 else now.year
        return previous_month if field_name == "month" else previous_year

    return value


def only_digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def compare(key: str, expected, got, now: datetime, problems: list[str]) -> None:
    if isinstance(expected, dict):
        nested = got if isinstance(got, dict) else {}

        for inner_key, inner_value in expected.items():
            compare(inner_key, inner_value, nested.get(inner_key), now, problems)

        return

    expected = resolve_expected(expected, now, key)

    if key in DIGIT_KEYS:
        if only_digits(expected) not in only_digits(got):
            problems.append(f"{key}: esperado conter {expected!r}, obtido {got!r}")
    elif key in NAME_KEYS:
        if normalize_text(str(expected)) not in normalize_text(str(got or "")):
            problems.append(f"{key}: esperado conter {expected!r}, obtido {got!r}")
    elif got != expected:
        problems.append(f"{key}: esperado {expected!r}, obtido {got!r}")


@dataclass
class PlannerCaseResult:
    id: str
    message: str
    passed: bool
    expected_tool: str
    got_tool: str
    got_args: dict
    problems: list[str] = field(default_factory=list)


def evaluate_planner_case(case: dict, planner: DataPlanner, now: datetime) -> PlannerCaseResult:
    from app.services.chat_service import format_history

    result = planner.plan(case["message"], format_history(case.get("history", []), 3))
    accepted = case.get("expected_tool_any") or [case["expected_tool"]]
    problems = []

    if result.tool not in accepted:
        problems.append(f"ferramenta: esperado {accepted}, obtido {result.tool}")

    if result.tool == case["expected_tool"]:
        for key, raw in case.get("expected_args", {}).items():
            compare(key, raw, result.arguments.get(key), now, problems)

    return PlannerCaseResult(
        id=case["id"],
        message=case["message"],
        passed=not problems,
        expected_tool=case["expected_tool"],
        got_tool=result.tool,
        got_args=result.arguments,
        problems=problems,
    )