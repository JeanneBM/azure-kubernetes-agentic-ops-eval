import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from agentic_ops.agents import SafeRemediationAgent
from agentic_ops.orchestrator import IncidentOrchestrator
from agentic_ops.remote import HttpRemediationAgent
from agentic_ops.timeouts import Timeouts
from agentic_ops.web import create_app
from conftest import FakeDiagnostics, FakeExecutor, make_facts, make_policy, make_trigger


def remote(handler, **kwargs):
    return HttpRemediationAgent(
        "http://remediation", "token", "test-app",
        http_client=httpx.Client(transport=httpx.MockTransport(handler), timeout=1), **kwargs,
    )


def test_handoff_read_budget_exceeds_rollout_even_for_injected_client():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"executed": True, "successful": True})

    result = remote(respond).remediate(make_trigger(), make_facts())
    assert result.executed is True and result.successful
    assert requests[0].extensions["timeout"]["read"] == 180
    assert requests[0].extensions["timeout"]["connect"] == 10
    assert Timeouts().handoff > Timeouts().verify + 30


@pytest.mark.parametrize("verify,handoff", [(120, 90), (120, 150), (0, 180),
    (120, -1), (float("nan"), 180), (120, float("inf"))])
def test_invalid_budgets_fail_before_any_request(verify, handoff):
    with pytest.raises(ValueError):
        remote(lambda request: pytest.fail("request must not run"),
               verify_timeout=verify, handoff_timeout=handoff)


def test_shared_budget_is_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("AGENTIC_OPS_VERIFY_TIMEOUT_SECONDS", "200")
    monkeypatch.setenv("AGENTIC_OPS_HANDOFF_TIMEOUT_SECONDS", "240")
    assert Timeouts.from_env() == Timeouts(verify=200, handoff=240)
    monkeypatch.setenv("AGENTIC_OPS_HANDOFF_TIMEOUT_SECONDS", "220")
    from agentic_ops.split_app import build_app
    monkeypatch.setenv("AGENTIC_OPS_ROLE", "diagnostic")
    # No kubeconfig/credentials are present or required: validation happens first.
    with pytest.raises(ValueError, match="margin"):
        build_app()


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ReadError, httpx.ConnectError])
def test_transport_errors_are_unknown_and_not_retried(error_type):
    calls = []

    def fail(request):
        calls.append(request)
        raise error_type("connection lost", request=request)

    outcome = remote(fail).remediate(make_trigger(), make_facts())
    assert outcome.executed is None
    assert not outcome.successful
    assert "outcome unknown" in outcome.reason
    assert len(calls) == 1


@pytest.mark.parametrize("body", [
    {"executed": None, "successful": False},
    {"executed": "false", "successful": False},
    {"executed": False, "successful": True},
    {"executed": None, "successful": True},
    {"successful": False},
])
def test_unknown_or_invalid_acknowledgement_never_becomes_confirmed_failure(body):
    outcome = remote(lambda request: httpx.Response(200, json=body)).remediate(make_trigger(), make_facts())
    assert outcome.executed is None
    assert not outcome.successful


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, text="not JSON")])
def test_server_error_or_malformed_response_is_unknown(response):
    outcome = remote(lambda request: response).remediate(make_trigger(), make_facts())
    assert outcome.executed is None and not outcome.successful


def test_explicit_refusal_remains_confirmed_not_executed():
    outcome = remote(lambda request: httpx.Response(200, json={
        "executed": False, "successful": False, "reason": "second agent policy: refused",
    })).remediate(make_trigger(), make_facts())
    assert outcome.executed is False
    assert not outcome.successful


def test_lost_ack_after_patch_survives_webhook_and_audit_as_unknown(caplog):
    executor = FakeExecutor()
    remediation = SafeRemediationAgent(make_policy(), executor)
    calls = []

    def patch_then_lose_ack(request):
        calls.append(request)
        assert remediation.remediate(make_trigger(), make_facts()).executed is True
        raise httpx.ReadTimeout("response lost after patch", request=request)

    orchestrator = IncidentOrchestrator(
        FakeDiagnostics(make_facts()), remediation_agent=remote(patch_then_lose_ack),
    )
    app = create_app(orchestrator, resolve_workload=lambda ns, pod: "test-app", webhook_token="token")
    with caplog.at_level(logging.INFO, logger="agentic_ops.audit"), TestClient(app) as client:
        response = client.post("/api/v1/incidents", json={
            "namespace": "test-app", "pod": "test-app-abc-1", "workload": "test-app",
            "reason": "ImagePullBackOff", "correlation_id": "lost-ack",
        }, headers={"X-Webhook-Token": "token"})
    assert response.status_code == 200
    assert response.json()["status"] == "escalated"
    assert response.json()["action_executed"] is None
    event = next(json.loads(r.message) for r in caplog.records if r.message.startswith("{"))
    assert event["action_executed"] is None
    assert len(executor.actions) == len(calls) == 1


def test_verification_error_after_patch_preserves_confirmed_execution():
    class BrokenVerifier(FakeExecutor):
        def verify(self, action):
            raise RuntimeError("Kubernetes read unavailable")

    executor = BrokenVerifier()
    result = IncidentOrchestrator(FakeDiagnostics(make_facts()), executor, make_policy()).handle(make_trigger())
    assert result.incident.status.value == "escalated"
    assert result.action_executed is True
    assert "verification failed" in result.incident.reason
    assert len(executor.actions) == 1
