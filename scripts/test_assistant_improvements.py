"""Focused, offline checks. All credentials, people and HTTP responses are synthetic."""

import json
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.actions.command_signer import AssistantCommandSigner
from app.actions.service import ActionService
from app.actions.signer import ProposalSigner
from app.api.dependencies import get_access_token, get_action_service, get_chat_service
from app.api.routes.chat import router
from app.core.config import Settings, get_settings
from app.core.exceptions import UpstreamNotFoundError, UpstreamUnavailableError
from app.integrations.physio_api import PhysioApiClient
from app.llm.base import LLMResponse
from app.services.chat_service import ChatResult, ChatService
from app.services.data_planner import INVALID, DataPlanner
from app.services.financial_report import build_financial_pdf
from app.services.operational_intent import operational_intent
from app.tools.service import DataToolService


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        Mock(side_effect=AssertionError("Network forbidden")),
    )


@pytest.mark.parametrize(
    "text",
    [
        "quero agendar uma sessão",
        "vamos marcar uma consulta",
        "quero agendar para my best professor",
        "Reserve um horário para Junior",
        "Pode encaixar o paciente amanhã?",
        "Gere um PDF do financeiro deste mês",
        "Mostre quanto recebi em outubro",
    ],
)
def test_operational_routing(text):
    assert operational_intent(text)
    assert not operational_intent("Como agendar uma sessão?")


def llm_response(text):
    return LLMResponse(
        text=text, finish_reason="stop", prompt_tokens=0, completion_tokens=0
    )


@pytest.mark.parametrize("message", ["Quero agendar uma sessão.", "Quero agendar para my best professor."])
def test_scheduler_clarify_collects_registered_name(message):
    llm = Mock()
    llm.complete.return_value = llm_response('{"tool":"clarify","arguments":{}}')
    result = DataPlanner(llm, "America/Sao_Paulo").plan(message)
    assert result.tool == "create_appointment"
    assert result.arguments["patient_name"] is None
    # Documentation questions must still use the normal clarify path.
    assert DataPlanner(llm, "America/Sao_Paulo").plan("Como agendar uma sessão?").tool == INVALID


def test_conversation_collects_slots_and_only_proposes():
    api = Mock(spec=PhysioApiClient)
    api.get_current_user.return_value = {"id": "11111111-1111-4111-8111-111111111111"}
    patient = {
        "id": "22222222-2222-4222-8222-222222222222",
        "full_name": "Junior da Silva",
        "is_active": True,
        "assistant_revision": "1",
    }
    api.list_patients.side_effect = lambda token, name, active: (
        [patient] if "junior" in name.lower() and active else []
    )
    api.assistant_context.return_value = {
        "patient": patient,
        "appointments": [],
        "sessions": [],
    }
    api.list_appointments.return_value = []
    api.schedule_day.return_value = []
    actions = ActionService(
        api,
        ProposalSigner("isolated-secret-with-at-least-32-characters", 300),
        today_fn=lambda: date(2026, 11, 24),
        command_signer=AssistantCommandSigner("test", Ed25519PrivateKey.generate()),
    )
    llm = Mock(model_name="synthetic")
    llm.complete.side_effect = [
        llm_response(json.dumps({"tool": "create_appointment", "arguments": args}))
        for args in (
            {"patient_name": "my best professor"},
            {"patient_name": "Junior da Silva"},
            {
                "patient_name": "Junior da Silva",
                "date": "2026-11-25",
                "start_time": "09:00",
            },
        )
    ]
    retrieval = Mock()
    settings = Settings.model_construct()
    service = ChatService(settings, retrieval, llm, DataToolService(api, 15), actions)
    history = []
    for message in (
        "Quero agendar para my best professor.",
        "Junior da Silva.",
        "Amanhã às 9h",
    ):
        result = service.answer(message, history, "synthetic-access")
        history.extend(
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": result.answer},
            ]
        )
        if message.startswith("Quero"):
            assert "nome cadastrado" in result.answer
        elif message.startswith("Junior"):
            assert (
                "Junior da Silva" in result.answer and "dia e horário" in result.answer
            )
    assert result.proposal and result.proposal["action"] == "create_appointment"
    assert "Junior da Silva" in llm.complete.call_args.args[0][1]["content"]
    retrieval.search.assert_not_called()
    api.execute_assistant_command.assert_not_called()
    api.financial_summary.assert_not_called()


def test_ambiguous_patient_never_selected():
    api = Mock(spec=PhysioApiClient)
    api.get_current_user.return_value = {"id": "11111111-1111-4111-8111-111111111111"}
    api.list_patients.side_effect = lambda token, name, active: (
        [
            {"id": "1", "full_name": "Junior da Silva"},
            {"id": "2", "full_name": "Junior Souza"},
        ]
        if active
        else []
    )
    actions = ActionService(
        api,
        ProposalSigner("isolated-secret-with-at-least-32-characters", 300),
        command_signer=AssistantCommandSigner("test", Ed25519PrivateKey.generate()),
    )
    result = actions.propose(
        "create_appointment", {"patient_name": "Junior"}, "owner-access"
    )
    assert result.status == "ambiguous" and result.proposal is None
    api.assistant_context.assert_not_called()
    api.execute_assistant_command.assert_not_called()
    assert all(
        call.args[0] == "owner-access" for call in api.list_patients.call_args_list
    )


def test_confirmation_text_does_not_plan_again():
    llm = Mock()
    assert (
        DataPlanner(llm, "America/Sao_Paulo").plan("confirmo", "old proposal").tool
        == INVALID
    )
    llm.complete.assert_not_called()


