# Live S05: two containers fail to pull

From PowerShell 7 in the repository directory, after S04 access restoration and a
healthy payments-api rollout:

```powershell
git pull; ./scripts/tests/test-s05.ps1
```

Requires the single-container healthy lab baseline with api using
payments-api:1.4.2, the local setup state, kubectl, and healthy agents.

The script verifies through the remediation identity that the healthy image exists
and paymnets-api:1.4.2 does not. It adds a metrics container and gives both containers
the typo image in one Deployment patch. No Azure permissions are changed.

The diagnostic watcher is scaled to zero before injection and resumed once both
containers fail to pull in the same trial Pod. Setup has a 120-second deadline;
decision observation defaults to 180 seconds including diagnostic startup.
This is a synchronized functional trial, not a warmed latency measurement.
The original diagnostic replica count is restored on setup exceptions.

Pass requires explicit scenario escalation, action_executed=false, independent
evidence of two simultaneous failures, and unchanged post-injection Deployment spec
and generation. An unrelated transport/model error is inconclusive.
Snapshots do not replace Kubernetes audit logs for exhaustive mutation history.

Logs, snapshots, decision and result are saved with a ZIP under eval/evidence/S05.
The faulted workload remains for inspection. Download the ZIP before resetting the
workload or deleting the lab; review evidence before publication.
No live result is claimed until execution.

Evidence ZIP names start with the scenario ID: `S05-<UTC-run-id>-C-01.zip`.
