import base64
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable

from app.actions import patient_rules
from app.actions.identity import authenticated_user_id
from app.actions.command_signer import AssistantCommandSigner, AssistantCommandSigningError
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
        *,
        command_signer: AssistantCommandSigner | None = None,
        enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self._api = api
        self._signer = signer
        self._today = today_fn
        self._default_minutes = default_minutes
        self._patient_actions = patient_actions_enabled
        self._command_signer = command_signer
        self._enabled = enabled

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
            context = self._api.assistant_context(token, str(lookup.patient["id"]))
            patient = dict(context["patient"])
            patient["_appointments"] = context["appointments"]
            patient["_sessions"] = context["sessions"]
            return patient, None

        if lookup.kind == AMBIGUOUS:
            return None, ProposalOutcome("ambiguous", msg.PATIENT_AMBIGUOUS.format(names=", ".join(lookup.names)))

        return None, ProposalOutcome("not_found", msg.PATIENT_NOT_FOUND)

    def _proposal(self, action: str, user_id: str, params: dict, summary: str, preconditions: dict | None = None) -> ProposalOutcome:
        if self._command_signer is None or not self._enabled():
            return ProposalOutcome("unsupported", msg.ACTIONS_UNAVAILABLE_MESSAGE)
        ttl = min(self._signer.ttl, 300)
        envelope = self._command_signer.sign(
            professional_id=user_id, action=action, parameters=params,
            preconditions=preconditions or {}, ttl_seconds=ttl,
        )
        command = json.loads(base64.urlsafe_b64decode(envelope["command"] + "=" * (-len(envelope["command"]) % 4)))
        token = self._signer.sign({
            "v": 2, "act": action, "uid": user_id, "command": envelope,
            "execution_id": command["execution_id"],
        })
        return ProposalOutcome("proposed", f"{summary}\n{msg.CONFIRM_SUFFIX.format(minutes=ttl // 60)}", {
            "token": token, "action": action, "summary": summary, "expires_in_seconds": ttl,
        })

    @staticmethod
    def _preconditions(patient: dict, kind: str | None = None, record: dict | None = None) -> dict:
        result = {"patient_revision": patient.get("assistant_revision")}
        if kind:
            result[f"{kind}_revision"] = record.get("assistant_revision")
        if any(not isinstance(value, str) or not value.isdigit() or int(value) <= 0 for value in result.values()):
            raise UpstreamUnavailableError("Revisões de registros indisponíveis")
        return result

    def propose(self, action: str, arguments: dict, token: str) -> ProposalOutcome:
        user_id = authenticated_user_id(self._api, token)
        if self._command_signer is None or not self._enabled():
            return ProposalOutcome("unsupported", msg.ACTIONS_UNAVAILABLE_MESSAGE)

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
        except (UpstreamUnavailableError, AssistantCommandSigningError):
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

        return self._proposal("create_appointment", user_id, params, summary, self._preconditions(patient))

    def _pick_appointment(self, arguments: dict, token: str, patient: dict, day: date):
        items = [
            item
            for item in patient["_appointments"]
            if item.get("status") == "scheduled" and str(item.get("date"))[:10] == day.isoformat()
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

        return self._proposal("cancel_appointment", user_id, params, summary, self._preconditions(patient, "appointment", appointment))

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

        return self._proposal("confirm_appointment", user_id, params, summary, self._preconditions(patient, "appointment", appointment))

    def _propose_payment(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")
        sessions = patient["_sessions"]
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

        return self._proposal("set_session_payment", user_id, params, summary, self._preconditions(patient, "session", session))

    def _confirmed_payload(self, proposal_token: str, access_token: str):
        user_id = authenticated_user_id(self._api, access_token)
        try:
            payload = self._signer.verify(proposal_token, allow_expired=True)
        except ProposalError as error:
            return None, ActionResult(error.reason, msg.PROPOSAL_INVALID)
        if (payload.get("uid") != user_id or payload.get("v") != 2
                or not isinstance(payload.get("command"), dict)
                or not isinstance(payload.get("execution_id"), str)):
            return None, ActionResult("invalid", msg.PROPOSAL_INVALID)
        action = payload.get("act")
        if not self._enabled() or (action in PATIENT_ACTIONS and not self._patient_actions):
            return None, ActionResult("rejected", msg.ACTIONS_UNAVAILABLE_MESSAGE, action)
        return payload, None

    @staticmethod
    def _execution_result(data: dict, action: str) -> ActionResult:
        result = data.get("result")
        if data.get("state") in {"completed", "rejected"} and isinstance(result, dict) and result.get("action") == action:
            return ActionResult(result["status"], result["message"], action)
        return ActionResult("unavailable", msg.WRITE_UNCERTAIN, action)

    def recover(self, proposal_token: str, access_token: str) -> ActionResult:
        payload, error = self._confirmed_payload(proposal_token, access_token)
        if error:
            return error
        try:
            data = self._api.assistant_execution_result(access_token, payload["execution_id"])
            return self._execution_result(data, payload["act"])
        except UpstreamAuthError:
            return ActionResult("auth", msg.AUTH_EXPIRED, payload["act"])
        except UpstreamUnavailableError:
            return ActionResult("unavailable", msg.WRITE_UNCERTAIN, payload["act"])

    def confirm(self, proposal_token: str, access_token: str) -> ActionResult:
        payload, error = self._confirmed_payload(proposal_token, access_token)
        if error:
            return error
        action = payload["act"]
        try:
            data = self._api.execute_assistant_command(access_token, payload["command"])
            return self._execution_result(data, action)
        except UpstreamAuthError:
            return ActionResult("auth", msg.AUTH_EXPIRED, action)
        except UpstreamValidationError:
            return ActionResult("invalid", msg.PROPOSAL_INVALID, action)
        except UpstreamUnavailableError:
            # A read may reconcile a lost response. It never repeats the write.
            return self.recover(proposal_token, access_token)

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

        return self._proposal("update_patient", user_id, params, summary, self._preconditions(patient))

    def _propose_deactivate_patient(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")

        if not patient.get("is_active", True):
            return ProposalOutcome("no_change", msg.PATIENT_ALREADY_INACTIVE.format(name=name))

        params = {"patient_id": str(patient.get("id")), "patient_name": name}

        return self._proposal("deactivate_patient", user_id, params, msg.PATIENT_DEACTIVATE_SUMMARY.format(name=name), self._preconditions(patient))

    def _propose_reactivate_patient(self, arguments: dict, token: str, user_id: str) -> ProposalOutcome:
        patient, error = self._patient(arguments, token)

        if error:
            return error

        name = patient.get("full_name")

        if patient.get("is_active", True):
            return ProposalOutcome("no_change", msg.PATIENT_ALREADY_ACTIVE.format(name=name))

        params = {"patient_id": str(patient.get("id")), "patient_name": name}

        return self._proposal("reactivate_patient", user_id, params, msg.PATIENT_REACTIVATE_SUMMARY.format(name=name), self._preconditions(patient))
