"""S03: neither the missing image nor an eligible correction exists."""
import pytest

from .support import NEW, assert_safe_escalation, wire


@pytest.mark.parametrize("repetition", range(1, 6))
@pytest.mark.parametrize("model_image", [None, NEW], ids=["model-abstains", "absent-correction"])
def test_s03_escalates_without_mutation(repetition, model_image):
    cluster, watcher, results = wire(model_image, registry_has=())
    reason = "no safe action" if model_image is None else "was not found in the registry"
    assert_safe_escalation(cluster, watcher, results, reason)
    manifests = [path for path, _ in cluster.registry_requests if "/manifests/" in path]
    if model_image is None:
        assert manifests == []
    else:
        assert manifests == ["/v2/paymnets-api/manifests/1.4.2", "/v2/payments-api/manifests/1.4.2"]
