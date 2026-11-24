import re
from datetime import date

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LENGTHS = {"rg": 20, "zip_code": 9, "number": 20, "neighborhood": 100, "street": 255}
LABELS = {
    "full_name": "nome",
    "cpf": "CPF",
    "phone": "telefone",
    "session_value": "valor da sessão",
    "email": "e-mail",
    "birth_date": "data de nascimento",
    "rg": "RG",
    "zip_code": "CEP",
    "street": "rua",
    "number": "número",
    "neighborhood": "bairro",
}
REQUIRED = ["full_name", "cpf", "phone", "session_value"]


def digits(text) -> str:
    return re.sub(r"\D", "", str(text or ""))


def is_valid_cpf(value: str) -> bool:
    cpf = digits(value)

    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    for position in (9, 10):
        total = sum(int(cpf[index]) * (position + 1 - index) for index in range(position))

        if (total * 10 % 11) % 10 != int(cpf[position]):
            return False

    return True


def format_cpf(value: str) -> str:
    cpf = digits(value)

    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else str(value)


def validate_fields(fields: dict, today: date) -> tuple[dict, list[str]]:
    clean: dict = {}
    errors: list[str] = []

    for key, value in fields.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue

        if key == "session_value":
            if float(value) <= 0:
                errors.append("o valor da sessão deve ser maior que zero")
            else:
                clean[key] = float(value)

            continue

        text = str(value).strip()

        if key == "full_name":
            if len(text) < 3:
                errors.append("o nome deve ter pelo menos 3 caracteres")
            else:
                clean[key] = text
        elif key == "cpf":
            if not is_valid_cpf(text):
                errors.append("o CPF informado não é válido")
            else:
                clean[key] = digits(text)
        elif key == "phone":
            if not 8 <= len(text) <= 20:
                errors.append("o telefone deve ter entre 8 e 20 caracteres")
            else:
                clean[key] = text
        elif key == "email":
            if not EMAIL_PATTERN.match(text):
                errors.append("o e-mail informado não é válido")
            else:
                clean[key] = text.lower()
        elif key == "birth_date":
            try:
                parsed = date.fromisoformat(text)
            except ValueError:
                errors.append("a data de nascimento deve ser uma data válida")
                continue

            if parsed > today:
                errors.append("a data de nascimento não pode estar no futuro")
            else:
                clean[key] = text
        elif key in MAX_LENGTHS:
            if len(text) > MAX_LENGTHS[key]:
                errors.append(f"{LABELS[key]} deve ter no máximo {MAX_LENGTHS[key]} caracteres")
            else:
                clean[key] = text
        else:
            clean[key] = text

    return clean, errors


def same_value(key: str, current, new) -> bool:
    if key == "cpf":
        return digits(current) == digits(new)

    if key == "session_value":
        try:
            return float(current) == float(new)
        except (TypeError, ValueError):
            return False

    return str(current or "").strip() == str(new or "").strip()