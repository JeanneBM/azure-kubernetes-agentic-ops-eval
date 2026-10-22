# Controlled live handoff trials

Run after setup and a passing S01, with the updated agent image already deployed.
From the repository in Git Bash:

```bash
git pull --ff-only
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 pwsh -NoProfile -File ./scripts/tests/test-handoff.ps1
```

Requires Python 3.11+, PowerShell 7, kubectl and an authenticated Azure CLI. The
host Python driver uses only the standard library; the evaluator uses dependencies
already in the agent image. The script verifies kubeconfig against the recorded
AKS identity using `.local/rg-agentic-ops-lab.json`. It never creates Azure resources.
Do not run another test or operator rollout concurrently.

The driver pauses automatic diagnostics and creates one temporary evaluator Pod at
a time using the diagnostic service account and configuration. Its image is pinned
to the running remediation image digest. A scripted proposal is passed through the
production `IncidentOrchestrator` and `HttpRemediationAgent` to a loopback proxy,
which forwards the request to the real remediation service. Only that service
authorizes and patches the Deployment. No model is called or evaluated here.

| Trial | Fault | Required result |
| --- | --- | --- |
| delayed | Acknowledgement withheld until at least 100 seconds after request receipt | resolved, executed=true, one upstream request, healthy workload |
| lost-ack | Connection closed after upstream confirms execution and healthy rollout | escalated, executed=null, one upstream request, healthy workload |

Both trials require exactly one Deployment generation increment after injection
and only the API image to change. A missing upstream confirmation is inconclusive,
not evidence that a patch occurred. This validates delayed HTTP acknowledgement,
not a genuinely 100-second Kubernetes rollout. The lost-ack trial injects a closed
connection, not a full 180-second read-timeout; timeout handling also has local
regression coverage. These are controlled transport trials, not continuous-operation
tests, security proofs, or model benchmarks.

In `finally`, the driver collects logs/snapshots, deletes temporary evaluator Pods,
restores the known good image, and restores the original diagnostic replica count
after the application is healthy. Restoration failures are reported in
`cleanup_errors`; diagnostics may remain paused. Do not interrupt by killing the
terminal: finally blocks cannot recover from process/host termination.

Raw evidence and a JSON summary go under `.local/evidence/handoff/`; the wrapper
creates an anonymized ZIP under `eval/evidence/` using the existing sanitizer.
Inspect the archive before publishing. The script leaves the Azure lab running;
delete it with the existing cleanup command when finished. A live result has not
been recorded merely because local tests passed.
