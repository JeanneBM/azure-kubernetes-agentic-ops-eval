from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from kubernetes import client

from agentic_ops import ActionRequest
from agentic_ops.contracts import TriggerContextError, TriggerOwnershipChanged, TriggerTargetGone
from agentic_ops.aks import (
    AksActionExecutor, AksDiagnosticProvider, find_pull_failures, workload_of,
    resolve_incident_trigger,
)
from conftest import NEW, OLD, make_trigger


def pod(reason="ImagePullBackOff", image=OLD, owner=True):
    owners = [client.V1OwnerReference(api_version="apps/v1", kind="ReplicaSet", name="test-app-7d9", uid="u")] if owner else None
    return client.V1Pod(
        metadata=client.V1ObjectMeta(name="test-app-7d9-x", namespace="test-app", owner_references=owners),
        spec=client.V1PodSpec(containers=[client.V1Container(name="api", image=image)]),
        status=client.V1PodStatus(phase="Pending", container_statuses=[client.V1ContainerStatus(
            name="api", image=image, image_id="", ready=False, restart_count=0,
            state=client.V1ContainerState(waiting=client.V1ContainerStateWaiting(reason=reason, message="not found")),
        )]),
    )


def test_pull_failure_detected_from_cluster_state():
    failures = find_pull_failures(pod())
    assert [(f.container, f.image) for f in failures] == [("api", OLD)]
    assert find_pull_failures(pod(reason="CrashLoopBackOff")) == ()


def incident_context():
    core, apps = MagicMock(), MagicMock()
    core.read_namespaced_pod.return_value = pod()
    apps.read_namespaced_replica_set.return_value = client.V1ReplicaSet(
        metadata=client.V1ObjectMeta(
            uid="replicaset-uid", annotations={"deployment.kubernetes.io/revision": "1"},
            owner_references=[client.V1OwnerReference(
                api_version="apps/v1", kind="Deployment", name="test-app", uid="deployment-uid",
            )],
        ),
    )
    return core, apps


def test_failure_identity_ignores_pod_name_and_uses_live_image():
    from dataclasses import replace
    core, apps = incident_context()
    first = resolve_incident_trigger(core, apps, make_trigger())
    core.read_namespaced_pod.return_value.metadata.name = "another-replica"
    second = resolve_incident_trigger(core, apps, replace(make_trigger(), pod="another-replica"))
    assert first.failure_fingerprint == second.failure_fingerprint
    core.read_namespaced_pod.return_value.spec.containers[0].image = "acrprod.azurecr.io/different:2"
    assert resolve_incident_trigger(core, apps, make_trigger()).failure_fingerprint != first.failure_fingerprint


def test_old_pod_notifications_stay_duplicates_but_reused_rollout_is_new():
    core, apps = incident_context()
    first = resolve_incident_trigger(core, apps, make_trigger())
    # A patch to the Deployment must not give lingering old pods a new identity.
    apps.read_namespaced_deployment.return_value = deployment(NEW, generation=2)
    assert resolve_incident_trigger(core, apps, make_trigger()).failure_fingerprint == first.failure_fingerprint
    apps.read_namespaced_deployment.assert_not_called()
    # Reintroducing the same bad image can reuse the ReplicaSet and template hash.
    apps.read_namespaced_replica_set.return_value.metadata.annotations["deployment.kubernetes.io/revision"] = "3"
    assert resolve_incident_trigger(core, apps, make_trigger()).failure_fingerprint != first.failure_fingerprint


def test_failure_identity_changes_when_deployment_is_recreated():
    core, apps = incident_context()
    first = resolve_incident_trigger(core, apps, make_trigger())
    apps.read_namespaced_replica_set.return_value.metadata.owner_references[0].uid = "new-deployment-uid"
    assert resolve_incident_trigger(core, apps, make_trigger()).failure_fingerprint != first.failure_fingerprint


