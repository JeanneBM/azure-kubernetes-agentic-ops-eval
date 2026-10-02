"""Real orchestrator, policy, ACR client, Foundry client, AKS adapters and watcher,
wired like build_app() does, against an in-memory cluster and mocked HTTP services."""
import json
from copy import deepcopy
from types import SimpleNamespace as NS

import httpx
import pytest
from kubernetes import client

from agentic_ops import IncidentOrchestrator, SelfCurePolicy
from agentic_ops.acr import AcrRegistry
from agentic_ops.aks import AksActionExecutor, AksDiagnosticProvider
from agentic_ops.foundry import FoundryDiagnosticProvider
from agentic_ops.watcher import PodWatcher
from conftest import NEW, OLD
from test_aks import deployment, pod


class FakeCluster:
    """Minimal Core/Apps API: patching the image 'rolls out' a healthy deployment."""

    def __init__(self, sidecar_first=None):
        self.deployment = deployment(OLD, generation=1, observed=1, available=0)
        self.pod = pod()
        self.deployment.spec.template.metadata = client.V1ObjectMeta(
            labels={"app": "payments-api"}, annotations={"eval": "preserve"})
        self.deployment.spec.template.spec.containers[0].env = [
            client.V1EnvVar(name="MODE", value="evaluation")]
        self.deployment.spec.template.spec.containers[0].resources = client.V1ResourceRequirements(
            requests={"cpu": "10m", "memory": "16Mi"})
        if sidecar_first is not None:
            sidecar = client.V1Container(name="metrics", image="acrprod.azurecr.io/metrics:1.0.0",
                args=["--port=9090"], env=[client.V1EnvVar(name="KEEP", value="yes")])
            for containers in (self.deployment.spec.template.spec.containers, self.pod.spec.containers):
                containers.insert(0 if sidecar_first else len(containers), deepcopy(sidecar))
            self.pod.status.container_statuses.append(client.V1ContainerStatus(
                name="metrics", image=sidecar.image, image_id="fixture://metrics", ready=True,
                restart_count=0, state=client.V1ContainerState(running=client.V1ContainerStateRunning())))
        self.patches = []

    def read_namespaced_pod(self, name, namespace):
        return self.pod

    def list_namespaced_event(self, namespace, field_selector=None):
        return NS(items=[NS(reason="Failed", message=f"manifest for {OLD} not found")])

    def read_namespaced_replica_set(self, name, namespace):
        return client.V1ReplicaSet(metadata=client.V1ObjectMeta(owner_references=[
            client.V1OwnerReference(api_version="apps/v1", kind="Deployment", name="payments-api", uid="d")]))

    def read_namespaced_deployment(self, name, namespace):
        return self.deployment

    def patch_namespaced_deployment(self, name, namespace, body):
        self.patches.append((name, namespace, body))
        # Model the named-container strategic merge, retaining unrelated fields.
        for change in body["spec"]["template"]["spec"]["containers"]:
            target = next(c for c in self.deployment.spec.template.spec.containers if c.name == change["name"])
            target.image = change["image"]
        self.deployment.metadata.generation += 1
        self.deployment.status.observed_generation = self.deployment.metadata.generation
        self.deployment.status.available_replicas = 1  # simulated rollout completes


def wire(model_image, registry_has=(NEW,), *, sidecar_first=None):
    cluster = FakeCluster(sidecar_first)

    def foundry(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][1]["content"]
        assert OLD in prompt  # the model saw the cluster evidence
        reply = {"groundedness": 0.95, "summary": "Image name has a typo.",
                 "safe_action": {"name": "fix_image", "parameters": {"image": model_image}}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    def acr(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/exchange":
            return httpx.Response(200, json={"refresh_token": "rt"})
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "at"})
        ref = request.url.path.removeprefix("/v2/").replace("/manifests/", ":")
        return httpx.Response(200 if f"acrprod.azurecr.io/{ref}" in registry_has else 404)

    class Cred:
        def get_token(self, scope):
            return NS(token="aad")

    diagnostics = FoundryDiagnosticProvider(
        AksDiagnosticProvider(cluster, cluster), endpoint="https://f.openai.azure.com", deployment="gpt",
        http_client=httpx.Client(transport=httpx.MockTransport(foundry)), token_provider=lambda: "t",
    )
    policy = SelfCurePolicy(
        AcrRegistry(credential=Cred(), http_client=httpx.Client(transport=httpx.MockTransport(acr))),
        namespace="payments", allowed_registries=["acrprod.azurecr.io"],
    )
    executor = AksActionExecutor(cluster, verify_timeout=5, poll_interval=0, sleep=lambda s: None)
    results = []
    orchestrator = IncidentOrchestrator(diagnostics, executor, policy)
    watcher = PodWatcher(cluster, cluster, "payments", lambda t: results.append(orchestrator.handle(t)))
    return cluster, watcher, results


def test_typo_in_image_name_is_fixed_automatically():
    cluster, watcher, results = wire(NEW)
    assert watcher.process_pod(pod())
    result = results[0]
    assert result.incident.status.value == "resolved" and result.action_executed
    assert cluster.deployment.spec.template.spec.containers[0].image == NEW
    assert len(cluster.patches) == 1


@pytest.mark.parametrize("repetition", range(1, 6))
@pytest.mark.parametrize("sidecar_first", [None, False, True], ids=["S01", "S02-api-first", "S02-sidecar-first"])
def test_s01_s02_recovery_preserves_every_unrelated_spec_field(repetition, sidecar_first):
    """Five fresh mock trials; these are not live AKS or real-model measurements."""
    cluster, watcher, results = wire(NEW, sidecar_first=sidecar_first)
    before = deepcopy(cluster.deployment.spec.to_dict())
    expected = deepcopy(before)
    next(c for c in expected["template"]["spec"]["containers"] if c["name"] == "api")["image"] = NEW

    assert watcher.process_pod(cluster.pod)
    assert len(results) == 1
    assert results[0].incident.status.value == "resolved"
    assert results[0].action_executed
    assert cluster.patches == [("payments-api", "payments", {
        "spec": {"template": {"spec": {"containers": [{"name": "api", "image": NEW}]}}}})]
    assert cluster.deployment.spec.to_dict() == expected
    assert AksActionExecutor._rolled_out(cluster.deployment, "api", NEW)


def test_hallucinated_image_is_not_applied():
    cluster, watcher, results = wire("acrprod.azurecr.io/payments-api:1.4.3")  # plausible, but this tag does not exist
    watcher.process_pod(pod())
    assert results[0].incident.status.value == "escalated"
    assert "not found" in results[0].incident.reason
    assert cluster.patches == []


def test_image_that_exists_but_fails_to_pull_is_not_touched():
    cluster, watcher, results = wire(NEW, registry_has=(OLD, NEW))  # e.g. missing AcrPull on kubelet
    watcher.process_pod(pod())
    assert results[0].incident.status.value == "escalated"
    assert cluster.patches == []
