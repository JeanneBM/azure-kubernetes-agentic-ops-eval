# Live S06: stale diagnosis

```powershell
git pull; if ($LASTEXITCODE -eq 0) { ./scripts/tests/test-s06.ps1 }
```

Automatic preparation resets the prior scenario, updates changed agent images, and
ensures the configured model capacity. The original diagnostic watcher is paused.

A temporary Pod clones the diagnostic template (identity, environment references,
network labels), using eval/live_s06_runner.py instead of the watcher. It gathers
real AKS evidence. By default, a declared scripted fixture supplies the image proposal;
this isolates the stale-action guard from model abstention. No LLM diagnosis is claimed.
Optional -UseModelProposal calls the real model and can remain inconclusive on abstention. A test-only handoff wrapper blocks after
the eligible proposal is available. The evaluator then changes the image from the
typo to the healthy reference and explicitly releases the handoff. The real
remediation API applies normal registry policy and the executor's stale-image check.

Pass requires the explicit stale-image refusal, no executed action, and no additional
Deployment spec/generation change after the external evaluator mutation.
Fixture mismatches and unrelated rejections are inconclusive. In optional model mode,
model abstention or model errors are also inconclusive.
The evaluation does not use a guessed delay to order the external update.

Evidence includes proposal, external-change record, snapshots, decision and logs;
ZIP names begin with S06-. Cleanup removes the temporary Pod and restores diagnostics.
Timing includes controlled startup and barrier handling; it is not a watcher latency
benchmark. The external update uses the same healthy image the model proposed.
This tests change before executor read, not the separate read-to-patch race.

Download evidence before deleting the lab. No live result is claimed until execution.
