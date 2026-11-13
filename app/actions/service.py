import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable

from app.actions import patient_rules
from app.actions.identity import user_id_from_token
from app.actions.schemas import PATIENT_ACTIONS
from app.actions.signer import ProposalError, ProposalSigner
from app.core.exceptions import (
    UpstreamAuthError,
    UpstreamConflictError,
    UpstreamNotFoundError,
    UpstreamUnavailableError,
    UpstreamValidationError,
)
from app.integrations.physio_api import PhysioApiClient
from app.prompts import actions as msg
from app.tools.dates import resolve_date, weekday_pt
from app.tools.formatting import date_br, money, time_hm
from app.tools.patient_lookup import AMBIGUOUS, FOUND, find_patient

logger = logging.getLogger("physioplus.actions")

MAX_LISTED = 5
PAYMENT_LABELS = {"paid": "paga", "pending": "pendente"}


@dataclass(frozen=True)
class ProposalOutcome:
    status: str
    text: str
    proposal: dict | None = None


@dataclass(frozen=True)
class ActionResult:
    status: str
    message: str
    action: str | None = None


def add_minutes(start: str, minutes: int) -> str | None:
    hours, mins = start.split(":")
    total = int(hours) * 60 + int(mins) + minutes

    if total >= 24 * 60:
        return None

    return f"{total // 60:02d}:{total % 60:02d}"