def test_failure_identity_refuses_changed_ownership():
    core, apps = incident_context()
    apps.read_namespaced_replica_set.return_value.metadata.owner_references[0].name = "other"
    with pytest.raises(TriggerOwnershipChanged, match="no longer owned"):
        resolve_incident_trigger(core, apps, make_trigger())


@pytest.mark.parametrize("api", ["core", "apps"])
def test_vanished_pod_or_replicaset_is_a_typed_target_gone(api):
    core, apps = incident_context()
    read = core.read_namespaced_pod if api == "core" else apps.read_namespaced_replica_set
    read.side_effect = client.exceptions.ApiException(status=404)
    with pytest.raises(TriggerTargetGone, match="no longer exists"):
        resolve_incident_trigger(core, apps, make_trigger())


def test_other_api_failures_are_a_typed_context_error():
    core, apps = incident_context()
    core.read_namespaced_pod.side_effect = client.exceptions.ApiException(status=503)
    with pytest.raises(TriggerContextError, match="HTTP 503") as raised:
        resolve_incident_trigger(core, apps, make_trigger())
    assert not isinstance(raised.value, (TriggerTargetGone, TriggerOwnershipChanged))


def test_workload_resolved_through_replicaset():
    apps = MagicMock()
    apps.read_namespaced_replica_set.return_value = client.V1ReplicaSet(
        metadata=client.V1ObjectMeta(owner_references=[
            client.V1OwnerReference(api_version="apps/v1", kind="Deployment", name="test-app", uid="d")]))
    assert workload_of(apps, pod()) == "test-app"
    assert workload_of(apps, pod(owner=False)) is None


def test_collect_reports_pull_failure_as_structured_fact():
    core = MagicMock()
    core.read_namespaced_pod.return_value = pod()
    core.list_namespaced_event.return_value = NS(items=[NS(reason="Failed", message="manifest unknown")])
    facts = AksDiagnosticProvider(core, MagicMock()).collect(make_trigger())
    assert facts.pull_failures[0].image == OLD
    assert any(e.name == "image-pull-failures" for e in facts.items)
    core.read_namespaced_pod_log.assert_not_called()


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


ACTION = ActionRequest("fix_image", {
    "namespace": "test-app", "deployment": "test-app", "container": "api",
    "old_image": OLD, "new_image": NEW,
})


def test_execute_patches_only_the_image_of_the_named_container():
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = deployment(OLD)
    AksActionExecutor(apps).execute(ACTION)
    apps.patch_namespaced_deployment.assert_called_once_with(
        "test-app", "test-app",
        {"spec": {"template": {"spec": {"containers": [{"name": "api", "image": NEW}]}}}},
    )


def test_execute_refuses_when_image_changed_since_diagnosis():
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = deployment("acrprod.azurecr.io/something-else:2")
    with pytest.raises(RuntimeError, match="changed"):
        AksActionExecutor(apps).execute(ACTION)
    apps.patch_namespaced_deployment.assert_not_called()


def test_execute_rejects_unknown_actions():
    with pytest.raises(PermissionError):
        AksActionExecutor(MagicMock()).execute(ActionRequest("scale", {}))


def test_verify_waits_for_rollout_then_succeeds():
    apps = MagicMock()
    apps.read_namespaced_deployment.side_effect = [
        deployment(NEW, observed=1),                    # controller has not seen the new spec
        deployment(NEW, updated=1, available=0),        # new pod not ready yet
        deployment(NEW),                                # healthy
    ]
    sleeps = []
    ok = AksActionExecutor(apps, sleep=sleeps.append, poll_interval=1).verify(ACTION)
    assert ok and len(sleeps) == 2


def test_verify_times_out_when_pods_never_become_available():
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = deployment(NEW, available=0)
    clock = iter(range(0, 1000, 10))
    executor = AksActionExecutor(apps, verify_timeout=30, sleep=lambda s: None, monotonic=lambda: next(clock))
    assert executor.verify(ACTION) is False
