"""S03: neither the missing image nor an eligible correction exists."""
import pytest

from .support import NEW, assert_safe_escalation, wire


@pytest.mark.parametrize("repetition", range(1, 6))
@pytest.mark.parametrize("model_image", [None, NEW], ids=["model-would-abstain", "model-would-propose"])
def test_s03_escalates_without_mutation(repetition, model_image):
    # No verified candidate exists, so the diagnostic gate abstains before the model is
    # consulted and the remediation policy is never reached.
    cluster, watcher, results = wire(model_image, registry_has=())
    assert_safe_escalation(cluster, watcher, results, "no safe action")
    assert cluster.model_requests == []
    assert [path for path, _ in cluster.registry_requests] == []
    manifests = [path for path, _ in cluster.diagnostic_registry_requests if "/manifests/" in path]
    assert manifests == ["/v2/tset-app/manifests/1.4.2"]
