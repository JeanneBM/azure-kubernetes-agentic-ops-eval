# Run the lab from local Git Bash on Windows

All `bash` blocks below run in **Git Bash**, from the repository root unless
stated otherwise. PowerShell scripts are launched through `pwsh -File`.
Do not run a `.ps1` file directly in Bash or paste the terminal's leading `$`.

## 1. Install and check prerequisites

Required: Git for Windows (Git Bash), Azure CLI, PowerShell 7, kubectl,
and Python 3.11+ (available as `python`, used for evidence packaging).
Local Docker is not required; images are built in ACR.

If PowerShell 7 is missing, run:

```bash
winget install --id Microsoft.PowerShell --source winget
```

Close and reopen Git Bash after installation. If Azure CLI is missing:

```bash
winget install --id Microsoft.AzureCLI --source winget
```

Close and reopen Git Bash again. Install kubectl if needed:

```bash
az aks install-cli
export PATH="$PATH:$HOME/.azure-kubectl"
```

The PATH command uses the default Windows Azure CLI installation directory.
If the installer reports another directory, add that directory instead.
Repeat the export in a new session, or add it to `~/.bashrc`.

Check the tools before creating resources:

```bash
git --version
az version
pwsh --version
kubectl version --client
python --version
```

## 2. Clone and sign in

For a new checkout:

```bash
cd ~
git clone https://github.com/JeanneBM/azure-kubernetes-agentic-ops-eval.git
cd azure-kubernetes-agentic-ops-eval
```

For an existing checkout, enter its directory and run `git pull --ff-only`.

```bash
az login --use-device-code
az account list --query "[].{Name:name,Subscription:id}" -o table
```

Select the intended subscription using its actual ID, then verify it:

```bash
az account set --subscription '<YOUR_SUBSCRIPTION_ID>'
az account show --query "{Name:name,Subscription:id}" -o table
```

Setup requires resource creation, provider registration and role-assignment permissions.

## 3. Create or resume the environment

Enable UTF-8 for Azure CLI's Python runtime and child processes:

```bash
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
```

Run setup with the selected subscription:

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 pwsh -NoProfile -File ./scripts/environment/setup-environment.ps1 -SubscriptionId "$(az account show --query id -o tsv)" -ModelCapacity 10
```

Wait for **READY FOR TESTS**. The script creates billable resources but does not
run scenarios. Keep `.local/`: it contains recorded lab state and kubeconfig.
After an interrupted setup, rerun the same command with the same parameters.
Existing resources with matching state are reused; setup rebuilds the image
and restores the healthy workload baseline. Save previous test evidence first.

If ACR log streaming reports `UnicodeEncodeError`, `charmap` or `cp1250`,
use the full command above with the inline UTF-8 variables. A log streaming
failure alone does not establish whether the remote image build failed.
Do not start tests until setup completes successfully.

## 4. Run individual tests sequentially

After successful setup:

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 pwsh -NoProfile -File ./scripts/tests/run-tests-one-by-one.ps1 -ContinueOnFailure
```

This runs S01–S10 in separate PowerShell processes, with a 60-second pause
between scripts. Each test keeps its own evidence and anonymized ZIP in
`eval/evidence`. The final console table shows PASS, FAIL, ERROR and NOT RUN,
exit codes and duration. These statuses summarize script exit codes;
review the individual evidence for the scenario verdict and failure cause.
There is no combined archive.

`-ContinueOnFailure` runs the remaining scripts after a nonzero exit code,
then returns an overall failure if any script failed. Omit it to stop at the
first failure; the final table still lists unrun tests.

Resume from S05, or select a range and a longer pause:

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 pwsh -NoProfile -File ./scripts/tests/run-tests-one-by-one.ps1 -From 5 -ContinueOnFailure
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 pwsh -NoProfile -File ./scripts/tests/run-tests-one-by-one.ps1 -From 7 -To 10 -PauseSeconds 120 -ContinueOnFailure
```

Each invocation reports only its selected range. The lab stays active after tests.

## 5. Delete the environment after saving evidence

Keep the recorded state and verify that the selected Azure subscription is the
one used for setup. Run:

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 pwsh -NoProfile -File ./scripts/environment/delete-environment-resource-group.ps1 -ResourceGroup rg-agentic-ops-lab
```

Follow the script's confirmation prompt. Cleanup checks tracked AKS node groups
and eligible unused Network Watcher resources; local evidence remains.
See the [setup and cleanup details](clean-environment-setup.md).

## Common shell errors

| Message | Fix |
| --- | --- |
| `bash: pwsh: command not found` | Install PowerShell 7 and reopen Git Bash. |
| `Install kubectl first` | Install kubectl and add its directory to PATH before launching pwsh. |
| `bash: =: command not found` or syntax error near `<#` | PowerShell syntax was sent to Bash. Use the `pwsh -NoProfile -File ...` commands above. |
| `charmap` / `cp1250` encoding error | Run with `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` as shown above. |
