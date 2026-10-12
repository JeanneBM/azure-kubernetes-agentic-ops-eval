import pytest
from fastapi.testclient import TestClient

from agentic_ops.agents import SafeRemediationAgent
from agentic_ops.contracts import PullFailure
from agentic_ops.remote import FactsPayload, HandoffPayload, create_remediation_app
from conftest import FakeExecutor, make_facts, make_policy, make_trigger, OLD


def payload():
    trigger = make_trigger()
    facts = make_facts(failures=(PullFailure("api", OLD), PullFailure("metrics", OLD)))
    return HandoffPayload(
        namespace=trigger.namespace, pod=trigger.pod, workload=trigger.workload,
        reason=trigger.reason, correlation_id=trigger.correlation_id,
        facts=FactsPayload.from_facts(facts),
    ).model_dump()


def test_two_pull_failures_return_policy_refusal_instead_of_http_500():
    executor = FakeExecutor()
    app = create_remediation_app(SafeRemediationAgent(make_policy(), executor), agent_token="test-token")
    with TestClient(app) as client:
        response = client.post("/internal/v1/remediate", json=payload(), headers={"X-Agent-Token": "test-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["executed"] is False
    assert body["successful"] is False
    assert body["action"] is None
    assert body["reason"] == "second agent policy: Expected exactly one container failing to pull, found 2"
    assert executor.actions == []


def test_policy_refusal_endpoint_still_requires_authentication():
    executor = FakeExecutor()
    app = create_remediation_app(SafeRemediationAgent(make_policy(), executor), agent_token="test-token")
    with TestClient(app) as client:
        assert client.post("/internal/v1/remediate", json=payload()).status_code == 401
    assert executor.actions == []
