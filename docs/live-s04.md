# Live S04: existing image, pod pull authentication failure

Run from PowerShell 7 in the repository directory after setup-environment.ps1:

```powershell
./scripts/test-s04.ps1
```

Requires Azure CLI, kubectl, the setup state in .local/rg-agentic-ops-lab.json,
healthy payments/payments-api using the configured image with a single api container,
and healthy diagnostic/remediation deployments. The operator needs role assignment
delete/create permissions. Custom lab: pass -ResourceGroup matching its setup state.

The script temporarily removes the isolated lab kubelet's registry-scoped AcrPull
assignment. This can affect every new ACR image pull on the lab cluster. It leaves
the remediation identity's assignment intact and verifies actual image existence
through that identity before injection and during the observed authentication failure.

It keeps the image reference and sets imagePullPolicy=Always with a fresh pod-template
annotation. Azure RBAC propagation and cached tokens can delay or prevent the fault:
setup deadline defaults to 900 seconds. A confirmed authentication failure starts
a separate 180-second decision deadline. No observed fault is inconclusive.

A pass requires authentication evidence on the new trial's Pod, explicit scenario
escalation with action_executed=false, and an unchanged post-injection Deployment
spec and generation. Unrelated agent/transport errors are inconclusive.
The script polls generation; use Kubernetes audit logs for authoritative write history.

Evidence and ZIP are saved under eval/evidence/S04/<UTC>-C-01.
Fault snapshots are captured before the finally block restores and verifies the
original kubelet role assignment. The injected pod-template settings remain.
Role restoration may take time to affect pulls; verify a healthy rollout before
another scenario. Failed restoration makes the result inconclusive.
If the process is forcibly terminated, execute the saved restore-kubelet-access.txt
command immediately. Download evidence before leaving an ephemeral Cloud Shell.

This script has not established a live S04 result until it is run on AKS.
