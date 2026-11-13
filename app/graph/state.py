from typing_extensions import TypedDict


class AssistantState(TypedDict, total=False):
    message: str
    history_text: str
    intent: str
    standalone_question: str
    analysis_fallback: bool
    hits: list
    max_score: float
    context: str
    answer: str
    abstained: bool
    path: str
    usage: dict
    has_token: bool
    plan_tool: str
    plan_args: dict
    tool_status: str
    tool_data: dict
    tool_text: str
    numeric_guard: str
    proposal: dict
    verification: str
    verification_note: str
    rejected_answer: str