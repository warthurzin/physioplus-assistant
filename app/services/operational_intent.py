import re

from app.services.text_utils import normalize_text


def scheduling_request(message: str) -> bool:
    text = normalize_text(message)
    return bool(re.search(r"\b(agendar|agende|marcar|marque|marcamos|reservar|reserve|encaixar|encaixe)\b", text)) and not bool(
        re.search(r"\b(como|onde|nao|desisti|cancelar)\b", text)
    )


def operational_intent(message: str, history_text: str = "") -> bool:
    text = normalize_text(message)
    if re.search(r"\b(como|onde)\b.*\b(agendar|marcar|cadastrar)\b", text):
        return False
    if re.search(r"\b(agend\w*|marc\w*|reserv\w*|encaix\w*)\b", text) and (
        re.search(
            r"\b(sessao|consulta|atendimento|horario|para|paciente|agenda)\b", text
        )
        or re.search(r"\b(quero|vamos|pode|preciso)\b", text)
    ):
        return True
    if re.search(
        r"\b(financeir\w*|pagamentos?|recebi|recebido|pendentes?|pdf)\b", text
    ):
        return True
    last = (
        history_text.rsplit("Assistente:", 1)[-1]
        if "Assistente:" in history_text
        else ""
    )
    return bool(
        re.search(
            r"nome cadastrado|qual dia|qual hor.rio|dia e hor.rio|para agendar|correspond.ncia",
            last,
            re.IGNORECASE,
        )
    )
