import threading
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from kubernetes import client as k8s

from agentic_ops import IncidentOrchestrator
from agentic_ops.aks import resolve_pod_workload
from agentic_ops.contracts import TriggerContextError, TriggerOwnershipChanged, TriggerTargetGone
from agentic_ops.watcher import PodWatcher
from agentic_ops.web import create_app
from conftest import FakeDiagnostics, FakeExecutor, make_facts, make_policy
from test_aks import pod

TOKEN = "s3cret"
AUTH = {"X-Webhook-Token": TOKEN}
PAYLOAD = {"namespace": "test-app", "pod": "test-app-abc-1", "workload": "test-app",
           "reason": "ImagePullBackOff", "correlation_id": "INC-4821"}


class Env:
    """Holds the collaborators so tests can assert on them."""

    def __init__(self, owner="test-app", token=TOKEN):
        self.owner = owner
        self.resolver_calls = []
        self.executor = FakeExecutor()
        self.orchestrator = IncidentOrchestrator(FakeDiagnostics(make_facts()), self.executor, make_policy())
        self.app = create_app(self.orchestrator, resolve_workload=self._resolve, webhook_token=token)

    def _resolve(self, namespace, pod_name):
        self.resolver_calls.append((namespace, pod_name))
        if isinstance(self.owner, Exception):
            raise self.owner
        return self.owner


@pytest.fixture
def env():
    return Env()


@pytest.fixture
def http(env):
    # One shared portal/event loop for the whole test instead of one per request.
    with TestClient(env.app) as client:
        yield client


def test_webhook_fixes_typo_and_reports_action(http, env):
    body = http.post("/api/v1/incidents", json=PAYLOAD, headers=AUTH).json()
    assert body["status"] == "resolved" and body["action_executed"]
    assert body["action"]["parameters"]["new_image"].endswith("test-app:1.4.2")
    assert env.resolver_calls == [("test-app", "test-app-abc-1")]


def test_webhook_is_disabled_without_a_configured_token():
    with TestClient(Env(token=None).app) as http:
        assert http.post("/api/v1/incidents", json=PAYLOAD).status_code == 503
        assert http.post("/api/v1/incidents", json=PAYLOAD, headers=AUTH).status_code == 503


def test_token_is_required_and_checked_before_the_body(http, env):
    assert http.post("/api/v1/incidents", json=PAYLOAD).status_code == 401
    assert http.post("/api/v1/incidents", json=PAYLOAD, headers={"X-Webhook-Token": "wrong"}).status_code == 401
    # an unauthenticated caller must not learn anything from validation errors
    assert http.post("/api/v1/incidents", json={"bad": 1}).status_code == 401
    assert env.resolver_calls == [] and env.executor.actions == []


def test_payload_validation_after_authentication(http):
    assert http.post("/api/v1/incidents", json={**PAYLOAD, "pod": ""}, headers=AUTH).status_code == 422


def test_unmanaged_namespace_is_rejected_without_touching_the_cluster(http, env):
    response = http.post("/api/v1/incidents", json={**PAYLOAD, "namespace": "kube-system"}, headers=AUTH)
    assert response.status_code == 403
    assert env.resolver_calls == []


def test_workload_that_does_not_match_the_pod_owner_is_rejected(http, env):
    response = http.post("/api/v1/incidents", json={**PAYLOAD, "workload": "billing"}, headers=AUTH)
    assert response.status_code == 409
    assert "test-app" in response.json()["detail"]
    assert env.executor.actions == []


def test_unknown_or_unowned_pod_is_rejected(http, env):
    env.owner = None
    response = http.post("/api/v1/incidents", json=PAYLOAD, headers=AUTH)
    assert response.status_code == 422
    assert env.executor.actions == []


def test_ownership_lookup_failure_is_a_502_and_never_acts(http, env):
    env.owner = RuntimeError("apiserver down")
    assert http.post("/api/v1/incidents", json=PAYLOAD, headers=AUTH).status_code == 502
    assert env.executor.actions == []


def test_healthz_needs_no_token(http):
    assert http.get("/healthz").json() == {"status": "ok"}


def test_lifespan_starts_the_watcher_and_signals_it_to_stop():
    started, stopped = threading.Event(), threading.Event()

    class FakeWatcher:
        def run(self, stop):
            started.set()
            stop.wait(5)
            stopped.set()

    env = Env()
    app = create_app(env.orchestrator, resolve_workload=env._resolve, webhook_token=TOKEN, watcher=FakeWatcher())
    with TestClient(app):
        assert started.wait(5)
        assert not stopped.is_set()
    assert stopped.wait(5)


def test_resolve_pod_workload_maps_missing_pod_to_none_and_other_errors_raise():
    core, apps = MagicMock(), MagicMock()
    core.read_namespaced_pod.side_effect = k8s.exceptions.ApiException(status=404)
    assert resolve_pod_workload(core, apps, "test-app", "gone") is None
    core.read_namespaced_pod.side_effect = k8s.exceptions.ApiException(status=500)
    with pytest.raises(k8s.exceptions.ApiException):
        resolve_pod_workload(core, apps, "test-app", "x")
    core.read_namespaced_pod.side_effect = None
    core.read_namespaced_pod.return_value = pod(owner=False)
    assert resolve_pod_workload(core, apps, "test-app", "x") is None


