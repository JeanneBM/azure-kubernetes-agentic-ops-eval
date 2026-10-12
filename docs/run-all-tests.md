# All six scenarios from one script

From PowerShell 7 at the repository root:

```powershell
./scripts/S01-S06-tests.ps1
```

The script checks the recorded subscription and provisions the default isolated lab
if its resource group is absent. With no setup state it uses the current Azure
subscription, or the explicit -SubscriptionId parameter. It refuses to adopt an
existing lab group without its setup state.

It runs S01, S02, S03, S04, S05 and S06 sequentially, reusing their scenario scripts.
Each performs automatic preparation. Simultaneous execution would corrupt the shared
Deployment fixtures, so the six scenarios do not run concurrently.

By default it continues after failed/inconclusive scenarios and records every outcome.
-StopOnFailure stops on the first non-pass. -TimeoutSeconds sets scenario decision
deadlines; it does not bound total provisioning/build/preparation duration.

Each batch has its own evidence directory under eval/evidence/batches/S01-S06-<UTC>.
It contains scenario evidence, individual archives, summary.json, summary.csv,
summary.md and a combined batch ZIP alongside the directory.
Old evidence is never selected as a new result. One batch is one repetition per
scenario, not a statistical benchmark. S06 uses a scripted proposal by default and
does not measure model diagnosis quality.

The lab remains active after the batch so results can be inspected. Download the
evidence and run delete-environment-resource-group.ps1 when finished.
Archives are anonymized automatically before packaging. Unsupported content prevents
archive creation. Local source evidence remains unchanged.
