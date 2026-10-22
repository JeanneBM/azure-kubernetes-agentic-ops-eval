import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agentic_ops import IncidentOrchestrator, IncidentStatus, OutOfScope, PolicyViolation
from agentic_ops.contracts import TriggerContextError, TriggerOwnershipChanged, TriggerTargetGone
from conftest import (
    NEW, FakeDiagnostics, FakeExecutor, FakeRegistry, make_facts, make_policy, make_trigger,
)


def build(facts=None, *, executor=None, diagnostics=None, policy=None, **kwargs):
    diagnostics = diagnostics or FakeDiagnostics(facts if facts is not None else make_facts())
    executor = executor or FakeExecutor()
    return IncidentOrchestrator(diagnostics, executor, policy or make_policy(), **kwargs), diagnostics, executor


def test_typo_is_fixed_and_incident_resolved():
    orchestrator, _, executor = build()
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.RESOLVED
    assert result.action_executed
    assert executor.actions[0].parameters["new_image"] == NEW
    assert executor.actions[0].parameters["namespace"] == "test-app"


def test_unhealthy_rollout_after_fix_is_escalated_not_resolved():
    orchestrator, _, _ = build(executor=FakeExecutor(healthy=False))
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.ESCALATED
    assert result.action_executed
    assert "did not become healthy" in result.incident.reason


def test_model_supplied_target_is_never_executed():
    facts = make_facts(params={"image": NEW, "namespace": "kube-system"})
    orchestrator, _, executor = build(facts)
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.ESCALATED
    assert executor.actions == []


def test_out_of_scope_namespace_raises_before_any_work():
    orchestrator, diagnostics, _ = build()
    with pytest.raises(OutOfScope):
        orchestrator.handle(make_trigger("kube-system"))
    assert diagnostics.calls == 0


def test_low_groundedness_is_escalated_without_action():
    orchestrator, _, executor = build(make_facts(groundedness=0.84))
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.ESCALATED
    assert executor.actions == []


def test_no_action_creates_recommendation_with_model_summary():
    orchestrator, _, _ = build(make_facts(None, params=None, summary="Missing secret"))
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.ESCALATED
    assert result.incident.recommendation.summary == "Missing secret"
    assert result.incident.recommendation.requires_human_approval


@pytest.mark.parametrize("error", [ValueError("bad contract"), RuntimeError("k8s down")])
def test_diagnostic_errors_are_escalated_not_raised(error):
    orchestrator, _, executor = build(diagnostics=FakeDiagnostics(error=error))
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.ESCALATED
    assert type(error).__name__ in result.incident.reason
    assert executor.actions == []


def test_registry_error_is_escalated_without_action():
    policy = make_policy(FakeRegistry(error=RuntimeError("401 from ACR")))
    orchestrator, _, executor = build(policy=policy)
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.ESCALATED
    assert executor.actions == []


def test_executor_failure_is_escalated():
    orchestrator, _, _ = build(executor=FakeExecutor(error=RuntimeError("image changed")))
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.ESCALATED
    assert not result.action_executed


def test_pods_of_one_workload_share_an_incident_and_cooldown_applies():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    orchestrator, diagnostics, _ = build(cooldown=timedelta(minutes=10), clock=lambda: now[0])
    orchestrator.handle(make_trigger())
    now[0] += timedelta(minutes=5)
    second = orchestrator.handle(make_trigger())
    assert second.deduplicated and diagnostics.calls == 1
    now[0] += timedelta(minutes=6)
    assert not orchestrator.handle(make_trigger()).deduplicated


def test_escalated_incident_is_retried_after_cooldown():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    orchestrator, diagnostics, _ = build(
        make_facts(groundedness=0.1), cooldown=timedelta(minutes=10), clock=lambda: now[0]
    )
    orchestrator.handle(make_trigger())
    now[0] += timedelta(minutes=11)
    assert not orchestrator.handle(make_trigger()).deduplicated
    assert diagnostics.calls == 2


