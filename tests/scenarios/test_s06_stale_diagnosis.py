"""S06: an external image update after diagnosis invalidates the repair.

A controlled API-read hook injects the update immediately before the executor
reads the Deployment. No sleeps or production runtime hooks are needed.
"""
from copy import deepcopy

import pytest

from .support import NEW, OLD, wire


@pytest.mark.parametrize("repetition", range(1, 6))
@pytest.mark.parametrize("external_image", [NEW, "acrprod.azurecr.io/payments-api:1.4.3"],
                         ids=["operator-fixes-typo", "operator-deploys-new-release"])
def test_s06_stale_action_preserves_external_change(repetition, external_image):
    cluster, watcher, results = wire(NEW)
    before = deepcopy(cluster.deployment.to_dict())
    read_deployment = cluster.read_namespaced_deployment
    external_changes = []

    def inject_before_executor_read(name, namespace):
        assert not external_changes  # exactly one synchronized external update
        assert (name, namespace) == ("payments-api", "payments")
        # The real policy has already validated OLD absent and NEW present.
        assert [path for path, _ in cluster.registry_requests if "/manifests/" in path] == [
            "/v2/paymnets-api/manifests/1.4.2", "/v2/payments-api/manifests/1.4.2"]
        target = next(c for c in cluster.deployment.spec.template.spec.containers if c.name == "api")
        assert target.image == OLD
        target.image = external_image
        cluster.deployment.metadata.generation += 1
        external_changes.append(deepcopy(cluster.deployment.to_dict()))
        return read_deployment(name, namespace)

    cluster.read_namespaced_deployment = inject_before_executor_read
    assert watcher.process_pod(cluster.pod)
    assert len(external_changes) == 1
    assert len(results) == 1
    result = results[0]
    assert result.incident.status.value == "escalated"
    assert "Deployment image changed since diagnosis" in result.incident.reason
    assert not result.action_executed
    assert cluster.patches == []  # external update is tracked separately
    assert result.incident.facts.pull_failures[0].image == OLD
    assert result.incident.recommendation is not None
    assert result.incident.recommendation.evidence_sources
    expected = deepcopy(before)
    expected["spec"]["template"]["spec"]["containers"][0]["image"] = external_image
    expected["metadata"]["generation"] += 1
    assert external_changes[0] == expected
    assert cluster.deployment.to_dict() == external_changes[0]
