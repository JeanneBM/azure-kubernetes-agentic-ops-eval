"""S04: pod pull credentials fail while remediation registry reads succeed."""
import pytest

from .support import NEW, OLD, assert_safe_escalation, wire


@pytest.mark.parametrize("repetition", range(1, 6))
@pytest.mark.parametrize("pull_reason", ["ErrImagePull", "ImagePullBackOff"])
def test_s04_existing_image_auth_failure_is_not_repaired(repetition, pull_reason):
    # Both references exist: a plausible alternative must still be rejected.
    cluster, watcher, results = wire(NEW, registry_has=(OLD, NEW))
    waiting = cluster.pod.status.container_statuses[0].state.waiting
    waiting.reason = pull_reason
    waiting.message = f'Failed to pull image "{OLD}": unauthorized: authentication required'
    assert_safe_escalation(cluster, watcher, results, "Current image exists in the registry")
    assert any("unauthorized" in item.value for item in results[0].incident.facts.items)
    # ACR exchange/token endpoints succeed; this is NOT a remediation identity failure (P06).
    assert [path for path, _ in cluster.registry_requests] == [
        "/oauth2/exchange", "/oauth2/token", "/v2/paymnets-api/manifests/1.4.2"]
    assert cluster.registry_requests[-1][1] == "Bearer at"
