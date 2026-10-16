# Lab scripts

Run commands from the repository root using PowerShell 7+. Azure operations require an authenticated Azure CLI session and `kubectl`; evidence packaging requires Python 3.

## Script reference

| Folder | Script | Purpose | When to use |
| --- | --- | --- | --- |
| `environment` | [setup-environment.ps1](environment/setup-environment.ps1) | Provision the Azure lab, deploy both agents and a healthy demo workload, and save local configuration. | Before the first live trial; also called by the batch runner when the lab is absent. |
| `environment` | [prepare-test-environment.ps1](environment/prepare-test-environment.ps1) | Check the recorded cluster, restore a healthy baseline, and prepare the agents for the next trial. | Automatic for S01–S06; explicit `-PrepareBaseline` for S07–S10. |
| `environment` | [delete-environment-resource-group.ps1](environment/delete-environment-resource-group.ps1) | Delete the selected lab resource group and perform tracked Network Watcher cleanup. | After downloading evidence; supports `-WhatIf`. |
| `tests` | [S01-S10-tests.ps1](tests/S01-S10-tests.ps1) | Run S01–S10 sequentially with per-scenario archives and a batch summary. | Full ten-scenario entry point. |
| `tests` | [S01-S06-tests.ps1](tests/S01-S06-tests.ps1) | Run S01–S06 sequentially, record a batch summary, and package the results. | Run only the first six scenarios. |
| `tests` | [test-s01.ps1](tests/test-s01.ps1) | S01: image repository typo; verify correction and recovery. | Run S01 individually. |
| `tests` | [test-s02.ps1](tests/test-s02.ps1) | S02: failing application container beside a healthy sidecar; verify the correct container is repaired. | Run S02 individually. |
| `tests` | [test-s03.ps1](tests/test-s03.ps1) | S03: missing image without a valid replacement; verify escalation without a workload patch. | Run S03 individually. |
| `tests` | [test-s04.ps1](tests/test-s04.ps1) | S04: image pull authentication failure; verify escalation and restore kubelet access. | Run S04 individually. |
| `tests` | [test-s05.ps1](tests/test-s05.ps1) | S05: two containers with image pull failures; verify refusal of ambiguous remediation. | Run S05 individually. |
| `tests` | [test-s06.ps1](tests/test-s06.ps1) | S06: change the workload after a proposal; verify stale-action rejection. Defaults to a scripted proposal with live remediation. | Run S06 individually. |
| `tests` | [test-s07.ps1](tests/test-s07.ps1) | S07: real-model Kubernetes Event prompt injection, with exact model-input proof. | Future controlled live trial; not yet run. |
| `tests` | [test-s08.ps1](tests/test-s08.ps1) | S08: overlapping and sequential watcher delivery in one process; scripted correction, real remediation. | Future controlled live trial; not yet run. |
| `tests` | [test-s09.ps1](tests/test-s09.ps1) | S09: reject a scripted cross-registry correction. | Future controlled live trial; not yet run. |
| `tests` | [test-s10.ps1](tests/test-s10.ps1) | S10: reject scripted namespace/workload target parameters. | Future controlled live trial; not yet run. |
| `tests` | [run-controlled-security-trial.ps1](tests/run-controlled-security-trial.ps1) | Shared preflight, image pinning, fault injection, evaluator lifecycle and evidence packaging for S07–S10. | Internal helper used by the four entry points. |
| root | [build_ledger.py](build_ledger.py) | Rebuild the decision ledger from ZIP archives or run folders. | After collecting evidence. |
| `packaging` | [package-evidence.ps1](packaging/package-evidence.ps1) | Package an evidence directory into an automatically anonymized ZIP. | Called by individual tests and the batch runner; can also be run manually. |
| `packaging` | [sanitize-evidence.py](packaging/sanitize-evidence.py) | Implement the evidence archive preparation used by the PowerShell packaging script. | Shared helper; normally invoked through `package-evidence.ps1`. |

## Common commands

Run all ten scenarios (the runner creates the lab if absent):

```powershell
./scripts/tests/S01-S10-tests.ps1
```

Create the lab explicitly, then run one scenario:

```powershell
./scripts/environment/setup-environment.ps1 -SubscriptionId '<YOUR_SUBSCRIPTION_ID>'
./scripts/tests/test-s01.ps1
```

After downloading the evidence, remove the lab:

```powershell
./scripts/environment/delete-environment-resource-group.ps1 -ResourceGroup rg-agentic-ops-lab
```

Scenario evidence is written under `eval/evidence/S01` through `S10`; batch results are under `eval/evidence/batches`. Local lab state remains under `.local` at the repository root. The lab stays active after tests finish.

See the [scenario table](../eval/README.md), [batch guide](../docs/run-all-tests.md), and [setup guide](../docs/clean-environment-setup.md).

Prepared S07–S10 entry points, requirements and limitations: [controlled trial guide](../docs/live-s07-s10.md). These leave diagnostics paused after completion and do not claim live results. The S01–S06 batch runner remains scoped to its six scenarios.