def test_different_failure_on_same_deployment_starts_new_incident_without_restart():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    orchestrator, diagnostics, executor = build(clock=lambda: now[0])
    first = orchestrator.handle(replace(make_trigger(), failure_fingerprint="generation-1-image-a"))
    now[0] += timedelta(minutes=3)
    second = orchestrator.handle(replace(make_trigger(), failure_fingerprint="generation-3-image-b"))
    assert not second.deduplicated
    assert second.incident is not first.incident
    assert second.incident.status is IncidentStatus.RESOLVED
    assert diagnostics.calls == 2
    assert len(executor.actions) == 2


def test_same_failure_from_another_pod_is_deduplicated():
    orchestrator, diagnostics, executor = build()
    trigger = replace(make_trigger(), failure_fingerprint="same-rollout-and-image")
    first = orchestrator.handle(trigger)
    second = orchestrator.handle(replace(trigger, pod="another-replica", correlation_id="duplicate"))
    assert second.deduplicated
    assert second.incident is first.incident
    assert diagnostics.calls == len(executor.actions) == 1


def test_same_image_failure_in_a_later_rollout_is_a_new_incident():
    orchestrator, diagnostics, executor = build()
    orchestrator.handle(replace(make_trigger(), failure_fingerprint="generation-1-image-a"))
    result = orchestrator.handle(replace(make_trigger(), failure_fingerprint="generation-3-image-a"))
    assert not result.deduplicated
    assert diagnostics.calls == len(executor.actions) == 2


@pytest.mark.parametrize("second_fingerprint", ["same", "different"])
def test_concurrent_signals_execute_the_action_once(second_fingerprint):
    entered, release = threading.Event(), threading.Event()

    class SlowDiagnostics(FakeDiagnostics):
        def collect(self, trigger):
            entered.set()
            release.wait(5)
            return super().collect(trigger)

    executor = FakeExecutor()
    orchestrator, _, _ = build(diagnostics=SlowDiagnostics(make_facts()), executor=executor)
    first = threading.Thread(target=lambda: orchestrator.handle(
        replace(make_trigger(), failure_fingerprint="same")
    ))
    first.start()
    assert entered.wait(5)
    second = orchestrator.handle(replace(make_trigger(), failure_fingerprint=second_fingerprint))
    release.set()
    first.join(5)
    assert second.deduplicated
    assert len(executor.actions) == 1


def test_cluster_context_is_resolved_before_deduplication():
    fingerprint = ["revision-1"]
    orchestrator, diagnostics, _ = build(
        resolve_trigger=lambda trigger: replace(trigger, failure_fingerprint=fingerprint[0]),
    )
    orchestrator.handle(make_trigger())
    assert orchestrator.handle(make_trigger()).deduplicated
    fingerprint[0] = "revision-3"
    assert not orchestrator.handle(make_trigger()).deduplicated
    assert diagnostics.calls == 2


def test_context_lookup_failure_never_runs_diagnostics_or_remediation():
    def unavailable(trigger):
        raise RuntimeError("cluster unavailable")

    orchestrator, diagnostics, executor = build(resolve_trigger=unavailable)
    with pytest.raises(TriggerContextError, match="cluster unavailable") as raised:
        orchestrator.handle(make_trigger())
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert diagnostics.calls == 0
    assert executor.actions == []


@pytest.mark.parametrize("error", [TriggerTargetGone("pod gone"), TriggerOwnershipChanged("moved")])
def test_typed_context_errors_pass_through_unchanged(error):
    def lookup(trigger):
        raise error

    orchestrator, diagnostics, executor = build(resolve_trigger=lookup)
    with pytest.raises(type(error)) as raised:
        orchestrator.handle(make_trigger())
    assert raised.value is error
    assert diagnostics.calls == 0
    assert executor.actions == []


def test_expired_completed_entries_are_removed_for_other_workloads():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    orchestrator, _, _ = build(clock=lambda: now[0])
    orchestrator.handle(make_trigger())
    now[0] += timedelta(minutes=16)
    orchestrator.handle(make_trigger(workload="other"))
    assert [key for key, _ in orchestrator._completed] == ["test-app/other"]


