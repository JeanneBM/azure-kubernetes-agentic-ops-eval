# Scripts by task

Run commands from the repository root. Python tools require Python 3.11+;
PowerShell scripts require PowerShell 7+. Live trials also require an authenticated
Azure CLI session and `kubectl`.

## Where to look

| Task | Folder | Entry point |
| --- | --- | --- |
| Run the complete evaluation, one trial at a time | [evaluation/](evaluation/) | `run_evaluation.py` |
| Run offline protocol checks | [evaluation/](evaluation/) | `run_protocol_checks.py` |
| Create, prepare or remove the Azure lab | [environment/](environment/) | `setup-environment.ps1`, `prepare-test-environment.ps1`, `delete-environment-resource-group.ps1` |
| Check whether the lab is ready | [validation/](validation/) | `validate_lab.py` |
| Run one S01–S10 scenario or the handoff probe | [tests/](tests/) | `test-s01.ps1` … `test-s10.ps1`, `test-handoff.ps1` |
| Package, anonymize or summarize evidence | [evidence/](evidence/) | `package-evidence.ps1`, `sanitize-evidence.py`, `build_ledger.py` |
| Use an older S-only batch launcher | [legacy/](legacy/) | `S01-S06-tests.ps1`, `S01-S10-tests.ps1`, `run-tests-one-by-one.ps1` |
| Change shared implementation helpers | [internal/](internal/) | Python validation adapters, PowerShell runtime and security-trial helper |

## Recommended: complete evaluation

```bash
python scripts/evaluation/run_evaluation.py init --campaign .local/evaluation/final
python scripts/evaluation/run_evaluation.py next --campaign .local/evaluation/final
```

`init` creates the plan without Azure calls. Repeat `next` to run one trial at a
time. The campaign includes S, K, P and handoff trials; the launchers in `legacy/`
cover only S scenarios. See the [full evaluation guide](../docs/full-evaluation.md)
for prerequisites, live trial costs, evidence and reporting.

After updating code or script locations, initialize a new campaign: an existing
campaign deliberately rejects changes to its frozen source files.

## Individual operations

```powershell
./scripts/environment/setup-environment.ps1 -SubscriptionId '<YOUR_SUBSCRIPTION_ID>'
python scripts/validation/validate_lab.py --help
./scripts/tests/test-s01.ps1
./scripts/environment/delete-environment-resource-group.ps1 -ResourceGroup rg-agentic-ops-lab
```

The lab remains active after trials. Download and inspect evidence before cleanup.
Campaign state is under the directory passed to `--campaign`. Standalone scripts
report their evidence locations; legacy batches and standalone scenarios can use
different defaults. See the [scenario guide](../eval/README.md),
[controlled S07–S10 guide](../docs/live-s07-s10.md), and
[setup guide](../docs/clean-environment-setup.md).
