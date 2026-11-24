from app.integrations.physio_api import PhysioApiClient
from app.services.report_metadata import financial_report_metadata
from app.tools.formatting import MONTHS, date_br, money, time_hm
from app.tools.outcome import OK, ToolOutcome


def _sessions(items: list, limit: int) -> list[dict]:
    return [
        {
            "paciente": (item.get("patient") or {}).get("full_name"),
            "data": date_br(item.get("date")),
            "inicio": time_hm(item.get("start_time")),
            "valor": money(item.get("session_value")),
        }
        for item in items[:limit]
    ]


def get_financial_summary(
    api: PhysioApiClient,
    token: str,
    month: int,
    year: int,
    max_items: int,
) -> ToolOutcome:
    summary = api.financial_summary(token, month, year)

    pending = summary.get("pending_sessions") or []
    paid = summary.get("paid_sessions") or []

    data = {
        "report": financial_report_metadata(summary, month, year),
        "mes": MONTHS[month - 1],
        "ano": year,
        "recebido": money(summary.get("total_received")),
        "pendente": money(summary.get("total_pending")),
        "acumulado_recebido": money(summary.get("total_accumulated")),
        "total_sessoes": summary.get("total_sessions", 0),
        "sessoes_pagas": summary.get("paid_sessions_count", len(paid)),
        "sessoes_pendentes": summary.get("pending_sessions_count", len(pending)),
        "pendentes": _sessions(pending, max_items),
        "pendentes_omitidas": max(len(pending) - max_items, 0),
        "pagas": _sessions(paid, max_items),
        "pagas_omitidas": max(len(paid) - max_items, 0),
    }

    text = (
        f"Em {data['mes']} de {year}: recebido {data['recebido']}, pendente {data['pendente']}, "
        f"acumulado recebido {data['acumulado_recebido']}. "
        f"Total de sessões: {data['total_sessoes']} "
        f"({data['sessoes_pagas']} pagas e {data['sessoes_pendentes']} pendentes)."
    )

    return ToolOutcome("get_financial_summary", OK, data, text)
