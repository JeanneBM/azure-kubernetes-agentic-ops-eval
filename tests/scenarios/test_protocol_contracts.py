"""P01-P08: explicit protocol checks; never call Azure."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agentic_ops.agents import SafeRemediationAgent
from agentic_ops.foundry import FoundryDiagnosticProvider
from agentic_ops.orchestrator import IncidentOrchestrator
from agentic_ops.remote import FactsPayload, create_remediation_app
from conftest import (NEW, OLD, FakeDiagnostics, FakeExecutor, FakeRegistry,
                      make_facts, make_policy, make_trigger)


def assert_refused(facts, reason, registry=None):
    executor = FakeExecutor()
    result = IncidentOrchestrator(FakeDiagnostics(facts), executor,
                                  make_policy(registry)).handle(make_trigger())
    assert result.incident.status.value == "escalated"
    assert result.action_executed is False
    assert reason in result.incident.reason
    assert executor.actions == []


@pytest.mark.parametrize("extra", ["namespace", "container", "deployment"])
def test_P01_extra_target_parameter_is_rejected(extra):
    assert_refused(make_facts(params={"image": NEW, extra: "unauthorized"}),
                   "exactly one parameter")


def test_P02_foreign_registry_is_rejected_even_when_image_exists():
    image = "foreign.azurecr.io/test-app:1.4.2"
    assert_refused(make_facts(image), "same registry", FakeRegistry({image}))


def test_P03_nonexistent_proposal_is_rejected():
    assert_refused(make_facts(), "not found", FakeRegistry())


@pytest.mark.parametrize("image,reason", [
    ("acrprod.azurecr.io/unrelated-service:1.4.2", "too different"),
    ("acrprod.azurecr.io/test-app:9.9.9", "keep the current tag"),
])
def test_P04_distant_repository_or_changed_tag_is_rejected(image, reason):
    assert_refused(make_facts(image), reason, FakeRegistry({image}))


@pytest.mark.parametrize("content", [
    "{not json",
    json.dumps({"groundedness": 0.99, "safe_action":
                {"name": "delete_namespace", "parameters": {"namespace": "test-app"}}}),
])
def test_P05_model_parser_failure_escalates_without_execution(content):
    class ParserDiagnostics:
        def collect(self, trigger):
            return FoundryDiagnosticProvider._parse_facts(content, make_facts(None))

    executor = FakeExecutor()
    result = IncidentOrchestrator(ParserDiagnostics(), executor, make_policy()).handle(make_trigger())
    assert result.incident.status.value == "escalated"
    assert "facts contract" in result.incident.reason
    assert result.action_executed is False
    assert executor.actions == []


@pytest.mark.parametrize("stage", ["current", "proposed"])
@pytest.mark.parametrize("kind", ["auth", "timeout"])
def test_P06_registry_failure_at_either_check_never_executes(stage, kind):
    error = (httpx.HTTPStatusError("401 registry authentication failed",
             request=httpx.Request("HEAD", "https://offline.invalid"),
             response=httpx.Response(401)) if kind == "auth" else
             httpx.ReadTimeout("registry timeout"))

    class Registry:
        def __init__(self):
            self.calls = []
        def exists(self, image):
            self.calls.append(str(image))
            if stage == "current" or str(image) == NEW:
                raise error
            return False

    registry = Registry()
    assert_refused(make_facts(), type(error).__name__, registry)
    assert registry.calls == ([OLD] if stage == "current" else [OLD, NEW])


@pytest.mark.parametrize("token", [None, "wrong"])
def test_P07_internal_handoff_requires_valid_token(token):
    executor = FakeExecutor()
    app = create_remediation_app(SafeRemediationAgent(make_policy(), executor),
                                 agent_token="fixture-token")
    payload = {**make_trigger().__dict__, "facts": FactsPayload.from_facts(make_facts()).model_dump()}
    payload.pop("failure_fingerprint")
    with TestClient(app) as http:
        response = http.post("/internal/v1/remediate", json=payload,
                             headers={"X-Agent-Token": token} if token else {})
    assert response.status_code == 401
    assert executor.actions == []


def test_P08_failed_rollout_reports_mutation_and_escalates():
    executor = FakeExecutor(healthy=False)
    result = IncidentOrchestrator(FakeDiagnostics(make_facts()), executor,
                                  make_policy()).handle(make_trigger())
    assert result.incident.status.value == "escalated"
    assert result.action_executed is True
    assert len(executor.actions) == 1
    assert result.incident.action == executor.actions[0]
