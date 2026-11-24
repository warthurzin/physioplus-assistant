from datetime import date, timedelta

WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
WEEKDAY_PT = [
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
]
RELATIVE_OFFSETS = {
    "today": 0,
    "tomorrow": 1,
    "yesterday": -1,
    "this_week": 0,
    "next_week": 7,
    "previous_week": -7,
}


def weekday_pt(value: date) -> str:
    return WEEKDAY_PT[value.weekday()]


def resolve_date(
    date_text: str | None,
    relative: str | None,
    weekday: str | None,
    direction: str,
    today: date,
) -> date:
    if date_text:
        return date.fromisoformat(date_text)

    if relative:
        return today + timedelta(days=RELATIVE_OFFSETS[relative])

    if weekday:
        target = WEEKDAY_INDEX[weekday]

        if direction == "previous":
            delta = (today.weekday() - target) % 7 or 7
            return today - timedelta(days=delta)

        return today + timedelta(days=(target - today.weekday()) % 7)

    raise ValueError("nenhuma referência de data informada")