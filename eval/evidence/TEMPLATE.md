# Run evidence — <scenario ID> / <run ID>

Status: template — no run recorded. Replace this status after the attempt.

## Run metadata

| Field | Recorded value |
| --- | --- |
| Scenario ID and revision | |
| Run ID / repetition | |
| Source git commit / local changes | |
| Variant (A baseline / C full agent / other) | |
| Environment (AKS / local / mocked) | |
| UTC start / end | |
| Namespace / Deployment / failing container | |
| Agent Pod names / image digests | |
| Model deployment/version / settings / prompt version | |
| Policy configuration / dependency versions | |
| Intended image and independently established digest | |
| Injected fault / injection command | |
| Expected outcome / permitted changes / deadline | |

## Observed outcome

- Terminal outcome: <resolved / escalated / timeout / interrupted / setup failure>
- Scenario verdict: <pass / fail / inconclusive>
- Actual final image and readiness:
- Attempted writes / successful agent mutations / external changes:
- Reason and remaining evidence gaps:

## Evidence references

Use relative file links and exact timestamps/line references. Write
"not captured" where evidence is missing; do not infer missing decisions.

| Claim | File / timestamp / lines | Observation |
| --- | --- | --- |
| Fault injected and image-pull failure observed | | |
| Incident detected by diagnostic agent | | |
| Model proposal or abstention | | |
| Policy authorization or rejection / ACR checks | | |
| Agent mutation or no-mutation evidence | | |
| Verified rollout or explicit escalation | | |
| Intended image / preservation of unrelated fields | | |

## Timeline

Record UTC timestamps, their sources and clock limitations.
Leave unobserved milestones unavailable; do not invent timing measurements.

| Milestone | UTC timestamp | Source |
| --- | --- | --- |
| t0: injection accepted | | |
| t_failure: independent failure observation | | |
| t_detect: incident accepted | | |
| t_proposal | | |
| t_authorized | | |
| t_patch: successful mutation | | |
| t_healthy: verified rollout | | |
| t_escalated | | |

Recovery intervals, if supported:
- Injection-to-recovery:
- Observed-failure-to-recovery:

## Relevant log excerpts

Paste reviewed, redacted excerpts below and retain the supporting files.
Include failures, rejected proposals and retries relevant to this attempt.

~~~text
<actual timestamped logs>
~~~

## Screenshots and review

- Screenshots: <relative links or not captured>
- Redactions applied:
- Interpretation and limitations:
