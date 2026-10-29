# Evaluation closeout — 29 October 2026

**Disposition: closed without human review; validation gaps accepted.**
Development continues in [Agentic Ops Lab](https://github.com/JeanneBM/azure-kubernetes-agentic-ops-lab).

## Recorded results

The [report](../eval/evidence/final/trials/evaluation-report-2026-10-26.md) records
98 outcomes: 75 PASS, 17 SETUP_FAIL, 3 AGENT_FAIL, 1 TIMEOUT and 2 INCONCLUSIVE.
Excluding S04 setup failures, A achieved 35/35 PASS and C 31/35 PASS.
C used gpt-4.1-nano (2025-04-14). This comparison is limited to the configured
image-correction task and model.

## Accepted gaps

- All 90 human-review forms remain incomplete. Original pending fields are
  preserved; the final disposition is closed without human review.
- S04 never established the intended fault in this campaign.
- S09 recorded PASS on a rebuilt image outside the frozen campaign runtime.
  Subsequent live probes were blocked by runtime drift.
- The S08-C timeout remains unexplained.
- The campaign recorded evaluator commit 198324432b352eba5a917e3b5dadfbe30ded5e58
  with a dirty working tree. The 65 frozen-file hashes are preserved; the commit
  alone does not reconstruct all evaluated inputs.
- Security hardening and current CI postdate the live campaign. No new Azure
  validation or production-security guarantee is claimed.
- Cloud resource deletion is not independently confirmed by published evidence.
  Closing or archiving GitHub does not stop Azure charges. Use the existing
  [verified cleanup procedure](../README.md#cleanup) against the saved lab state.

Original [campaign](../eval/evidence/final/campaign.json),
[JSON summary](../eval/evidence/final/summary.json) and
[Markdown summary](../eval/evidence/final/summary.md) are sanitized historical
records. No verdicts or original review forms were rewritten at closeout.

## Sequential test branch disposition

Branch `test/sequential-aks-evidence-and-unit-coverage` at
`1293ff9e1ac528bd39434e13412d8cc5ac664333` was reviewed before closeout.
Its startup-role and watcher tests are identical to main. Protocol-report tests
are identical after the script path move. The sequential launcher changes and
its fixture tests already exist on main with `scripts/legacy` and
`scripts/scenarios` paths. The current runbook also retains the branch's
evidence-validation guidance and adds the full-campaign link.
The branch is integrated by retaining current main content, avoiding restoration
of obsolete paths. Its commits remain reachable through the integration commit.

## Release and continuation

Version 0.2.0 is the closeout snapshot, not a newly validated Azure runtime.
The [release notes](release-v0.2.0.md) state the same limitations.
The Lab continuation should prevent baseline preparation from rebuilding a
frozen campaign image and validate any new runtime under a new campaign.
