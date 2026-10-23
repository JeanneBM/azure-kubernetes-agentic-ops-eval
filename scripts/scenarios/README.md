# Live evaluation scenarios

These PowerShell commands inject controlled faults into an existing AKS lab,
observe agent decisions and collect evidence. They are separate from the
[automated code tests](../../tests/README.md) executed by `pytest` and CI.

Run from the repository root with PowerShell 7, Azure CLI and kubectl:

```powershell
./scripts/scenarios/test-s01.ps1
```

| Entry point | Scenario |
| --- | --- |
| `test-s01.ps1` … `test-s06.ps1` | Image failures, safe escalation and stale-action rejection |
| `test-s07.ps1` … `test-s10.ps1` | Injection, duplicate delivery and policy refusal probes |
| `test-handoff.ps1` | Agent-to-agent handoff probes |

Prepare the lab first and inspect each scenario's prerequisites in the
[documentation guide](../../docs/README.md). These commands use live resources;
some use real model calls, while others use controlled scripted proposals.
For the full repeated A/C campaign, use
`python scripts/evaluation/run_evaluation.py` and follow the
[full evaluation guide](../../docs/full-evaluation.md).