def test_watcher_raises_incident_for_pull_failures_only():
    apps = MagicMock()
    parent = MagicMock(kind="Deployment")
    parent.name = "test-app"
    apps.read_namespaced_replica_set.return_value = MagicMock(metadata=MagicMock(owner_references=[parent]))
    handled = []
    watcher = PodWatcher(MagicMock(), apps, "test-app", handled.append)
    assert watcher.process_pod(pod()) is True
    assert handled[0].workload == "test-app" and handled[0].namespace == "test-app"
    assert watcher.process_pod(pod(reason="CrashLoopBackOff")) is False
    assert len(handled) == 1


def test_watcher_handles_two_rollouts_without_restarting_orchestrator():
    from agentic_ops.aks import resolve_incident_trigger
    from test_aks import incident_context

    core, apps = incident_context()
    diagnostics, executor = FakeDiagnostics(make_facts()), FakeExecutor()
    orchestrator = IncidentOrchestrator(
        diagnostics, executor, make_policy(),
        resolve_trigger=lambda trigger: resolve_incident_trigger(core, apps, trigger),
    )
    watcher = PodWatcher(core, apps, "test-app", orchestrator.handle)
    failing_pod = core.read_namespaced_pod.return_value
    assert watcher.process_pod(failing_pod)
    assert watcher.process_pod(failing_pod)
    assert diagnostics.calls == len(executor.actions) == 1
    apps.read_namespaced_replica_set.return_value.metadata.annotations["deployment.kubernetes.io/revision"] = "3"
    assert watcher.process_pod(failing_pod)
    assert diagnostics.calls == len(executor.actions) == 2


def test_webhook_uses_cluster_context_for_each_alert():
    from dataclasses import replace

    revision = ["1"]
    diagnostics, executor = FakeDiagnostics(make_facts()), FakeExecutor()
    orchestrator = IncidentOrchestrator(
        diagnostics, executor, make_policy(),
        resolve_trigger=lambda trigger: replace(trigger, failure_fingerprint=revision[0]),
    )
    app = create_app(orchestrator, resolve_workload=lambda ns, pod: "test-app", webhook_token=TOKEN)
    with TestClient(app) as http:
        assert not http.post("/api/v1/incidents", json=PAYLOAD, headers=AUTH).json()["deduplicated"]
        assert http.post("/api/v1/incidents", json=PAYLOAD, headers=AUTH).json()["deduplicated"]
        revision[0] = "3"
        assert not http.post("/api/v1/incidents", json=PAYLOAD, headers=AUTH).json()["deduplicated"]
    assert diagnostics.calls == len(executor.actions) == 2


@pytest.mark.parametrize("error, status", [
    (TriggerTargetGone("pod test-app/test-app-abc-1 no longer exists"), 422),
    (TriggerOwnershipChanged("Pod is no longer owned by the requested Deployment"), 409),
    (TriggerContextError("could not read pod test-app/test-app-abc-1: HTTP 503"), 502),
    (RuntimeError("connection reset"), 502),
])
def test_webhook_maps_context_lookup_failures_without_running_anything(error, status):
    def lookup(trigger):
        raise error

    diagnostics, executor = FakeDiagnostics(make_facts()), FakeExecutor()
    orchestrator = IncidentOrchestrator(diagnostics, executor, make_policy(), resolve_trigger=lookup)
    app = create_app(orchestrator, resolve_workload=lambda ns, pod: "test-app", webhook_token=TOKEN)
    with TestClient(app, raise_server_exceptions=False) as http:
        response = http.post("/api/v1/incidents", json=PAYLOAD, headers=AUTH)
    assert response.status_code == status
    assert diagnostics.calls == 0
    assert executor.actions == []


@pytest.mark.parametrize("error", [
    TriggerTargetGone("pod test-app/test-app-7d9-x no longer exists"),
    TriggerOwnershipChanged("Pod is no longer owned by the requested Deployment"),
])
def test_watcher_skips_pods_whose_context_is_gone(error):
    from test_aks import incident_context

    core, apps = incident_context()

    def handle(trigger):
        raise error

    watcher = PodWatcher(core, apps, "test-app", handle)
    assert watcher.process_pod(core.read_namespaced_pod.return_value) is False


def test_watcher_propagates_other_context_errors_to_its_event_handler():
    from test_aks import incident_context

    core, apps = incident_context()

    def handle(trigger):
        raise TriggerContextError("could not read pod: HTTP 503")

    watcher = PodWatcher(core, apps, "test-app", handle)
    with pytest.raises(TriggerContextError):
        watcher.process_pod(core.read_namespaced_pod.return_value)
