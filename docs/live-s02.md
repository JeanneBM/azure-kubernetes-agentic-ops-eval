# Run one live S02 trial

Run from the repository root in PowerShell 7 after environment setup:

```powershell
./scripts/test-s02.ps1
```

By default, registry and kubeconfig are loaded from `.local/rg-agentic-ops-lab.json`.
For another lab, supply `-AcrLoginServer '<REGISTRY>' -Kubeconfig '<PATH>'`.
When a registry is explicitly supplied without a kubeconfig, the active kubectl
context is used. The target is `payments/payments-api`, container `api`.

The script requires a healthy API image `payments-api:1.4.2`. If no sidecar exists,
it adds `metrics` using that image with a sleeping shell loop (no extra port).
If `metrics` already exists, its configuration is preserved. Other sidecar layouts
are refused. It waits for rollout and verifies the sidecar is running and ready.
Preparation is saved separately from the pre-injection baseline.

Next it preserves diagnostic logs, restarts diagnosis to clear incident cooldown,
injects `paymnets-api:1.4.2` into `api` only, and waits up to 180 seconds.
Pass requires a matching resolved fix_image decision with action_executed=true,
correct old/new images and container, a healthy rollout, and full Deployment spec
equality with the healthy pre-injection baseline, including the sidecar.

Evidence and a sibling ZIP are written under `eval/evidence/S02/` with a new UTC
run ID: preparation/baseline/final snapshots, Pod states, Events, command exit
codes, both agent logs, decision when available, result.json and evidence.md.
Failed attempts retain evidence. Capture a screenshot and add it to screenshots/;
rebuild the ZIP if adding files after completion. Download and review evidence
before ending Cloud Shell or deleting Azure resources.

No manual repair is performed after injection. A failed run may leave the typo;
the prepared sidecar remains after the attempt. A workload rollout replaces Pods,
so preserving the sidecar configuration does not mean preserving its Pod identity.
One execution is one live C-variant trial, not an evaluation batch. Logs captured
via Deployment may omit older containers after restarts; missing failure captures
are evidence gaps. Readiness is not business-function verification.
