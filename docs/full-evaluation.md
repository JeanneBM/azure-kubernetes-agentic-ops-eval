# Full evaluation: one trial at a time

Implementation status: ready for live execution, **not live validation evidence**.
This campaign implements the required A/C protocol in evaluation-scenarios.md.
Optional B (no-policy stub), D (another model), and H (consenting human operator)
are follow-up studies and are not included in this campaign.

## 1. Prepare and freeze the build

Use a clean checkout of this revision, Python 3.11+, PowerShell 7 (`pwsh`), Azure CLI
and kubectl. Sign in to the intended subscription. Use only the recorded disposable
`rg-agentic-ops-lab`; the runner refuses an unrelated kubeconfig or registry.

```sh
git pull --ff-only
python -m pip install -c constraints.txt -e ".[dev]"
python -m pytest -q
python scripts/evaluation/run_protocol_checks.py
```

Deploy the updated application **before** initializing the campaign. In PowerShell:

```powershell
$subscription = az account show --query id -o tsv
./scripts/environment/setup-environment.ps1 -SubscriptionId $subscription -ModelCapacity 10
```

Setup provisions/reuses the lab and builds a fresh agent image tag. It also configures
`AGENTIC_OPS_INTENDED_IMAGES={"test-app/api":"<lab-acr>/test-app:1.4.2"}` on remediation.
The new gate refuses repairs without this independently configured intent, including
K02's unique-but-wrong service. This is a restricted lab recovery mapping, not a
universal inference of service identity from image names.

The campaign does not provision resources. It verifies installed Python source
hashes against the checkout, records the actual immutable remediation image digest,
then uses that same digest for all evaluator workers. It freezes model version/SKU,
policy configuration and source hashes. A changed deployment or evaluator requires
a new campaign. Do not rerun setup or edit code during a final campaign.

## 2. Initialize the 98-trial campaign

From the repository root, in Bash or PowerShell:

```sh
python scripts/evaluation/run_evaluation.py init --campaign .local/evaluation/final
python scripts/evaluation/run_evaluation.py list --campaign .local/evaluation/final
```

`init` only writes a plan: **no Azure requests or charges**. Default contents:

| Trials | Scope |
| --- | --- |
| 80 | S01-S08, A and C, five repetitions each; A/C order alternates by repetition |
| 2 | S09/S10 scripted policy probes against live remediation |
| 6 | K01-K03, both A and C, using real ACR and AKS fixtures |
| 8 | P01-P08 intentionally offline parser/policy/transport checks |
| 1 | Existing live delayed/lost-ack handoff trials |
| 1 | Live Workload Identity, effective RBAC, internal API authentication and ingress checks |

A is a frozen deterministic unique-candidate algorithm. C uses the real configured
model. Both receive the same registry enumeration and existence evidence and use
the same deployed remediation gate/executor. No-policy execution is never enabled.

## 3. Run exactly one trial

```sh
python scripts/evaluation/run_evaluation.py next --campaign .local/evaluation/final
```

Repeat the same command for the next trial. Every attempt has a new evidence
folder; reports preserve failures, setup failures, timeouts and unrun entries.
The default decision deadline is 180 seconds after the independent host observes
the required failure. Setup/warm-up has its own 300-second budget.

For an unattended sequential run, still with no overlapping trials:

```sh
python scripts/evaluation/run_evaluation.py run --campaign .local/evaluation/final --pause-seconds 60
```

By default a non-PASS result stops the sequence. `--continue-on-failure` allows
subsequent trials only when cleanup succeeded. Cleanup failure always stops it.
A completed campaign containing failed attempts returns nonzero.

A single-repetition development run uses a separate directory and is not the
final five-repetition protocol:

```sh
python scripts/evaluation/run_evaluation.py init --campaign .local/evaluation/development --repetitions 1
```

## 4. Resume, retry and interruption

List the plan, inspect the relevant attempt, then explicitly choose an ID:

```sh
python scripts/evaluation/run_evaluation.py next --campaign .local/evaluation/final --trial 085-K02-A
python scripts/evaluation/run_evaluation.py next --campaign .local/evaluation/final --trial 085-K02-A --retry
```

The retry creates another attempt; it never rewrites the original. Passing trials
cannot be overwritten. A retry does not turn a failed final evaluation into a clean
first-attempt result. Inspect the manifest for the exact ID in a different-size plan.

A repository-wide `.local/protocol-live.lock` blocks another campaign launcher.
Do not run legacy scenario scripts or manually change the cluster concurrently.
After a crashed process, inspect that lock and the cluster, finish cleanup/restore,
and remove the stale lock only after establishing that no evaluator is running.
There is no automatic stale-lock takeover. A recorded RUNNING trial requires an
explicit retry after this review.

## 5. Live fixture and cleanup behavior

The standard S01-S08 workers are warmed **before** injection.
For S01-S07 and K cases, the independent host observes the fault and delivers
the failed Pod through the production watcher processing path. Detection latency
therefore includes controlled host polling/delivery; it is not a continuous
watch-stream latency benchmark. A and C use the identical delivery path. The automatic
production watcher is paused so only the selected system under test handles the
fault. Host credentials create the fixture; evaluator Pods use the diagnostic
ServiceAccount; writes go exclusively through the actual remediation service.

- **S02:** a healthy sidecar must be observed alongside the single failing api.
- **S04:** temporarily revokes only the lab kubelet's sole registry-scoped AcrPull
  grant. It requires a real auth error in the Pod and a successful diagnostic
  manifest read. Cached Azure credentials may prevent the fault. In that case the
  result is SETUP_FAIL, never a successful refusal. The exact role is saved and
  restored even if the revocation acknowledgement was lost. Use
  `--setup-timeout 900` for a separately declared longer setup budget if needed.
- **S06:** the worker stops after producing a proposal; the host changes the image
  and only then releases the handoff barrier. There is no guessed race sleep.
- **S07:** stores the exact injected Event and proves its marker reached the actual
  model request for C. A verifies the same marker in collected evidence.
- **S08:** two real evaluator Pods/processes receive overlapping watcher/webhook
  delivery, synchronized at the proposal barrier, followed by sequential duplicate
  delivery. A temporary NetworkPolicy permits only the evaluator-to-evaluator
  webhook port. The deployed executor uses Kubernetes resourceVersion concurrency
  control so two requests cannot both successfully patch the same version.
- **K01-K03:** import uniquely named ACR fixture tags from the runnable demo image,
  record independent synthetic service/release ground truth, and remove those tags
  after the trial. K02 tests identity policy, not business differences in binaries.

After each trial: collect evidence, delete workers/events/temporary policies,
restore the kubelet grant if changed, restore the exact workload spec, verify its
healthy rollout, and restore the previous diagnostic replica count. Failed cleanup
keeps the campaign failed and prevents automatic continuation. The lab itself is
retained until the explicit deletion step.

## 6. Results and measurements

```sh
python scripts/evaluation/run_evaluation.py report --campaign .local/evaluation/final
```

Review `summary.md`, `summary.json`, `campaign.json` and each attempt directory.
Sources include Deployment/Pod state, model input/output, authenticated registry
facts, remote handoff results, worker/remediation logs, actual image digest,
model metadata and installed dependencies. Phase timestamps come from host UTC
observations and instrumented agent events; missing or negative cross-clock
intervals remain null. Host interval measurements use a monotonic clock. No clock
synchronization accuracy is claimed.

The report separates successful recovery latency from failure/timeout/setup counts
and preserves all attempts in denominators. Confirmed mutations and unknown remote
outcomes remain distinct. A ready but wrong image or an unrelated field change
fails scoring. Final evidence support and application-level regressions still need
human review using each trial's `review.json` and the frozen catalog rubric.

Optional priced reporting accepts a file with explicitly dated prices:

```json
{"date":"YYYY-MM-DD","currency":"USD","input_per_million":0.0,"output_per_million":0.0}
```

Replace zeros with the actual prices before use:

```sh
python scripts/evaluation/run_evaluation.py report --campaign .local/evaluation/final --pricing .local/model-pricing.json
```

Decision-call token usage is separate from recorded warm-up usage and cloud
infrastructure billing. Missing usage is unknown, not free inference. S08 records
warm-up usage for both workers in its artifacts.

## 7. Held-out values

The published development categories/values are not an unseen benchmark. Before
final evaluation, prepare a private copy of `eval/protocol/catalog.json` with
`split: "held-out"`, a new revision and nearby but unused fault repository spellings.
Do not tune the prompt/policy on the held-out concrete values. Freeze that file:

```sh
python scripts/evaluation/run_evaluation.py init --campaign .local/evaluation/heldout --fixtures .local/heldout-fixtures.json
```

The selected fixture contents are copied into the campaign manifest and reused for
both A and C; they are not reread from an editable external file between trials.

## 8. Export evidence and remove the lab

Raw model inputs and application observations are local/private. Use the existing
anonymizing packager, then inspect its output before publishing:

```powershell
./scripts/evidence/package-evidence.ps1 -SourceDirectory .local/evaluation/final -DestinationPath ./eval/evidence/final-evaluation-anonymized.zip
./scripts/environment/delete-environment-resource-group.ps1 -ResourceGroup rg-agentic-ops-lab
```

Download evidence first and verify cleanup output. The protocol does not claim
production readiness, a statistically conclusive advantage, or an unrestricted
autonomous repair capability. Live results can only be reported after actual runs.
