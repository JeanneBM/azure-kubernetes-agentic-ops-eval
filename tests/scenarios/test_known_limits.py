"""K01-K03: real adapters with controlled model/registry/cluster responses."""
import json
from copy import deepcopy

import httpx

from agentic_ops.acr import AcrRegistry, RegistryEvidenceProvider
from agentic_ops.aks import AksActionExecutor, AksDiagnosticProvider
from agentic_ops.foundry import FoundryDiagnosticProvider
from agentic_ops.orchestrator import IncidentOrchestrator
from agentic_ops.safety import SelfCurePolicy
from conftest import make_trigger
from .support import FakeCluster, _acr_handler


def run_case(old, existing, proposed):
    cluster = FakeCluster()
    cluster.deployment.spec.template.spec.containers[0].image = old
    cluster.pod.spec.containers[0].image = old
    cluster.pod.status.container_statuses[0].image = old
    before = deepcopy(cluster.deployment.to_dict())
    model_calls = []
    registry_calls = []

    class Credential:
        def get_token(self, scope):
            return type("Token", (), {"token": "offline"})()

    def model(request):
        model_calls.append(json.loads(request.content))
        reply = {"groundedness": 0.95, "summary": "Controlled proposal",
                 "safe_action": {"name": "fix_image", "parameters": {"image": proposed}}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    with httpx.Client(transport=httpx.MockTransport(_acr_handler(existing, registry_calls))) as acr_http, \
         httpx.Client(transport=httpx.MockTransport(model)) as model_http:
        registry = AcrRegistry(credential=Credential(), http_client=acr_http)
        diagnostics = FoundryDiagnosticProvider(
            RegistryEvidenceProvider(AksDiagnosticProvider(cluster, cluster), registry,
                                     namespace="test-app", allowed_registries=["acrprod.azurecr.io"]),
            endpoint="https://offline.invalid", deployment="fixture",
            token_provider=lambda: "offline", http_client=model_http)
        orchestrator = IncidentOrchestrator(
            diagnostics, AksActionExecutor(cluster, verify_timeout=1, poll_interval=0),
            SelfCurePolicy(registry, namespace="test-app", allowed_registries=["acrprod.azurecr.io"]))
        result = orchestrator.handle(make_trigger())
    return cluster, before, result, model_calls


def assert_abstained(case):
    cluster, before, result, _ = case
    assert result.incident.status.value == "escalated"
    assert result.action_executed is False
    assert cluster.patches == []
    assert cluster.deployment.to_dict() == before


def test_K01_ambiguous_existing_repositories_abstain_before_model():
    case = run_case("acrprod.azurecr.io/orders-api:1.4.2",
                    {"acrprod.azurecr.io/orders-apj:1.4.2",
                     "acrprod.azurecr.io/orders-apk:1.4.2"},
                    "acrprod.azurecr.io/orders-apj:1.4.2")
    assert_abstained(case)
    assert case[3] == []


def test_K02_unique_similar_repository_is_another_service():
    # Independent ground truth: orders-api is intended; orders-apt is another service.
    # Registry evidence has no trusted mapping establishing that relationship.
    case = run_case("acrprod.azurecr.io/orders-api:1.4.2",
                    {"acrprod.azurecr.io/orders-apt:1.4.2"},
                    "acrprod.azurecr.io/orders-apt:1.4.2")
    assert_abstained(case)


def test_K03_missing_release_does_not_fall_back_to_nearby_version():
    case = run_case("acrprod.azurecr.io/orders-api:1.4.3",
                    {"acrprod.azurecr.io/orders-api:1.4.2"},
                    "acrprod.azurecr.io/orders-api:1.4.2")
    assert_abstained(case)
    assert case[3] == []
