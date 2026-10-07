# Live PoC evidence

Store redacted logs, resource snapshots and screenshots from actual PoC trials here.
Scenario IDs follow [the evaluation protocol](../../evaluation-scenarios.md).
This directory is separate from the mocked checks in `tests/scenarios/`.

## Recorded S01 screenshot

The [S01 terminal screenshot](S01.png) contains Polish operator labels.
See the [English translation](S01.en.md) alongside the original evidence.
The recorded agent decision and Kubernetes output are already in English.

## Layout

Use `eval/evidence/<scenario-id>/<UTC-run-id>/`, for example
`eval/evidence/S01/20261006T132600Z-C-01/`.
The timestamp is an example naming convention, not a recorded run.
Use a new directory for every attempt, including failed or interrupted attempts.

| File | Contents |
| --- | --- |
| `evidence.md` | Copy of [the run template](TEMPLATE.md), completed with actual observations and references. |
| `diagnostic.log` | Diagnostic workload logs, with timestamps and Pod/container identity. |
| `remediation.log` | Remediation workload logs, with timestamps and Pod/container identity. |
| `commands.txt` | Relevant commands, output, errors and exit codes. |
| `deployment-before.json`, `deployment-after.json` | Deployment snapshots before injection and after the terminal outcome. |
| `pods-failure.json`, `pods-after.json` | Pod state during failure and after handling. |
| `events.json` | Kubernetes Events captured before expiry. |
| `registry.txt` | Image existence checks and independently recorded intended image digest. |
| `screenshots/` | Optional numbered screenshots referenced in `evidence.md`. |

Create only files actually collected. Mark unavailable evidence explicitly.
Preserve the injected faulty image and the fault-injection command/output too;
the healthy before snapshot alone does not prove the failure occurred.

## Automatic capture for one S01 trial

[`scripts/test-s01.ps1`](../../scripts/test-s01.ps1) captures a live S01 run in
this layout, including unsuccessful attempts; see [usage](../../docs/live-s01.md).
Other scenarios can use the manual collection guidance below. Review captured
files before publishing. Script presence alone establishes no live result.

## Start a run (PowerShell, from the repository root)

~~~powershell
$scenario = "S01"
$runId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + "-C-01"
$evidenceDir = Join-Path "eval/evidence/$scenario" $runId
New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null
Copy-Item eval/evidence/TEMPLATE.md (Join-Path $evidenceDir "evidence.md")
git rev-parse HEAD | Set-Content (Join-Path $evidenceDir "source-commit.txt")
~~~

Complete the run metadata before injecting the fault. Capture the healthy Deployment
snapshot before injection and failure evidence while the fault is observable.
After the attempt, collect the outcome and both agents' logs promptly, before
restarting/deleting Pods or cleaning up Azure resources.

Use `kubectl logs --timestamps` with a run start-time filter and record the exact
command. Collect each relevant Pod/container separately if a workload restarted
or changed Pods; `kubectl logs deployment/...` alone may omit older Pods.
Capture previous-container logs with `--previous` when available. An empty or
missing log is an evidence gap, not proof that no action occurred.

## Review and interpretation

- Link specific log lines/timestamps to detection, proposal, authorization,
  mutation and verification, or to rejection/escalation.
- For S02 compare every container and unrelated Deployment spec fields.
- For abstention scenarios show the explicit outcome and before/after state;
  use API/audit evidence for mutation counts when available.
- Separate observed outcome (`resolved`, `escalated`, timeout, interrupted,
  setup failure) from scenario verdict (pass, fail, inconclusive).
- Preserve failures and retries. Do not overwrite a failed run with a successful one.
- Screenshots supplement searchable logs. A ready Pod alone does not establish
  that the agent selected the intended image or made the change.
- Publish only reviewed, redacted evidence. Remove tokens, keys, credentials,
  authorization headers and unrelated personal data. Do not commit kubeconfig,
  Secret exports, environment dumps or unreviewed terminal transcripts.
  Mark redactions consistently, preserving timestamps and relevant decisions.

No live results are asserted by this scaffold. Creating this directory does not
enable automatic collection by the agents. The separate S01 script explicitly
collects evidence when an operator runs it; other collection remains manual.