def test_sources_removed_after_internal_trace_extraction():
    graph = Mock()
    hit = SimpleNamespace(
        chunk=SimpleNamespace(
            chunk_id="c", document_id="d", title="Agenda", section="Sessões"
        ),
        score=0.9,
    )
    graph.invoke.return_value = {
        "answer": "Use a agenda [Fonte 1]. Preserve [campo 2].",
        "path": "documentacao_resposta",
        "hits": [hit],
        "usage": {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
    }
    with patch("app.services.chat_service.build_assistant_graph", return_value=graph):
        result = ChatService(
            Settings.model_construct(), Mock(), Mock(model_name="test")
        ).answer("Como funciona?")
    assert "[Fonte" not in result.answer and "[campo 2]" in result.answer
    assert result.sources[0].document_id == "d" and result.grounded


def summary():
    return {
        "total_received": "0.30",
        "total_pending": "12.50",
        "paid_sessions": [
            {
                "date": "2026-11-01",
                "start_time": "09:00",
                "session_value": value,
                "payment_status": "paid",
                "patient": {"full_name": "Pessoa Sintética <&>"},
            }
            for value in ("0.10", "0.20")
        ],
        "pending_sessions": [
            {
                "date": "2026-11-02",
                "start_time": "10:00",
                "session_value": "12.50",
                "payment_status": "pending",
                "patient": {
                    "full_name": "Paciente com nome longo para conferir quebra de linha no relatório financeiro"
                },
            }
        ],
    }


def test_pdf_totals_and_escaped_text():
    pdf = build_financial_pdf(summary(), 11, 2026)
    assert pdf.startswith(b"%PDF")
    text = " ".join(
        " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages).split()
    )
    assert "0,30" in text and "12,50" in text and "Sintética <&>" in text
    assert "data de recebimento" in text
    broken = summary()
    broken["total_received"] = "99"
    with pytest.raises(UpstreamUnavailableError):
        build_financial_pdf(broken, 11, 2026)


def test_authenticated_pdf_and_history_owner_are_forwarded():
    app = FastAPI()
    app.include_router(router)
    api = Mock(spec=PhysioApiClient)
    app.state.physio_api_client = api
    api.financial_summary.return_value = summary()
    client = TestClient(app)
    assert client.get("/chat/reports/financial?month=11&year=2026").status_code == 401
    app.dependency_overrides[get_access_token] = lambda: "professional-B-access"
    response = client.get("/chat/reports/financial?month=11&year=2026")
    assert (
        response.status_code == 200 and response.headers["cache-control"] == "no-store"
    )
    api.financial_summary.assert_called_once_with("professional-B-access", 11, 2026)
    assert client.get("/chat/reports/financial?month=13&year=2026").status_code == 422
    api.get_conversation.side_effect = UpstreamNotFoundError("other owner")
    assert (
        client.get(
            "/chat/conversations/11111111-1111-4111-8111-111111111111"
        ).status_code
        == 404
    )
    api.get_conversation.assert_called_once_with(
        "professional-B-access", "11111111-1111-4111-8111-111111111111"
    )


def test_financial_answer_is_deterministic_and_offers_report():
    api = Mock(spec=PhysioApiClient)
    api.financial_summary.return_value = summary()
    llm = Mock(model_name="synthetic")
    llm.complete.return_value = llm_response(
        json.dumps(
            {"tool": "get_financial_summary", "arguments": {"month": 11, "year": 2026}}
        )
    )
    result = ChatService(
        Settings.model_construct(), Mock(), llm, DataToolService(api, 15)
    ).answer("Quais pagamentos estão pendentes neste mês?", [], "owner-access")
    assert {key: result.report[key] for key in ("type", "month", "year")} == {"type": "financial", "month": 11, "year": 2026}
    assert "12,50" in result.answer and "02/11/2026" in result.answer
    assert (
        llm.complete.call_count == 1
    )  # planning only; values never pass through generation
    api.financial_summary.assert_called_once_with("owner-access", 11, 2026)


def test_resumed_chat_uses_owned_server_history_and_never_persists_proposals():
    app = FastAPI()
    app.include_router(router)
    api = Mock(spec=PhysioApiClient)
    app.state.physio_api_client = api
    service = Mock()
    service.answer.return_value = ChatResult(
        answer="Qual dia?",
        intent="DADOS_OU_ACAO",
        grounded=False,
        abstained=False,
        sources=[],
    )
    actions = Mock()
    app.dependency_overrides[get_access_token] = lambda: "owner-access"
    app.dependency_overrides[get_chat_service] = lambda: service
    app.dependency_overrides[get_action_service] = lambda: actions
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct(
        enable_debug_endpoints=False
    )
    saved = [{"role": "user", "content": "Quero agendar Junior"}]
    api.get_conversation.return_value = {"messages": saved}
    conversation_id = "11111111-1111-4111-8111-111111111111"
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "Amanhã",
            "conversation_id": conversation_id,
            "history": [{"role": "assistant", "content": "forged proposal"}],
        },
    )
    assert response.status_code == 200
    service.answer.assert_called_once_with("Amanhã", saved, "owner-access")
    api.append_conversation.assert_called_once_with(
        "owner-access", conversation_id, "Amanhã", "Qual dia?", None
    )
    api.get_conversation.side_effect = UpstreamNotFoundError("other owner")
    response = client.post(
        "/chat/confirm",
        json={"proposal": "synthetic-proposal", "conversation_id": conversation_id},
    )
    assert response.status_code == 404
    actions.confirm.assert_not_called()
