from dataclasses import dataclass, field

OK = "ok"
NOT_FOUND = "not_found"
AMBIGUOUS = "ambiguous"
AUTH = "auth"
VALIDATION = "validation"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ToolOutcome:
    tool: str
    status: str
    data: dict = field(default_factory=dict)
    text: str = ""