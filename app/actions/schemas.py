import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.tools.schemas import DateFields

TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")
WEEK_RELATIVES = {"this_week", "next_week", "previous_week"}


def normalize_time(value) -> str | None:
    if value is None or value == "":
        return None

    match = TIME_PATTERN.match(str(value).strip())

    if not match:
        raise ValueError("horário deve estar no formato HH:MM")

    hours, minutes = int(match.group(1)), int(match.group(2))

    if hours > 23 or minutes > 59:
        raise ValueError("horário inválido")

    return f"{hours:02d}:{minutes:02d}"


class DayFields(DateFields):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @model_validator(mode="after")
    def reject_week_references(self):
        if self.relative in WEEK_RELATIVES:
            raise ValueError("referência de semana não vale para uma ação")

        return self


class RequiredDayFields(DayFields):
    @model_validator(mode="after")
    def require_reference(self):
        if not (self.date or self.relative or self.weekday):
            raise ValueError("informe o dia")

        return self


class CreateAppointmentArgs(RequiredDayFields):
    patient_name: str = Field(min_length=2, max_length=100)
    start_time: str
    end_time: str | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=480)
    is_home_visit: bool = False

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value):
        return normalize_time(value)

    @model_validator(mode="after")
    def validate_order(self):
        if self.start_time is None:
            raise ValueError("informe o horário de início")

        if self.end_time and self.end_time <= self.start_time:
            raise ValueError("o término deve ser depois do início")

        return self


class AppointmentRefArgs(RequiredDayFields):
    patient_name: str = Field(min_length=2, max_length=100)
    start_time: str | None = None

    @field_validator("start_time")
    @classmethod
    def validate_time(cls, value):
        return normalize_time(value)


class CancelAppointmentArgs(AppointmentRefArgs):
    pass


class ConfirmAppointmentArgs(AppointmentRefArgs):
    pass


class SessionPaymentArgs(DayFields):
    patient_name: str = Field(min_length=2, max_length=100)
    paid: bool


class PatientFields(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    full_name: str | None = Field(default=None, max_length=255)
    cpf: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=30)
    session_value: float | None = None
    email: str | None = Field(default=None, max_length=255)
    birth_date: str | None = Field(default=None, max_length=10)
    rg: str | None = Field(default=None, max_length=30)
    zip_code: str | None = Field(default=None, max_length=12)
    street: str | None = Field(default=None, max_length=255)
    number: str | None = Field(default=None, max_length=20)
    neighborhood: str | None = Field(default=None, max_length=100)


class CreatePatientArgs(PatientFields):
    pass


class PatientNameArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    patient_name: str = Field(min_length=2, max_length=100)


class UpdatePatientArgs(PatientNameArgs):
    changes: PatientFields = Field(default_factory=PatientFields)


class DeactivatePatientArgs(PatientNameArgs):
    pass


class ReactivatePatientArgs(PatientNameArgs):
    pass


PATIENT_ACTIONS = {"create_patient", "update_patient", "deactivate_patient", "reactivate_patient"}

ACTION_MODELS = {
    "create_patient": CreatePatientArgs,
    "update_patient": UpdatePatientArgs,
    "deactivate_patient": DeactivatePatientArgs,
    "reactivate_patient": ReactivatePatientArgs,
    "create_appointment": CreateAppointmentArgs,
    "cancel_appointment": CancelAppointmentArgs,
    "confirm_appointment": ConfirmAppointmentArgs,
    "set_session_payment": SessionPaymentArgs,
}