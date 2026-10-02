# S01 and S02 development checks

These checks implement the functional assertions for the first two core scenarios
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

The registry fixture contains the intended image and returns 404 for the injected
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

Live S01/S02 evaluation remains pending: this execution environment has no
`kubectl`, Azure CLI, Docker, or configured AKS/inference endpoint. Run the
protocol in `evaluation-scenarios.md` in an isolated configured environment,
with independently recorded image digests and five repetitions per A/C variant,
before drawing recovery-time or Azure integration conclusions.
