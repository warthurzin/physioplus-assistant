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

    for active in (True, False):
        matches = api.list_patients(token, name, active)

        if matches:
            break

    if not matches:
        return Lookup(NONE)

    target = normalize_text(name)
    exact = [item for item in matches if normalize_text(str(item.get("full_name", ""))) == target]
    chosen = exact if len(exact) == 1 else matches

    if len(chosen) > 1:
        return Lookup(AMBIGUOUS, None, [str(item.get("full_name")) for item in chosen[:MAX_NAMES]])

    return Lookup(FOUND, chosen[0])