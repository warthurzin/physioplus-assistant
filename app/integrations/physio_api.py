import httpx

from app.core.exceptions import (
    UpstreamAuthError,
    UpstreamConflictError,
    UpstreamNotFoundError,
    UpstreamUnavailableError,
    UpstreamValidationError,
)


def _message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""

    if isinstance(body, dict):
        return str(body.get("message", ""))[:200]

    return ""


class PhysioApiClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        force_ipv4: bool = False,
    ) -> None:
        if transport is None and force_ipv4:
            transport = httpx.HTTPTransport(local_address="0.0.0.0")

        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(timeout, connect=min(3.0, timeout)),
            transport=transport,
        )

    def _request(
        self,
        method: str,
        token: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
    ):
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException as error:
            raise UpstreamUnavailableError("tempo esgotado") from error
        except httpx.HTTPError as error:
            raise UpstreamUnavailableError("falha de conexão") from error

        status = response.status_code

        if status == 401:
            raise UpstreamAuthError(_message(response))

        if status in (403, 404):
            raise UpstreamNotFoundError(_message(response))

        if status == 409:
            raise UpstreamConflictError(_message(response))

        if status in (400, 422):
            raise UpstreamValidationError(_message(response))

        if status >= 400:
            raise UpstreamUnavailableError(f"status {status}")

        if status == 204 or not response.content:
            return None

        try:
            return response.json().get("data")
        except (ValueError, AttributeError) as error:
            raise UpstreamUnavailableError("resposta inválida") from error

    def _get(self, token: str, path: str, params: dict | None = None):
        return self._request("GET", token, path, params)

    def list_patients(self, token: str, search: str | None, active: bool) -> list[dict]:
        params = {"active": "true" if active else "false"}

        if search:
            params["search"] = search

        data = self._get(token, "patients", params)

        return data if isinstance(data, list) else []

    def get_patient(self, token: str, patient_id: str) -> dict:
        data = self._get(token, f"patients/{patient_id}")

        return data if isinstance(data, dict) else {}

    def schedule_day(self, token: str, day: str) -> list:
        data = self._get(token, "schedule/day", {"date": day})

        return data if isinstance(data, list) else []

    def schedule_week(self, token: str, day: str) -> list:
        data = self._get(token, "schedule/week", {"date": day})

        return data if isinstance(data, list) else []

    def financial_summary(self, token: str, month: int, year: int) -> dict:
        data = self._get(token, "financial/summary", {"month": month, "year": year})

        return data if isinstance(data, dict) else {}

    def list_appointments(self, token: str, day: str | None = None, patient_id: str | None = None) -> list:
        params = {}

        if day:
            params["date"] = day

        if patient_id:
            params["patientId"] = patient_id

        data = self._get(token, "appointments", params)

        return data if isinstance(data, list) else []

    def list_sessions(self, token: str, patient_id: str) -> list:
        data = self._get(token, f"patients/{patient_id}/sessions")

        return data if isinstance(data, list) else []

    def create_appointment(self, token: str, patient_id: str, body: dict) -> dict:
        data = self._request("POST", token, f"patients/{patient_id}/appointments", body=body)

        return data if isinstance(data, dict) else {}

    def create_patient(self, token: str, body: dict) -> dict:
        data = self._request("POST", token, "patients", body=body)

        return data if isinstance(data, dict) else {}

    def update_patient(self, token: str, patient_id: str, body: dict) -> dict:
        data = self._request("PUT", token, f"patients/{patient_id}", body=body)

        return data if isinstance(data, dict) else {}

    def deactivate_patient(self, token: str, patient_id: str) -> None:
        self._request("DELETE", token, f"patients/{patient_id}")

    def reactivate_patient(self, token: str, patient_id: str) -> None:
        self._request("PATCH", token, f"patients/{patient_id}/reactivate")

    def cancel_appointment(self, token: str, patient_id: str, appointment_id: str) -> None:
        self._request("DELETE", token, f"patients/{patient_id}/appointments/{appointment_id}")

    def confirm_appointment(self, token: str, patient_id: str, appointment_id: str) -> dict:
        data = self._request("POST", token, f"patients/{patient_id}/appointments/{appointment_id}/confirm")

        return data if isinstance(data, dict) else {}

    def toggle_session_payment(self, token: str, patient_id: str, session_id: str) -> dict:
        data = self._request("PATCH", token, f"patients/{patient_id}/sessions/{session_id}/payment")

        return data if isinstance(data, dict) else {}