def test_interleaved_rollout_notifications_stay_deduplicated():
    # Rollout 2 is handled while pods of rollout 1 still emit events.
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    orchestrator, diagnostics, executor = build(clock=lambda: now[0])
    first = orchestrator.handle(replace(make_trigger(), failure_fingerprint="rollout-1"))
    now[0] += timedelta(minutes=1)
    second = orchestrator.handle(replace(make_trigger(), failure_fingerprint="rollout-2"))
    now[0] += timedelta(minutes=1)
    late_first = orchestrator.handle(replace(make_trigger(), failure_fingerprint="rollout-1"))
    late_second = orchestrator.handle(replace(make_trigger(), failure_fingerprint="rollout-2"))
    assert late_first.deduplicated and late_first.incident is first.incident
    assert late_second.deduplicated and late_second.incident is second.incident
    assert diagnostics.calls == len(executor.actions) == 2


def test_each_fingerprint_expires_on_its_own_cooldown():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    orchestrator, diagnostics, _ = build(clock=lambda: now[0])
    orchestrator.handle(replace(make_trigger(), failure_fingerprint="rollout-1"))
    now[0] += timedelta(minutes=10)
    orchestrator.handle(replace(make_trigger(), failure_fingerprint="rollout-2"))
    now[0] += timedelta(minutes=6)  # rollout-1 is 16 minutes old, rollout-2 only 6
    assert not orchestrator.handle(replace(make_trigger(), failure_fingerprint="rollout-1")).deduplicated
    assert orchestrator.handle(replace(make_trigger(), failure_fingerprint="rollout-2")).deduplicated
    assert diagnostics.calls == 3


def test_in_flight_entry_is_released_when_handling_raises(monkeypatch):
    orchestrator, diagnostics, _ = build()
    original = orchestrator._process

    def broken_once(trigger):
        monkeypatch.setattr(orchestrator, "_process", original)
        raise RuntimeError("unexpected")

    monkeypatch.setattr(orchestrator, "_process", broken_once)
    with pytest.raises(RuntimeError, match="unexpected"):
        orchestrator.handle(make_trigger())
    # Neither stuck in flight nor recorded as completed: the next signal is handled.
    result = orchestrator.handle(make_trigger())
    assert not result.deduplicated
    assert result.incident.status is IncidentStatus.RESOLVED
    assert diagnostics.calls == 1


def test_policy_refusal_audit_preserves_original_proposal(caplog):
    import json
    import logging

    facts = make_facts(params={"image": NEW, "namespace": "kube-system"})
    orchestrator, _, executor = build(facts)
    with caplog.at_level(logging.INFO, logger="agentic_ops.audit"):
        orchestrator.handle(make_trigger())
    event = next(json.loads(r.message) for r in caplog.records
                 if r.message.startswith('{'))
    assert event['action'] is None
    assert event['action_executed'] is False
    assert event['proposed_action'] == {
        'name': facts.safe_action.name, 'parameters': dict(facts.safe_action.parameters)
    }
    assert executor.actions == []


@pytest.mark.parametrize("groundedness", [0.0, 0.8, 1.0])
def test_multiple_failures_take_precedence_over_model_confidence(groundedness):
    from agentic_ops import PullFailure
    facts = make_facts(groundedness=groundedness, failures=(
        PullFailure("api", "acrprod.azurecr.io/tset-app:1.4.2"),
        PullFailure("metrics", "acrprod.azurecr.io/metrcis:1.0.0")))
    registry = FakeRegistry({NEW})
    orchestrator, _, executor = build(facts, policy=make_policy(registry))
    result = orchestrator.handle(make_trigger())
    assert result.incident.status is IncidentStatus.ESCALATED
    assert "Expected exactly one container failing to pull, found 2" in result.incident.reason
    assert not result.action_executed
    assert executor.actions == []
    assert registry.calls == []
