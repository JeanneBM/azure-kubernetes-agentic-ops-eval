# Sequential functional tests

Provision the lab once with `scripts/environment/setup-environment.ps1`.
From the repository root in PowerShell 7:

```powershell
git pull
./scripts/legacy/run-tests-one-by-one.ps1
```

This launches `test-s01.ps1` through `test-s10.ps1` as separate PowerShell
processes, waiting for each script to finish and then pausing for 60 seconds.
Each script creates its own evidence and anonymized ZIP in a fresh scenario directory
under `.local/evidence/sequences/<UTC>-<id>/`. The launcher saves console logs
and JSON/CSV/Markdown summaries, including tests not run after an early stop.
PASS requires both exit code zero and a matching `result.json` with verdict `pass`;
missing, malformed or mismatched results are reported as inconclusive errors.
There is no combined batch archive. S07–S10 receive `-PrepareBaseline`.
The launcher requires existing recorded lab state and does not provision resources.

The sequence stops at the first nonzero exit code. To resume from S05, change the
pause, select a range, or explicitly continue after errors:

```powershell
./scripts/legacy/run-tests-one-by-one.ps1 -From 5
./scripts/legacy/run-tests-one-by-one.ps1 -From 7 -To 10 -PauseSeconds 120
./scripts/legacy/run-tests-one-by-one.ps1 -ContinueOnFailure
```

Continuing after errors still reports an overall failure when the sequence ends.
A pause reduces request overlap but does not guarantee avoidance of model throttling.
You can also invoke any `test-sXX.ps1` directly.

Each known-lab trial automatically runs prepare-test-environment.ps1 before fault
injection. It checks the recorded cluster, ensures at least 10 model capacity units,
restores the kubelet's registry-scoped AcrPull if absent, ensures diagnostic read-only
AcrPull for authenticated manifest evidence, pauses diagnostics, restores
the healthy API image, removes the known metrics fixture, waits for healthy rollout,
then resumes diagnostics. Preparation snapshots are stored inside each run's
preparation directory. Prior trial evidence and ZIP files are not modified.

S01–S03 and S05 use this automation with the default local setup state. Explicit
external AcrLoginServer/Kubeconfig configurations remain operator-managed.
S04 requires its recorded lab state.

Capacity 10 is a lab default, not a guarantee against all 429 responses.
Quota, permissions, credential propagation, and service failures remain reported
errors; setup must succeed before a fault is injected. Resumed setup permits changing
model capacity and records the effective requested value in local state.

These are functional trials. Preparation can restart workloads and diagnostic agents,
so do not interpret the sequence as a warmed latency benchmark. Download ZIP evidence
before deleting the environment. Delete the lab after testing with the repository's
delete-environment-resource-group.ps1 script.

## Protocol coverage

For the full repeated A/C protocol, live K cases and infrastructure probes, use
the [new full campaign](full-evaluation.md). This legacy command runs S01-S10 live functional trials, one attempt each. It does not
implement the complete repeated A/C benchmark in evaluation-scenarios.md.
K01-K03 and P01-P08 currently have offline implementations only; run
`python scripts/evaluation/run_protocol_checks.py` separately and label those results offline.
S06/S08/S09/S10 use controlled proposals against live remediation, not model
accuracy trials. S08 does not cover cross-replica overlapping webhook delivery.
Run controlled handoff integration separately with `./scripts/tests/test-handoff.ps1`.
No AKS pass is claimed by adding or locally checking these scripts.
