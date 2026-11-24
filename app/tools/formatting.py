import re

MONTHS = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
PAYMENT_LABELS = {"paid": "pago", "pending": "pendente"}
ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def money(value) -> str:
    text = f"{to_float(value):,.2f}"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")


def date_br(value) -> str:
    match = ISO_DATE.match(str(value or ""))

    if not match:
        return str(value or "")

    year, month, day = match.groups()

    return f"{day}/{month}/{year}"


def time_hm(value) -> str:
    return str(value or "")[:5]


def appointment_status_label(value) -> str:
    text = str(value or "").lower()

    if text == "scheduled":
        return "agendado"

    if "complet" in text:
        return "concluído"

    if "cancel" in text:
        return "cancelado"

    return text


def payment_label(value) -> str:
    return PAYMENT_LABELS.get(str(value), str(value or ""))