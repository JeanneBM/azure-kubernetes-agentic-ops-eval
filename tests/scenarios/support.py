"""Real orchestrator, policy, ACR client, Foundry client, AKS adapters and watcher,
wired like build_app() does, against an in-memory cluster and mocked HTTP services."""
import json
from copy import deepcopy
from types import SimpleNamespace as NS

import httpx
from kubernetes import client

from agentic_ops import IncidentOrchestrator, SelfCurePolicy
from agentic_ops.acr import AcrRegistry
from agentic_ops.aks import AksActionExecutor, AksDiagnosticProvider
from agentic_ops.foundry import FoundryDiagnosticProvider
from agentic_ops.watcher import PodWatcher
OLD = "acrprod.azurecr.io/paymnets-api:1.4.2"
NEW = "acrprod.azurecr.io/payments-api:1.4.2"




def pod(reason="ImagePullBackOff", image=OLD, owner=True):
    owners = [client.V1OwnerReference(api_version="apps/v1", kind="ReplicaSet", name="payments-api-7d9", uid="u")] if owner else None
    return client.V1Pod(
        metadata=client.V1ObjectMeta(name="payments-api-7d9-x", namespace="payments", owner_references=owners),
        spec=client.V1PodSpec(containers=[client.V1Container(name="api", image=image)]),
        status=client.V1PodStatus(phase="Pending", container_statuses=[client.V1ContainerStatus(
            name="api", image=image, image_id="", ready=False, restart_count=0,
            state=client.V1ContainerState(waiting=client.V1ContainerStateWaiting(reason=reason, message="not found")),
        )]),
    )

def deployment(image=OLD, *, generation=2, observed=2, replicas=1, updated=1, available=1, total=1):
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(generation=generation),
        spec=client.V1DeploymentSpec(
            replicas=replicas, selector=client.V1LabelSelector(),
            template=client.V1PodTemplateSpec(spec=client.V1PodSpec(
                containers=[client.V1Container(name="api", image=image)]))),
        status=client.V1DeploymentStatus(
            observed_generation=observed, replicas=total, updated_replicas=updated, available_replicas=available),
    )

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
        return NS(items=[NS(reason="Failed", message=f"Failed to pull image {OLD}: {self.pod.status.container_statuses[0].state.waiting.message}")])

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
        self.deployment.status.available_replicas = 1

def wire(model_image, registry_has=(NEW,), *, sidecar_first=None):
    cluster = FakeCluster(sidecar_first)

    def foundry(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][1]["content"]
        assert OLD in prompt  # the model saw the cluster evidence
        evidence = json.loads(prompt)["evidence"]
        pull_message = cluster.pod.status.container_statuses[0].state.waiting.message
        assert any(pull_message in item["value"] for item in evidence)
        reply = {"groundedness": 0.95, "summary": "Image name has a typo.",
                 "safe_action": ({"name": "fix_image", "parameters": {"image": model_image}}
                                 if model_image is not None else None)}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    cluster.registry_requests = []

    def acr(request: httpx.Request) -> httpx.Response:
        cluster.registry_requests.append((request.url.path, request.headers.get("authorization")))
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


def assert_correct_recovery(cluster, watcher, results):
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


def assert_safe_escalation(cluster, watcher, results, expected_reason):
    """No attempted patch and no resource mutation, with evidence for review."""
    before = deepcopy(cluster.deployment.to_dict())
    assert watcher.process_pod(cluster.pod)
    assert len(results) == 1
    result = results[0]
    assert result.incident.status.value == "escalated"
    assert not result.action_executed
    assert result.incident.action is None
    assert expected_reason in result.incident.reason
    assert cluster.patches == []
    assert cluster.deployment.to_dict() == before
    assert result.incident.facts.pull_failures[0].image == OLD
    assert result.incident.recommendation is not None
    assert result.incident.recommendation.evidence_sources