class ActionService:
    def __init__(
        self,
        api: PhysioApiClient,
        signer: ProposalSigner,
        today_fn: Callable[[], date] = date.today,
        default_minutes: int = 60,
        patient_actions_enabled: bool = True,
    ) -> None:
        self._api = api
        self._signer = signer
        self._today = today_fn
        self._default_minutes = default_minutes
        self._patient_actions = patient_actions_enabled

    def _day(self, arguments: dict) -> date:
        return resolve_date(
            arguments.get("date"),
            arguments.get("relative"),
            arguments.get("weekday"),
            arguments.get("direction", "next"),
            self._today(),
        )

    def _patient(self, arguments: dict, token: str):
        lookup = find_patient(self._api, token, arguments["patient_name"])

        if lookup.kind == FOUND:
            return lookup.patient, None

        if lookup.kind == AMBIGUOUS:
            return None, ProposalOutcome("ambiguous", msg.PATIENT_AMBIGUOUS.format(names=", ".join(lookup.names)))

        return None, ProposalOutcome("not_found", msg.PATIENT_NOT_FOUND)

    def _proposal(self, action: str, user_id: str, params: dict, summary: str) -> ProposalOutcome:
        token = self._signer.sign({"v": 1, "act": action, "uid": user_id, "p": params})
        text = f"{summary}\n{msg.CONFIRM_SUFFIX.format(minutes=self._signer.ttl // 60)}"

        return ProposalOutcome(
            "proposed",
            text,
            {
                "token": token,
                "action": action,
                "summary": summary,
                "expires_in_seconds": self._signer.ttl,
            },
        )

    def propose(self, action: str, arguments: dict, token: str) -> ProposalOutcome:
        user_id = user_id_from_token(token)

        if not user_id:
            return ProposalOutcome("auth", msg.AUTH_EXPIRED)

        handlers = {
            "create_appointment": self._propose_create,
            "cancel_appointment": self._propose_cancel,
            "confirm_appointment": self._propose_confirm,
            "set_session_payment": self._propose_payment,
            "create_patient": self._propose_create_patient,
            "update_patient": self._propose_update_patient,
            "deactivate_patient": self._propose_deactivate_patient,
            "reactivate_patient": self._propose_reactivate_patient,
        }

        if action in PATIENT_ACTIONS and not self._patient_actions:
            return ProposalOutcome("unsupported", msg.ACTIONS_UNAVAILABLE_MESSAGE)

        try:
            outcome = handlers[action](arguments, token, user_id)
        except UpstreamAuthError:
            outcome = ProposalOutcome("auth", msg.AUTH_EXPIRED)
        except UpstreamNotFoundError:
            outcome = ProposalOutcome("not_found", msg.PATIENT_NOT_FOUND)
        except (UpstreamValidationError, UpstreamConflictError):
            outcome = ProposalOutcome("rejected", msg.REJECTED_GENERIC)
        except UpstreamUnavailableError:
            outcome = ProposalOutcome("unavailable", msg.WRITE_UNCERTAIN)

        logger.info("Proposta: action=%s status=%s", action, outcome.status)

        return outcome

    def _propose_create(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")

        if not patient.get("is_active", True):
            return ProposalOutcome("invalid_state", msg.PATIENT_INACTIVE.format(name=name, verb="agendar"))

        day = self._day(arguments)
        start = arguments["start_time"]
        end = arguments.get("end_time") or add_minutes(
            start, arguments.get("duration_minutes") or self._default_minutes
        )

        if end is None:
            return ProposalOutcome("invalid", msg.END_OVERFLOW)

        for item in self._api.list_appointments(token, day.isoformat()):
            if item.get("status") == "cancelled":
                continue

            if time_hm(item.get("start_time")) < end and time_hm(item.get("end_time")) > start:
                other = (item.get("Patient") or item.get("patient") or {}).get("full_name") or "outro paciente"

                return ProposalOutcome(
                    "conflict",
                    msg.SLOT_TAKEN.format(name=other, start=time_hm(item.get("start_time")), end=time_hm(item.get("end_time"))),
                )

        home = arguments.get("is_home_visit", False)
        summary = (
            f"Criar agendamento: {name}, {weekday_pt(day)} {date_br(day.isoformat())}, "
            f"das {start} às {end}{', atendimento domiciliar' if home else ''}."
        )

        if day.weekday() >= 5:
            summary += msg.WEEKEND_WARNING

        if day < self._today():
            summary += msg.PAST_WARNING

        params = {
            "patient_id": str(patient.get("id")),
            "patient_name": name,
            "date": day.isoformat(),
            "start_time": start,
            "end_time": end,
            "is_home_visit": bool(home),
        }

        return self._proposal("create_appointment", user_id, params, summary)

    def _pick_appointment(self, arguments: dict, token: str, patient: dict, day: date):
        items = [
            item
            for item in self._api.list_appointments(token, day.isoformat(), str(patient.get("id")))
            if item.get("status") == "scheduled"
        ]
        wanted = arguments.get("start_time")

        if wanted:
            items = [item for item in items if time_hm(item.get("start_time")) == wanted]

        name = patient.get("full_name")
        label = date_br(day.isoformat())

        if not items:
            return None, ProposalOutcome("not_found", msg.NO_APPOINTMENT.format(name=name, date=label))

        if len(items) > 1:
            times = ", ".join(time_hm(item.get("start_time")) for item in items[:MAX_LISTED])
            return None, ProposalOutcome("ambiguous", msg.MANY_APPOINTMENTS.format(name=name, date=label, times=times))

        return items[0], None

    def _propose_cancel(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        day = self._day(arguments)
        appointment, error = self._pick_appointment(arguments, token, patient, day)

        if error:
            return error

        name = patient.get("full_name")
        start, end = time_hm(appointment.get("start_time")), time_hm(appointment.get("end_time"))
        summary = f"Cancelar o agendamento de {name} em {date_br(day.isoformat())}, das {start} às {end}."
        params = {
            "patient_id": str(patient.get("id")),
            "appointment_id": str(appointment.get("id")),
            "patient_name": name,
            "date": day.isoformat(),
        }

        return self._proposal("cancel_appointment", user_id, params, summary)

    def _propose_confirm(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")

        if not patient.get("is_active", True):
            return ProposalOutcome("invalid_state", msg.PATIENT_INACTIVE.format(name=name, verb="confirmar o atendimento"))

        day = self._day(arguments)
        appointment, error = self._pick_appointment(arguments, token, patient, day)

        if error:
            return error

        start, end = time_hm(appointment.get("start_time")), time_hm(appointment.get("end_time"))
        summary = (
            f"Confirmar o atendimento de {name} em {date_br(day.isoformat())}, das {start} às {end}. "
            "Isso cria a sessão com pagamento pendente."
        )
        params = {
            "patient_id": str(patient.get("id")),
            "appointment_id": str(appointment.get("id")),
            "patient_name": name,
            "date": day.isoformat(),
        }

        return self._proposal("confirm_appointment", user_id, params, summary)

    def _propose_payment(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")
        sessions = self._api.list_sessions(token, str(patient.get("id")))
        target = "paid" if arguments["paid"] else "pending"
        label = PAYMENT_LABELS[target]
        opposite = PAYMENT_LABELS["pending" if target == "paid" else "paid"]

        if not sessions:
            return ProposalOutcome("not_found", msg.NO_SESSIONS.format(name=name))

        has_day = any(arguments.get(key) for key in ("date", "relative", "weekday"))

        if has_day:
            day = self._day(arguments)
            sessions = [item for item in sessions if str(item.get("date"))[:10] == day.isoformat()]

            if not sessions:
                return ProposalOutcome("not_found", msg.NO_SESSION_ON_DATE.format(name=name, date=date_br(day.isoformat())))

        candidates = [item for item in sessions if item.get("payment_status") != target]

        if not candidates:
            return ProposalOutcome("no_change", msg.PAYMENT_ALREADY.format(name=name, label=label))

        if len(candidates) > 1:
            dates = ", ".join(date_br(item.get("date")) for item in candidates[:MAX_LISTED])
            return ProposalOutcome("ambiguous", msg.MANY_SESSIONS.format(name=name, label_opposite=opposite, dates=dates))

        session = candidates[0]
        when = date_br(session.get("date"))
        summary = (
            f"Marcar como {label} a sessão de {name} de {when}, das {time_hm(session.get('start_time'))} "
            f"às {time_hm(session.get('end_time'))} (valor {money(session.get('session_value'))})."
        )
        params = {
            "patient_id": str(patient.get("id")),
            "session_id": str(session.get("id")),
            "patient_name": name,
            "date": str(session.get("date"))[:10],
            "target": target,
        }

        return self._proposal("set_session_payment", user_id, params, summary)

    def confirm(self, proposal_token: str, access_token: str) -> ActionResult:
        user_id = user_id_from_token(access_token)

        if not user_id:
            return ActionResult("auth", msg.AUTH_EXPIRED)

        try:
            payload = self._signer.verify(proposal_token)
        except ProposalError as error:
            text = msg.PROPOSAL_EXPIRED if error.reason == "expired" else msg.PROPOSAL_INVALID
            return ActionResult(error.reason, text)

        action = payload.get("act")
        params = payload.get("p")
        executors = {
            "create_appointment": self._exec_create,
            "cancel_appointment": self._exec_cancel,
            "confirm_appointment": self._exec_confirm,
            "set_session_payment": self._exec_payment,
            "create_patient": self._exec_create_patient,
            "update_patient": self._exec_update_patient,
            "deactivate_patient": self._exec_deactivate_patient,
            "reactivate_patient": self._exec_reactivate_patient,
        }

        if payload.get("uid") != user_id or payload.get("v") != 1 or action not in executors or not isinstance(params, dict):
            return ActionResult("invalid", msg.PROPOSAL_INVALID)

        try:
            result = executors[action](params, access_token)
        except UpstreamAuthError:
            result = ActionResult("auth", msg.AUTH_EXPIRED)
        except UpstreamConflictError:
            text = msg.PATIENT_CPF_CONFLICT if action in PATIENT_ACTIONS else msg.SLOT_NOW_TAKEN
            result = ActionResult("conflict", text)
        except UpstreamNotFoundError:
            result = ActionResult("not_found", msg.RECORD_GONE)
        except UpstreamValidationError as error:
            detail = str(error).strip()
            text = msg.REJECTED.format(detail=detail) if detail else msg.REJECTED_GENERIC
            result = ActionResult("rejected", text)
        except UpstreamUnavailableError:
            result = ActionResult("unavailable", msg.WRITE_UNCERTAIN)

        logger.info("Ação: action=%s status=%s", action, result.status)

        return ActionResult(result.status, result.message, action)

    def _exec_create(self, params: dict, token: str) -> ActionResult:
        self._api.create_appointment(
            token,
            params["patient_id"],
            {
                "date": params["date"],
                "start_time": params["start_time"],
                "end_time": params["end_time"],
                "is_home_visit": params["is_home_visit"],
            },
        )

        return ActionResult(
            "executed",
            msg.CREATED.format(
                name=params["patient_name"],
                date=date_br(params["date"]),
                start=params["start_time"],
                end=params["end_time"],
            ),
        )

    def _exec_cancel(self, params: dict, token: str) -> ActionResult:
        self._api.cancel_appointment(token, params["patient_id"], params["appointment_id"])

        return ActionResult("executed", msg.CANCELLED.format(name=params["patient_name"], date=date_br(params["date"])))

    def _exec_confirm(self, params: dict, token: str) -> ActionResult:
        session = self._api.confirm_appointment(token, params["patient_id"], params["appointment_id"])

        return ActionResult(
            "executed",
            msg.CONFIRMED.format(
                name=params["patient_name"],
                date=date_br(params["date"]),
                value=money(session.get("session_value")),
            ),
        )

    def _exec_payment(self, params: dict, token: str) -> ActionResult:
        target = params["target"]
        label = PAYMENT_LABELS.get(target, target)
        sessions = self._api.list_sessions(token, params["patient_id"])
        current = next((item for item in sessions if str(item.get("id")) == params["session_id"]), None)

        if current is None:
            return ActionResult("not_found", msg.RECORD_GONE)

        info = {"name": params["patient_name"], "date": date_br(params["date"]), "label": label}

        if current.get("payment_status") == target:
            return ActionResult("no_change", msg.PAYMENT_NO_CHANGE.format(**info))

        updated = self._api.toggle_session_payment(token, params["patient_id"], params["session_id"])

        if updated.get("payment_status") not in (None, target):
            actual = PAYMENT_LABELS.get(updated.get("payment_status"), str(updated.get("payment_status")))
            return ActionResult("rejected", f"A sessão ficou {actual}, e não {label}. Confira no aplicativo.")

        return ActionResult("executed", msg.PAYMENT_DONE.format(**info))

    def _find_by_cpf(self, token: str, cpf: str) -> dict | None:
        for active in (True, False):
            for item in self._api.list_patients(token, cpf, active):
                if patient_rules.digits(item.get("cpf")) == cpf:
                    return item

        return None

    def _propose_create_patient(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        clean, errors = patient_rules.validate_fields(arguments, self._today())

        if errors:
            return ProposalOutcome("invalid", msg.PATIENT_INVALID.format(errors="; ".join(errors)))

        missing = [patient_rules.LABELS[key] for key in patient_rules.REQUIRED if key not in clean]

        if missing:
            return ProposalOutcome("missing", msg.PATIENT_MISSING.format(fields=", ".join(missing)))

        existing = self._find_by_cpf(token, clean["cpf"])

        if existing:
            return ProposalOutcome("conflict", msg.PATIENT_CPF_EXISTS.format(name=existing.get("full_name")))

        extras = []

        if clean.get("email"):
            extras.append(f"e-mail {clean['email']}")

        if clean.get("birth_date"):
            extras.append(f"nascimento {date_br(clean['birth_date'])}")

        summary = (
            f"Cadastrar paciente: {clean['full_name']}, CPF {patient_rules.format_cpf(clean['cpf'])}, "
            f"telefone {clean['phone']}, valor da sessão {money(clean['session_value'])}"
            f"{', ' + ', '.join(extras) if extras else ''}."
        )

        return self._proposal("create_patient", user_id, {"body": clean, "patient_name": clean["full_name"]}, summary)

    def _propose_update_patient(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")
        clean, errors = patient_rules.validate_fields(arguments.get("changes") or {}, self._today())

        if errors:
            return ProposalOutcome("invalid", msg.PATIENT_INVALID.format(errors="; ".join(errors)))

        if not clean:
            return ProposalOutcome("missing", msg.PATIENT_NO_CHANGES_GIVEN.format(name=name))

        clean = {key: value for key, value in clean.items() if not patient_rules.same_value(key, patient.get(key), value)}

        if not clean:
            return ProposalOutcome("no_change", msg.PATIENT_NOTHING_TO_CHANGE.format(name=name))

        if "cpf" in clean:
            existing = self._find_by_cpf(token, clean["cpf"])

            if existing and str(existing.get("id")) != str(patient.get("id")):
                return ProposalOutcome("conflict", msg.PATIENT_CPF_EXISTS.format(name=existing.get("full_name")))

        parts = []

        for key, value in clean.items():
            label = patient_rules.LABELS[key]
            current = patient.get(key)

            if key == "session_value":
                parts.append(f"{label} de {money(current)} para {money(value)}")
            elif key == "cpf":
                parts.append(f"{label} para {patient_rules.format_cpf(value)}")
            elif key == "birth_date":
                parts.append(f"{label} para {date_br(value)}")
            elif key == "phone" and current:
                parts.append(f"{label} de {current} para {value}")
            else:
                parts.append(f"{label} para {value}")

        summary = f"Alterar dados de {name}: {'; '.join(parts)}."
        params = {"patient_id": str(patient.get("id")), "patient_name": name, "body": clean}

        return self._proposal("update_patient", user_id, params, summary)

    def _propose_deactivate_patient(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")

        if not patient.get("is_active", True):
            return ProposalOutcome("no_change", msg.PATIENT_ALREADY_INACTIVE.format(name=name))

        params = {"patient_id": str(patient.get("id")), "patient_name": name}

        return self._proposal("deactivate_patient", user_id, params, msg.PATIENT_DEACTIVATE_SUMMARY.format(name=name))

    def _propose_reactivate_patient(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")

        if patient.get("is_active", True):
            return ProposalOutcome("no_change", msg.PATIENT_ALREADY_ACTIVE.format(name=name))

        params = {"patient_id": str(patient.get("id")), "patient_name": name}

        return self._proposal("reactivate_patient", user_id, params, msg.PATIENT_REACTIVATE_SUMMARY.format(name=name))

    def _exec_create_patient(self, params: dict, token: str) -> ActionResult:
        self._api.create_patient(token, params["body"])

        return ActionResult("executed", msg.PATIENT_CREATED.format(name=params["patient_name"]))

    def _exec_update_patient(self, params: dict, token: str) -> ActionResult:
        self._api.update_patient(token, params["patient_id"], params["body"])

        return ActionResult("executed", msg.PATIENT_UPDATED.format(name=params["patient_name"]))

    def _exec_deactivate_patient(self, params: dict, token: str) -> ActionResult:
        self._api.deactivate_patient(token, params["patient_id"])

        return ActionResult("executed", msg.PATIENT_DEACTIVATED.format(name=params["patient_name"]))

    def _exec_reactivate_patient(self, params: dict, token: str) -> ActionResult:
        self._api.reactivate_patient(token, params["patient_id"])

        return ActionResult("executed", msg.PATIENT_REACTIVATED.format(name=params["patient_name"]))