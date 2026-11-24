from dataclasses import dataclass, field

from app.integrations.physio_api import PhysioApiClient
from app.services.text_utils import normalize_text

FOUND = "found"
NONE = "none"
AMBIGUOUS = "ambiguous"
MAX_NAMES = 5


@dataclass(frozen=True)
class Lookup:
    kind: str
    patient: dict | None = None
    names: list[str] = field(default_factory=list)


def find_patient(api: PhysioApiClient, token: str, name: str) -> Lookup:
    matches: list[dict] = []
    target = normalize_text(name)

    for active in (True, False):
        for item in api.list_patients(token, name, active):
            candidate = normalize_text(str(item.get("full_name", "")))
            if target and target in candidate and not any(row.get("id") == item.get("id") for row in matches):
                matches.append(item)

    if not matches:
        return Lookup(NONE)

    exact = [item for item in matches if normalize_text(str(item.get("full_name", ""))) == target]
    chosen = exact if len(exact) == 1 else matches

    if len(chosen) > 1:
        return Lookup(AMBIGUOUS, None, [str(item.get("full_name")) for item in chosen[:MAX_NAMES]])

    return Lookup(FOUND, chosen[0])
