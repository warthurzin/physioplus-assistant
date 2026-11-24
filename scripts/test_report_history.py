from copy import deepcopy
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_access_token
from app.api.routes.chat import router
from app.core.exceptions import UpstreamNotFoundError
from app.integrations.physio_api import PhysioApiClient
from app.services.report_metadata import financial_report_metadata, financial_snapshot
from scripts.test_assistant_improvements import summary

CID = "11111111-1111-4111-8111-111111111111"


def test_report_snapshot_covers_displayed_data_without_order_or_accumulated_noise():
    original = summary()
    changed = deepcopy(original)
    changed["paid_sessions"].reverse()
    changed["total_accumulated"] = "900"
    assert financial_snapshot(changed) == financial_snapshot(original)
    changed["paid_sessions"][0]["session_value"] = "1.00"
    assert financial_snapshot(changed) != financial_snapshot(original)


def test_history_download_enforces_owner_period_and_detects_updated_data():
    app = FastAPI()
    app.include_router(router)
    api = Mock(spec=PhysioApiClient)
    app.state.physio_api_client = api
    data = summary()
    report = financial_report_metadata(data, 11, 2026)
    api.get_conversation.return_value = {
        "messages": [{"role": "assistant", "content": "Resumo", "report": report}]
    }
    api.financial_summary.return_value = data
    client = TestClient(app)
    path = f"/chat/conversations/{CID}/reports/0"
    assert client.get(path).status_code == 401
    app.dependency_overrides[get_access_token] = lambda: "professional-A"
    response = client.get(path + "?month=1&year=2000")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert response.headers["x-report-updated"] == "false"
    assert response.headers["cache-control"] == "no-store"
    api.financial_summary.assert_called_once_with("professional-A", 11, 2026)
    updated = deepcopy(data)
    updated["total_pending"] = "18.50"
    updated["pending_sessions"][0]["session_value"] = "18.50"
    api.financial_summary.return_value = updated
    assert client.get(path).headers["x-report-updated"] == "true"
    del report["snapshot_hash"]
    assert client.get(path).headers["x-report-updated"] == "unknown"
    assert client.get(f"/chat/conversations/{CID}/reports/-1").status_code == 404
    api.get_conversation.side_effect = UpstreamNotFoundError("other owner")
    app.dependency_overrides[get_access_token] = lambda: "professional-B"
    assert client.get(path).status_code == 404
    api.get_conversation.assert_called_with("professional-B", CID)
