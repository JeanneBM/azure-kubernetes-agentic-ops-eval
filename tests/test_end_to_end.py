"""Cross-component rejection checks using mocked external services.

Catalogued S01-S06 recovery and escalation checks live in tests/scenarios/.
"""
from scenarios.support import NEW, OLD, pod, wire


def test_hallucinated_image_is_not_applied():
    cluster, watcher, results = wire("acrprod.azurecr.io/payments-api:1.4.3")  # plausible, but this tag does not exist
    watcher.process_pod(pod())
    assert results[0].incident.status.value == "escalated"
    assert "not found" in results[0].incident.reason
    assert cluster.patches == []


def test_image_that_exists_but_fails_to_pull_is_not_touched():
    cluster, watcher, results = wire(NEW, registry_has=(OLD, NEW))  # e.g. missing AcrPull on kubelet
    watcher.process_pod(pod())
    assert results[0].incident.status.value == "escalated"
    assert cluster.patches == []

