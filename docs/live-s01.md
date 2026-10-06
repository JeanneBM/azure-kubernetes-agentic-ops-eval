# Run one live S01 trial

Use PowerShell 7 with kubectl connected to the isolated PoC cluster. Setup and
test execution are separate: this script provisions no Azure resources.

```powershell
./scripts/test-s01.ps1 -AcrLoginServer '<YOUR_ACR_LOGIN_SERVER>'
```

For the environment created by setup-environment.ps1:

```powershell
$config = Get-Content ./.local/rg-agentic-ops-lab.json -Raw | ConvertFrom-Json
$registry = ($config.demoImage -split '/')[0]
./scripts/test-s01.ps1 -AcrLoginServer $registry -Kubeconfig $config.kubeconfig
```

For the manually deployed lab used on 2026-10-06:

```powershell
./scripts/test-s01.ps1 -AcrLoginServer 'acragentevalfe8616e8d7.azurecr.io'
```

Review your current kubectl context before using the last command. The script
targets payments/payments-api and api, and requires the healthy starting image
payments-api:1.4.2 in the supplied registry. It preserves diagnostic logs and
restarts the diagnostic Deployment to clear its in-memory incident cooldown.
It injects paymnets-api:1.4.2, waits up to 180 seconds (configurable with
-TimeoutSeconds), and never manually repairs the Deployment after injection.
A failed or timed-out run can leave the injected image in place. Prepare a
healthy baseline before another run.

Evidence is written to eval/evidence/S01/<UTC-run-id>-C-01/ and a sibling ZIP.
An optional -EvidenceRoot overrides the output directory. Files include source
revision when git is available, current context, command exit codes, injection
output, before/after Deployment snapshots, best-effort failing Pod capture,
events, both agents' logs, parsed decision when available, result.json and
evidence.md. Screenshot the final decision, image and Pod table and place it in
screenshots/. Download the ZIP before ending ephemeral Cloud Shell sessions.

Pass requires a matching resolved fix_image audit with action_executed=true,
the exact old/new image pair and API container, a fully healthy Deployment,
and restoration of its original spec. Otherwise the script raises an error
after capturing evidence. Setup or collection errors are inconclusive.
Rollout readiness does not verify business functionality. Full spec comparison
is intentionally conservative and concurrent external changes can fail the trial.

One execution is one C-variant trial, not an evaluation batch or baseline
comparison. Deployment logs may omit older containers if agents restart during
the trial; use the saved agent Pod snapshots to investigate gaps. Review and
redact files before publishing; kubeconfig and Secrets are never exported.
This script does not claim that a live run has occurred merely by being added.
