from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import ActionRequest, Facts, IncidentTrigger
from .safety import ActionExecutor, SelfCurePolicy, PolicyViolation, StaleActionError
from .telemetry import Trace


@dataclass(frozen=True)
class RemediationOutcome:
    """The independently verified outcome of the network-isolated second agent."""

    action: ActionRequest | None
    executed: bool | None  # None: the remote execution outcome is unknown.
    successful: bool
    reason: str = ""


class RemediationAgent(Protocol):
    """Network-isolated agent that authorizes, acts, and verifies."""

    def manages(self, namespace: str) -> bool:
        """Return whether the namespace is in this agent's fixed scope."""

    def remediate(self, trigger: IncidentTrigger, facts: Facts) -> RemediationOutcome:
        """Attempt one safe remediation. Raise on policy or infrastructure errors."""


class SafeRemediationAgent:
    """Second agent with no model, browser, or network-search dependency.

    It accepts only the typed handoff from the diagnostic agent. Its policy
    derives target namespace, workload, container, and current image from AKS
    facts, then verifies the rollout independently.
    """

    def __init__(self, policy: SelfCurePolicy, executor: ActionExecutor) -> None:
        self._policy = policy
        self._executor = executor

    def manages(self, namespace: str) -> bool:
        return self._policy.namespace_allowed(namespace)

    def remediate(self, trigger: IncidentTrigger, facts: Facts) -> RemediationOutcome:
        with Trace('remediation', trigger.correlation_id) as trace:
            try:
                return self._remediate(trigger, facts, trace)
            except (PolicyViolation, StaleActionError):
                trace.status = 'escalated'
                trace.event('escalation', status='policy_refusal')
                raise

    def _remediate(self, trigger, facts, trace):
        trace.tool('policy_check', dict(facts.safe_action.parameters) if facts.safe_action else {})
        action = self._policy.authorize(trigger, facts)
        trace.event("policy_authorized")
        self._executor.execute(action)
        trace.event('claim', status='fixed', attrs={'claim_id': trigger.correlation_id})
        try:
            verified = self._executor.verify(action)
        except Exception as error:  # noqa: BLE001 - the write already completed
            trace.status = 'escalated'
            trace.event('escalation', status='verification_error')
            return RemediationOutcome(
                action=action, executed=True, successful=False,
                reason=f"second agent action executed but verification failed: {type(error).__name__}: {error}",
            )
        trace.event('verification', status='ok' if verified else 'failed',
                    attrs={'claim_id': trigger.correlation_id, 'verifier': 'kubernetes_rollout'})
        if not verified:
            trace.status = 'escalated'
            trace.event('escalation', status='verification_failed')
            return RemediationOutcome(
                action=action,
                executed=True,
                successful=False,
                reason="second agent action executed but the workload did not become healthy",
            )
        return RemediationOutcome(action=action, executed=True, successful=True)
