# Test organization

| Location | Purpose |
| --- | --- |
| `scenarios/test_s01_repository_transposition.py` | S01: repair the intended repository image; five fresh mocked trials. |
| `scenarios/test_s02_healthy_sidecar.py` | S02: preserve the healthy sidecar and unrelated fields; five fresh trials per container order. |
| `scenarios/test_s03_missing_image.py` | S03: no eligible correction; five fresh trials each for model abstention and an absent proposed image. |
| `scenarios/test_s04_pull_authentication.py` | S04: pod authentication failure with successful remediation ACR reads; five fresh trials per pull reason. |
| `scenarios/test_s05_two_pull_failures.py` | S05: two failing containers; five fresh trials per container order; escalation without any patch. |
| `scenarios/test_s06_stale_diagnosis.py` | S06: synchronized external update before execution; five fresh trials each for a corrected image and a newer release. |
| `scenarios/support.py` | Shared image-typo fixture, mocked HTTP wiring, and recovery/escalation assertions. Not a test module. |
| `test_end_to_end.py` | Existing cross-component rejection checks: absent proposed image and existing image that fails to pull. |
| Other `test_*.py` files | Component and contract checks for policy, adapters, orchestration, transport, and watcher. |
| `conftest.py` | Existing shared component-test helpers. |

## Run a scenario

```sh
python -m pytest tests/scenarios/test_s01_repository_transposition.py -v
python -m pytest tests/scenarios/test_s02_healthy_sidecar.py -v
python -m pytest tests/scenarios/test_s03_missing_image.py -v
python -m pytest tests/scenarios/test_s04_pull_authentication.py -v
python -m pytest tests/scenarios/test_s05_two_pull_failures.py -v
python -m pytest tests/scenarios/test_s06_stale_diagnosis.py -v
python -m pytest tests/scenarios/ -v
python -m pytest
```

Pytest reports the scenario file, descriptive test name, container ordering where
applicable, and repetition number. No custom runner or marker registration is
needed to select a scenario.

## Growing the catalog

Use one `test_<lowercase-id>_<description>.py` file per implemented catalog item
(S01-S06; K01/P01 when appropriate). Keep scenario-specific setup and
expected outcomes in that file; reuse the support functions where the fixture
contract matches. Add separate support modules if new failure classes need
different fixtures rather than growing one factory with many boolean switches.

Twenty scenario files are practical: discovery and selection are built into
pytest, and shared infrastructure avoids twenty copies of the service wiring.
Do not create empty files or placeholder passing tests for unimplemented items.
Do not assign a catalog ID to an existing check solely because its name sounds
similar: match the complete scenario prerequisites and assertions first.

Use parameterization for meaningful inputs within a scenario, such as container
ordering. Five repeated deterministic mock checks are retained to match the
current development protocol; they do not measure model variability or cluster
timing. If runtime grows, repeated identical mock trials can be reduced separately
from the required five independent live trials per A/C variant.

These files currently test production application code with fake Kubernetes,
ACR, and model responses. Live AKS and real-model evaluation need separate,
explicitly selected execution and evidence collection; do not interpret these
checks as completion of those evaluations. See `eval/README.md` for results and
`evaluation-scenarios.md` for the full evaluation protocol.

After reorganization on 2026-10-02: 84 tests passed in 1.20 seconds, including all
15 S01/S02 cases. One redundant S01 smoke test was removed; its assertions are
covered by the stronger repeated S01 checks.

