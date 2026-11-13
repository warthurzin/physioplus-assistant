from datetime import date

from app.integrations.physio_api import PhysioApiClient
from app.tools.dates import weekday_pt
from app.tools.formatting import appointment_status_label, date_br, time_hm
from app.tools.outcome import OK, ToolOutcome

WEEKEND_NOTE = "A Agenda do PhysioPlus cobre apenas de segunda a sexta."


def _appointment(item: dict) -> dict:
    appointment = item.get("appointment") or {}
    patient = appointment.get("patient") or {}

    return {
        "inicio": time_hm(appointment.get("start_time")),
        "fim": time_hm(appointment.get("end_time")),
        "paciente": patient.get("full_name"),
        "domiciliar": bool(appointment.get("is_home_visit")),
        "situacao": appointment_status_label(appointment.get("status")),
    }


def _day_payload(target: date, schedule: list, max_items: int) -> dict:
    occupied = [item for item in schedule if item.get("status") == "occupied" and item.get("appointment")]
    free = [item for item in schedule if item.get("status") == "free"]

    return {
        "data": date_br(target.isoformat()),
        "dia_semana": weekday_pt(target),
        "total_atendimentos": len(occupied),
        "atendimentos": [_appointment(item) for item in occupied[:max_items]],
        "atendimentos_omitidos": max(len(occupied) - max_items, 0),
        "total_horarios_livres": len(free),
        "horarios_livres": [
            f"{time_hm((item.get('slot') or {}).get('start_time'))}-{time_hm((item.get('slot') or {}).get('end_time'))}"
            for item in free[:max_items]
        ],
    }


def _day_text(payload: dict) -> str:
    header = f"{payload['dia_semana'].capitalize()}, {payload['data']}"

    if not payload["total_atendimentos"]:
        return f"{header}: nenhum atendimento marcado."

    lines = "; ".join(
        f"{item['inicio']} {item['paciente']}{' (domiciliar)' if item['domiciliar'] else ''}"
        for item in payload["atendimentos"]
    )

    return f"{header}: {payload['total_atendimentos']} atendimento(s): {lines}."


def get_schedule_day(api: PhysioApiClient, token: str, target: date, max_items: int) -> ToolOutcome:
    if target.weekday() >= 5:
        payload = {
            "data": date_br(target.isoformat()),
            "dia_semana": weekday_pt(target),
            "total_atendimentos": 0,
            "atendimentos": [],
            "observacao": WEEKEND_NOTE,
        }
        text = f"{payload['dia_semana'].capitalize()}, {payload['data']}. {WEEKEND_NOTE}"

        return ToolOutcome("get_schedule_day", OK, payload, text)

    payload = _day_payload(target, api.schedule_day(token, target.isoformat()), max_items)

    return ToolOutcome("get_schedule_day", OK, payload, _day_text(payload))


def get_schedule_week(api: PhysioApiClient, token: str, target: date, max_items: int) -> ToolOutcome:
    days = api.schedule_week(token, target.isoformat())
    parsed = []

    for entry in days:
        day = date.fromisoformat(str(entry.get("date")))
        parsed.append(_day_payload(day, entry.get("schedule") or [], max_items))

    total = sum(item["total_atendimentos"] for item in parsed)

    payload = {
        "periodo": (
            f"{parsed[0]['data']} a {parsed[-1]['data']}" if parsed else date_br(target.isoformat())
        ),
        "total_atendimentos": total,
        "dias": [
            {
                "data": item["data"],
                "dia_semana": item["dia_semana"],
                "total_atendimentos": item["total_atendimentos"],
                "atendimentos": item["atendimentos"],
                "atendimentos_omitidos": item["atendimentos_omitidos"],
                "total_horarios_livres": item["total_horarios_livres"],
            }
            for item in parsed
        ],
    }

    lines = " ".join(_day_text(item) for item in parsed) if parsed else "Nenhum dado de agenda para a semana."
    text = f"Semana de {payload['periodo']}: {total} atendimento(s). {lines}"

    return ToolOutcome("get_schedule_week", OK, payload, text)