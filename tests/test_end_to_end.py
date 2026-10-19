"""Cross-component rejection checks using mocked external services.

Catalogued S01-S06 recovery and escalation checks live in tests/scenarios/.
"""
from scenarios.support import NEW, OLD, pod, wire


def test_hallucinated_image_is_not_applied():
    # One verified candidate (NEW) exists; the model proposes a plausible but different tag.
    cluster, watcher, results = wire("acrprod.azurecr.io/test-app:1.4.3")
    watcher.process_pod(pod())
    assert results[0].incident.status.value == "escalated"
    assert "unique verified candidate" in results[0].incident.reason
    assert cluster.patches == []
    assert cluster.registry_requests == []  # rejected before the remediation policy


def test_image_that_exists_but_fails_to_pull_is_not_touched():
    cluster, watcher, results = wire(NEW, registry_has=(OLD, NEW))  # e.g. missing AcrPull on kubelet
    watcher.process_pod(pod())
    assert results[0].incident.status.value == "escalated"
    assert cluster.patches == []

