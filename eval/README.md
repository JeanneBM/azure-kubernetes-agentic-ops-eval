# S01-S06 development checks

These checks implement the functional assertions for the first six core scenarios
in `evaluation-scenarios.md`. They run the production watcher, Kubernetes diagnostic
adapter, Foundry response parser, ACR existence adapter, policy, orchestrator and
executor against an in-memory Kubernetes fixture and scripted HTTP responses.

Run after installing the constrained development dependencies:

```sh
python -m pytest tests/scenarios/ -v
python -m pytest
```

The scenario files in `tests/scenarios/` make five independent trials with fresh state for each case:

| Case | Fault and ground truth | Assertions |
| --- | --- | --- |
| S01 | `acrprod.azurecr.io/paymnets-api:1.4.2`; intended `acrprod.azurecr.io/payments-api:1.4.2` | Resolved outcome, exactly one image patch, intended image, simulated healthy rollout, preservation of every other Deployment spec field. |
| S02, API first | Same fault plus a running, ready `metrics` sidecar | S01 assertions plus unchanged sidecar image, args, environment, and position. |
| S02, sidecar first | Same as above with reversed container order | Same assertions, exercising named-container targeting rather than positional targeting. |

| S03, model abstains | Missing current image; empty registry; model returns no action | Explicit escalation with evidence, no patch attempt, entire Deployment unchanged. |
| S03, absent correction | Same registry; model proposes a nearby image that also does not exist | Policy rejects absent correction; explicit escalation; no patch attempt; entire Deployment unchanged. |
| S04, both pull reasons | Current and nearby image exist; Pod reports an authentication failure | Reject typo repair after a successful authenticated read of the current image; preserve authentication evidence; escalate without a patch or Deployment changes. |

| S05, both container orders | Application and sidecar both fail to pull | Two structured failures; escalation before registry lookup; no attempted patch; entire Deployment unchanged. |
| S06, operator fixes typo | External update to the intended image before executor reads Deployment | Stale action rejected; no agent patch; preserve the separately recorded external update. |
| S06, operator deploys newer release | External update to `payments-api:1.4.3` before executor reads Deployment | Same rejection and preservation assertions, including all unrelated fields. |

For S01/S02, the registry fixture contains the intended image and returns 404 for the injected
image. The scripted model proposes the intended image and is checked to have
received the failing image in its prompt. The fake Kubernetes API merges the
image patch by container name and immediately simulates controller recovery.
The expected final spec is independently constructed from the before snapshot
with only the API image changed; the exact permitted patch is also asserted.

## Observed result

On 2026-10-02, based on repository commit
`0c627fa5884471e93356c8c5c90b900ed82a35f7` plus the scenario tests:

- S01: 5/5 functional checks passed.
- S02: 5/5 passed in each container ordering (10 checks total).
- Full test suite: 85 passed, pytest reported 1.47 seconds (before the directory reorganization).
  The reorganization removes one redundant S01 smoke test; the current suite has 84 tests.
- Python 3.12; dependencies installed with `constraints.txt` and `.[dev]`.

The suite duration is not incident recovery latency. These results are mocked
development checks, not a final A/C evaluation batch, real model-quality evidence,
or live fault-injection results. No deterministic baseline was evaluated. No
real registry digests, inference cost, cluster timestamps, Workload Identity,
networking, image pulls, or workload readiness were measured.

Live S01-S06 evaluation remains pending: this execution environment has no
`kubectl`, Azure CLI, Docker, or configured AKS/inference endpoint. Run the
protocol in `evaluation-scenarios.md` in an isolated configured environment,
with independently recorded image digests and five repetitions per A/C variant,
before drawing recovery-time or Azure integration conclusions.


S03 covers both model abstention and deterministic rejection of a nonexistent
correction. S04 covers `ErrImagePull` and `ImagePullBackOff`, retaining real adapter
evidence from the simulated Pod/Event. Its ACR OAuth exchange and token calls
succeed, and the authenticated current-image manifest read returns 200. This
is distinct from P06 (remediation registry authentication failure).

## S03/S04 validation — 2026-10-06

Based on main commit `9c134940f42564a11b9940d65792b84ed3c66ccb` plus the S03/S04 changes:

- S03: 10/10 passed (five trials per model response).
- S04: 10/10 passed (five trials per pull reason).
- Full constrained Python 3.12 test suite: 104 passed.

All 35 S01-S04 scenario cases use fresh mocked state. These checks establish
functional behavior for scripted inputs, not live authentication handling or
real-model accuracy. Runtime application code is unchanged.

## S05/S06 validation — 2026-10-06

Based on main commit `49740a62fc53e5fec08fe27a37841f5ff27f4c43` plus these changes:

- S05: 10/10 passed (five fresh trials per container order).
- S06: 10/10 passed (five fresh trials per external image update).
- Full constrained Python 3.12 test suite: 124 passed, including 55 S01-S06 cases.

S06 uses a controlled fixture hook at the executor's Deployment read, after real
policy authorization. The external update is recorded separately from agent
patch attempts, and its complete snapshot is preserved. This checks the existing
pre-execution stale-image guard; it does not establish atomic protection against
a concurrent change after the executor reads the Deployment and before patching.
These are mocked checks; live AKS and real-inference evaluation remain pending.
Runtime application code is unchanged.

## Live PoC evidence

Actual AKS trial logs, snapshots and screenshots belong in
[`evidence/`](evidence/README.md), grouped by scenario and UTC run ID.
Copy [`evidence/TEMPLATE.md`](evidence/TEMPLATE.md) into each run as `evidence.md`.
This scaffold records no live result; keep mocked results above separate from
observations captured in AKS.
