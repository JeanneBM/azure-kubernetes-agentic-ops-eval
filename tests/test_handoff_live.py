import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agentic_ops.remote import HttpRemediationAgent
from conftest import make_facts, make_trigger


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / f"eval/handoff/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trial = load("trial")
host = load("run")


@pytest.mark.parametrize("mode,expected", [("delayed", True), ("lost-ack", None)])
def test_real_loopback_proxy_propagates_or_drops_confirmed_ack_once(mode, expected):
    forwarded, delays = [], []

    def upstream(request):
        forwarded.append(request)
        assert request.headers["X-Agent-Token"] == "upstream-secret"
        return httpx.Response(200, json={"executed": True, "successful": True})

    backend = httpx.Client(transport=httpx.MockTransport(upstream))
    with trial.HandoffProxy("http://upstream", "upstream-secret", mode, 180,
                            client=backend, sleep=delays.append, clock=lambda: 0) as proxy:
        client = httpx.Client(trust_env=False)
        try:
            result = HttpRemediationAgent(proxy.url, "local", "test-app", http_client=client).remediate(
                make_trigger(), make_facts())
        finally:
            client.close()
        assert proxy.done.wait(2)
        assert result.executed is expected
        assert result.successful is (mode == "delayed")
        assert len(forwarded) == proxy.requests == len(proxy.confirmed) == 1
        assert proxy.errors == []
        assert delays == ([100] if mode == "delayed" else [])


def test_unconfirmed_upstream_is_not_presented_as_successful_fault_injection():
    backend = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"executed": False, "successful": False})))
    with trial.HandoffProxy("http://upstream", "secret", "lost-ack", 180, client=backend) as proxy:
        with httpx.Client(trust_env=False) as client:
            outcome = HttpRemediationAgent(proxy.url, "local", "test-app", http_client=client).remediate(
                make_trigger(), make_facts())
        assert proxy.done.wait(2)
        assert outcome.executed is None
        assert not proxy.confirmed
        assert proxy.errors


@pytest.mark.parametrize("mode,status,executed,elapsed,expected", [
    ("delayed", "resolved", True, 100.1, "pass"),
    ("delayed", "resolved", True, 89.9, "fail"),
    ("delayed", "escalated", None, 180, "fail"),
    ("lost-ack", "escalated", None, 2, "pass"),
    ("lost-ack", "escalated", False, 2, "fail"),
])
def test_trial_verdict_requires_the_exact_contract(mode, status, executed, elapsed, expected):
    result = SimpleNamespace(incident=SimpleNamespace(status=SimpleNamespace(value=status)), action_executed=executed)
    assert trial.verdict(mode, result, elapsed, 1, True, True, True, []) == expected
    assert trial.verdict(mode, result, elapsed, 1, False, True, True, []) == "inconclusive"
    assert trial.verdict(mode, result, elapsed, 2, True, True, True, []) == "fail"


def test_only_image_change_and_exactly_one_generation_are_allowed():
    before = {"metadata": {"generation": 2}, "spec": {"replicas": 2, "template": {
        "spec": {"containers": [{"name": "api", "image": "bad"}]}}}}
    after = copy.deepcopy(before)
    after["metadata"]["generation"] = 3
    after["spec"]["template"]["spec"]["containers"][0]["image"] = "good"
    assert trial.image_only_change(before, after, "good")
    after["spec"]["replicas"] = 3
    assert not trial.image_only_change(before, after, "good")


def test_report_serializes_sdk_dates_without_coercing_null_or_unknown_types():
    from datetime import datetime, timezone
    from kubernetes import client

    timestamp = datetime(2026, 10, 22, 14, 40, 32, tzinfo=timezone.utc)
    snapshot = client.V1Deployment(metadata=client.V1ObjectMeta(
        creation_timestamp=timestamp, managed_fields=[client.V1ManagedFieldsEntry(time=timestamp)],
    )).to_dict()
    report = json.loads(trial.encode_report({"before": snapshot, "action_executed": None}))
    assert report["before"]["metadata"]["creation_timestamp"] == timestamp.isoformat()
    assert report["before"]["metadata"]["managed_fields"][0]["time"] == timestamp.isoformat()
    assert report["action_executed"] is None
    with pytest.raises(TypeError, match="Unsupported report value"):
        trial.encode_report({"unsupported": object()})


@pytest.mark.parametrize("mode", ["delayed", "lost-ack"])
def test_in_pod_main_emits_terminal_result_with_sdk_dates(mode, monkeypatch, capsys):
    import threading
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from kubernetes import client, config
    from agentic_ops import aks, remote
    from agentic_ops.agents import RemediationOutcome
    from test_aks import deployment, pod

    before = deployment(generation=2)
    after = deployment(image="acrprod.azurecr.io/test-app:1.4.2", generation=3, observed=3)
    for item in (before, after):
        item.metadata.creation_timestamp = datetime(2026, 10, 22, tzinfo=timezone.utc)
    core, apps = MagicMock(), MagicMock()
    core.read_namespaced_pod.return_value = pod()
    apps.read_namespaced_deployment.side_effect = [before, after]
    monkeypatch.setattr(client, "CoreV1Api", lambda: core)
    monkeypatch.setattr(client, "AppsV1Api", lambda: apps)
    monkeypatch.setattr(config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(aks, "workload_of", lambda apps, pod: "test-app")
    monkeypatch.setattr(aks, "AksDiagnosticProvider", lambda *args: SimpleNamespace(collect=lambda trigger: make_facts()))

    class Proxy:
        url = "http://localhost"
        requests, confirmed, errors = 1, [{"executed": True, "successful": True}], []
        done = threading.Event()

        def __init__(self, *args):
            self.done.set()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(trial, "HandoffProxy", Proxy)
    monkeypatch.setattr(remote, "HttpRemediationAgent", lambda *a, **kw: SimpleNamespace(
        manages=lambda ns: True,
        remediate=lambda trigger, facts: RemediationOutcome(
            None, True if mode == "delayed" else None, mode == "delayed", "controlled result"),
    ))
    clock = iter([0, 100.1])
    monkeypatch.setattr(trial, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    for key, value in {
        "EVAL_HANDOFF_MODE": mode, "AGENTIC_OPS_NAMESPACE": "test-app",
        "EVAL_GOOD_IMAGE": "acrprod.azurecr.io/test-app:1.4.2",
        "EVAL_BAD_IMAGE": "acrprod.azurecr.io/tset-app:1.4.2",
        "EVAL_CORRELATION_ID": "regression", "EVAL_FAILURE_POD": "failed-pod",
        "AGENTIC_OPS_REMEDIATION_URL": "http://remediation", "AGENTIC_OPS_REMEDIATION_TOKEN": "test-token",
    }.items():
        monkeypatch.setenv(key, value)
    assert trial.main() == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["event"] == "handoff_trial_result"
    assert report["verdict"] == "pass"
    assert report["before"]["metadata"]["creation_timestamp"] == "2026-10-22T00:00:00+00:00"
    assert report["action_executed"] is (True if mode == "delayed" else None)


def test_evaluator_retains_identity_and_network_policy_labels_without_mutating_template():
    template = {"spec": {"template": {"spec": {"serviceAccountName": "agentic-ops-diagnostic",
        "containers": [{"name": "agent", "image": "old", "envFrom": [{"configMapRef": {"name": "timeouts"}}],
                        "readinessProbe": {"httpGet": {}}, "env": []}]}}}}
    original = copy.deepcopy(template)
    pod = host.runner_manifest(template, "repo@sha256:abc", "print(1)", "runner", {"EVAL_HANDOFF_MODE": "delayed"})
    assert template == original
    assert pod["metadata"]["labels"]["role"] == "diagnostic"
    assert pod["spec"]["serviceAccountName"] == "agentic-ops-diagnostic"
    assert pod["spec"]["containers"][0]["envFrom"]
    assert "readinessProbe" not in pod["spec"]["containers"][0]
    assert pod["spec"]["restartPolicy"] == "Never"


def test_host_restores_baseline_and_replica_count_after_injection_failure(tmp_path, monkeypatch):
    root = tmp_path
    (root / "eval/handoff").mkdir(parents=True)
    (root / "eval/handoff/trial.py").write_text("print(1)")
    (root / ".local").mkdir()
    state = {"resourceGroup": "rg-agentic-ops-lab", "kubeconfig": "lab.yaml", "aksName": "lab",
             "subscriptionId": "sub", "demoImage": "acr/test-app:1.4.2", "agentImage": "acr/agent:tag"}
    (root / ".local/rg-agentic-ops-lab.json").write_text(json.dumps(state))
    monkeypatch.setattr(host, "__file__", str(root / "eval/handoff/run.py"))
    monkeypatch.setattr(host.shutil, "which", lambda name: name)
    monkeypatch.setattr(host, "command", lambda args, **kw: json.dumps({"fqdn": "lab.example"}) if args[0] == "az" else "commit")
    monkeypatch.setattr("sys.argv", ["run.py"])
    calls = []

    class FakeLab:
        def __init__(self, state, evidence):
            self.evidence = evidence

        def save(self, name, value):
            (self.evidence / name).write_text(json.dumps(value))

        def get(self, kind, name=None, namespace=None, label=None):
            if kind == "pods":
                return {"items": [{"metadata": {}, "status": {"containerStatuses": [
                    {"ready": True, "imageID": "acr/agent@sha256:" + "a" * 64}]}}]}
            image = state["demoImage"] if name == "test-app" else "acr/agent:tag"
            return {"spec": {"replicas": 1, "template": {"spec": {"containers": [{"name": "api", "image": image}]}}}}

        def kube(self, *args):
            calls.append(args)
            return "https://lab.example" if args[0] == "config" else ""

        def rollout(self, *args):
            calls.append(("rollout", *args))

        def set_image(self, image):
            calls.append(("image", image))
            if "/tset-app:" in image:
                raise RuntimeError("injection failed")

    monkeypatch.setattr(host, "Lab", FakeLab)
    assert host.main() == 1
    assert ("image", state["demoImage"]) in calls
    assert ("scale", "deployment/agentic-ops-diagnostic", "-n", "agentic-ops", "--replicas=1") in calls
    summary = json.loads(next(root.glob(".local/evidence/handoff/*/summary.json")).read_text())
    assert summary["errors"] and summary["cleanup_errors"] == []
