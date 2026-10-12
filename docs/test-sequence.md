# Sequential functional tests

Provision once with scripts/setup-environment.ps1 (default ModelCapacity: 10).
From the repository root in PowerShell 7:

```powershell
git pull
./scripts/test-s01.ps1
./scripts/test-s02.ps1
./scripts/test-s03.ps1
./scripts/test-s04.ps1
./scripts/test-s05.ps1
```

Each known-lab trial automatically runs prepare-test-environment.ps1 before fault
injection. It checks the recorded cluster, ensures at least 10 model capacity units,
restores the kubelet's registry-scoped AcrPull if absent, pauses diagnostics, restores
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
