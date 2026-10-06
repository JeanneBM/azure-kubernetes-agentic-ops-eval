"""S05: two failing containers must never receive an automatic image repair."""
from kubernetes import client
import pytest

from .support import NEW, OLD, assert_safe_escalation, wire


@pytest.mark.parametrize("repetition", range(1, 6))
@pytest.mark.parametrize("sidecar_first", [False, True], ids=["api-first", "sidecar-first"])
def test_s05_two_pull_failures_escalate_without_mutation(repetition, sidecar_first):
    cluster, watcher, results = wire(NEW, sidecar_first=sidecar_first)
    missing_sidecar = "acrprod.azurecr.io/metrcis:1.0.0"
    for containers in (cluster.pod.spec.containers, cluster.deployment.spec.template.spec.containers):
        next(c for c in containers if c.name == "metrics").image = missing_sidecar
    status = next(s for s in cluster.pod.status.container_statuses if s.name == "metrics")
    status.image = missing_sidecar
    status.image_id = ""
    status.ready = False
    status.state = client.V1ContainerState(waiting=client.V1ContainerStateWaiting(
        reason="ErrImagePull", message="manifest unknown"))

    assert_safe_escalation(cluster, watcher, results, "Expected exactly one container failing to pull, found 2")
    assert {(f.container, f.image) for f in results[0].incident.facts.pull_failures} == {
        ("api", OLD), ("metrics", missing_sidecar)}
    # The gate rejects the number of failures before any registry authorization.
    assert cluster.registry_requests == []
