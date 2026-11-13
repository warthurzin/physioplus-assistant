from app.integrations.physio_api import PhysioApiClient
from app.tools.patient_lookup import AMBIGUOUS as LOOKUP_AMBIGUOUS
from app.tools.patient_lookup import NONE, find_patient
from app.tools.formatting import date_br, money, payment_label, time_hm
from app.tools.outcome import AMBIGUOUS, NOT_FOUND, OK, ToolOutcome


def search_patients(
    api: PhysioApiClient,
    token: str,
    query: str | None,
    active: bool,
    max_items: int,
) -> ToolOutcome:
    patients = api.list_patients(token, query, active)
    shown = patients[:max_items]
    situation = "ativos" if active else "inativos"

    data = {
        "situacao": situation,
        "busca": query,
        "total": len(patients),
        "exibidos": len(shown),
        "pacientes": [
            {
                "nome": item.get("full_name"),
                "valor_sessao": money(item.get("session_value")),
            }
            for item in shown
        ],
    }

    if not patients:
        text = f"Não encontrei pacientes {situation}" + (f" com a busca \"{query}\"." if query else ".")
    else:
        names = ", ".join(str(item.get("full_name")) for item in shown)
        extra = f" e mais {len(patients) - len(shown)}" if len(patients) > len(shown) else ""
        text = f"Pacientes {situation} encontrados ({len(patients)}): {names}{extra}."

    return ToolOutcome("search_patients", OK, data, text)


def get_patient_profile(
    api: PhysioApiClient,
    token: str,
    patient_name: str,
    max_items: int,
) -> ToolOutcome:
    lookup = find_patient(api, token, patient_name)

    if lookup.kind == NONE:
        return ToolOutcome("get_patient_profile", NOT_FOUND, {}, "")

    if lookup.kind == LOOKUP_AMBIGUOUS:
        return ToolOutcome(
            "get_patient_profile",
            AMBIGUOUS,
            {},
            f"Encontrei mais de um paciente com esse nome: {', '.join(lookup.names)}. Qual deles você quer consultar?",
        )

    profile = api.get_patient(token, str(lookup.patient.get("id")))
    patient = profile.get("patient") or lookup.patient
    financial = profile.get("financial") or {}
    sessions = (profile.get("recentSessions") or [])[:max_items]

    data = {
        "paciente": {
            "nome": patient.get("full_name"),
            "situacao": "ativo" if patient.get("is_active", True) else "inativo",
            "telefone": patient.get("phone"),
            "email": patient.get("email"),
            "data_nascimento": date_br(patient.get("birth_date")) if patient.get("birth_date") else None,
            "valor_sessao": money(patient.get("session_value")),
        },
        "financeiro": {
            "recebido": money(financial.get("total_received")),
            "pendente": money(financial.get("total_pending")),
            "total_sessoes": financial.get("total_sessions", 0),
        },
        "sessoes_recentes": [
            {
                "data": date_br(item.get("date")),
                "inicio": time_hm(item.get("start_time")),
                "fim": time_hm(item.get("end_time")),
                "pagamento": payment_label(item.get("payment_status")),
                "valor": money(item.get("session_value")),
            }
            for item in sessions
        ],
    }

    text = (
        f"{data['paciente']['nome']} ({data['paciente']['situacao']}), valor da sessão "
        f"{data['paciente']['valor_sessao']}. Recebido: {data['financeiro']['recebido']}. "
        f"Pendente: {data['financeiro']['pendente']}. "
        f"Total de sessões: {data['financeiro']['total_sessoes']}."
    )

    return ToolOutcome("get_patient_profile", OK, data, text)