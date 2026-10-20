# Run S01–S10 from one script

From PowerShell 7, from any directory (replace the checkout path if necessary):

```powershell
& /home/joanna/azure-kubernetes-agentic-ops-eval/scripts/tests/S01-S10-tests.ps1
```

The ten scenarios run sequentially against the shared lab. S01–S06 use their
existing preparation; S07–S10 receive `-PrepareBaseline` automatically.
Default decision timeout is 300 seconds per scenario, configurable from 180 to 900.
Preparation, builds and rollout waits can add time beyond that decision timeout.

By default the runner continues after failures and records each result.
Use `-StopOnFailure` to stop after the first non-pass scenario.
Missing recorded state for an existing resource group is rejected; a missing lab
can be provisioned using the current subscription or `-SubscriptionId`.

Raw evidence and summaries stay under `.local/evidence/batches/S01-S10-<UTC>/`.
Each available scenario ZIP is exported directly into `eval/evidence/`, with a
name ending in `-anonymized.zip`. A combined S01-S10 archive is written there too.
The final output lists full ZIP paths. Missing archives are recorded separately
from functional verdicts and cause the batch command to report failure.

Each scenario runs once. This is not a statistical benchmark.
S06, S08, S09 and S10 use scripted proposals with real remediation;
S07 uses the real model with controlled Event injection.
Diagnostics remain paused after the final controlled trial.
The Azure lab remains provisioned; use the cleanup script after saving evidence.

## First six scenarios only

```powershell
./scripts/tests/S01-S06-tests.ps1
```

### Batch lifecycle guards

The batch starts each scenario in a separate PowerShell process and saves its
console output as `runner-console.log`. Preparation restores both agents to one
replica and checks the observed Deployment generation, replica counts, pod
readiness, and container image before fault injection. A zero-replica Deployment
is not considered ready.

Only read-only `kubectl logs` requests retry (up to four attempts, two seconds
apart). Mutating commands are never replayed by this helper. Exhausted log
requests and preparation failures remain errors in the evidence; they do not
become successful trials. These guards do not solve S04 token/cache-dependent
authentication fault injection; an unobserved authentication failure remains
inconclusive.
