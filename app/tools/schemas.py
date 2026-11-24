from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SearchPatientsArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    query: str | None = Field(default=None, max_length=100)
    active: bool = True


class PatientProfileArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    patient_name: str = Field(min_length=2, max_length=100)


class FinancialSummaryArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)


class DateFields(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str | None = None
    relative: Literal["today", "tomorrow", "yesterday", "this_week", "next_week", "previous_week"] | None = None
    weekday: Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] | None = None
    direction: Literal["next", "previous"] = "next"

    @field_validator("date")
    @classmethod
    def validate_date(cls, value):
        if not value:
            return None

        date_type.fromisoformat(value)

        return value



class DateArgs(DateFields):
    @model_validator(mode="after")
    def require_reference(self):
        if not (self.date or self.relative or self.weekday):
            raise ValueError("informe date, relative ou weekday")

        return self


ARGUMENT_MODELS = {
    "search_patients": SearchPatientsArgs,
    "get_patient_profile": PatientProfileArgs,
    "get_financial_summary": FinancialSummaryArgs,
    "get_schedule_day": DateArgs,
    "get_schedule_week": DateArgs,
}