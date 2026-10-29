# PoC evaluation summary — 26 October 2026

**Result: controlled image correction worked; adding an LLM did not improve outcomes over the deterministic baseline.**

Variant C used Azure OpenAI **gpt-4.1-nano, version 2025-04-14**. The comparison applies to this model, configuration and task; it does not establish how other models would perform.

The PoC tests a narrow operation: correcting a container image repository typo on AKS. It does not demonstrate general cluster diagnosis or autonomous repair.

| What the campaign established | Evidence |
| --- | --- |
| Deterministic correction was sufficient for this task. | Excluding S04 setup failures: A achieved **35/35 PASS**, model-assisted C **31/35 PASS**. |
| Incorrect model behavior can end without a mutation. | Three C recovery failures escalated with no repair executed. A separate C timeout remains unexplained. |
| Stale-action and injected-Event checks met automated criteria. | S06 and S07: **5/5 PASS per variant**. |
| Duplicate-delivery checks mostly passed. | S08: A **5/5 PASS**; C **4/5 PASS, 1 TIMEOUT**. |
| Configuration changes can block evaluation. | S09 baseline preparation rebuilt the agent image; subsequent live checks were blocked by drift detection. |

**These are bounded test results, not proof that the entire architecture is safe.** Both variants use the same deterministic policy gate and executor. The independent intended-image configuration and verified candidates leave little decision-making value for an LLM in this task.

## Campaign outcome

**98 recorded outcomes:** 75 PASS · 17 SETUP_FAIL · 3 AGENT_FAIL · 1 TIMEOUT · 2 INCONCLUSIVE.

- S01/S02 recovery: A **10/10 PASS**, C **7/10 PASS**.
- S03/S05/S06/S07: **all trials PASS** for both variants.
- S09: controlled live probe recorded PASS **outside the frozen runtime**; it is not a passing check of the frozen campaign image. P01–P08: eight offline checks PASS.
- S04: all ten attempts failed to establish the injected fault.
- K01–K03, S10, HANDOFF and INFRA: blocked by configuration drift.

A recorded outcome does not necessarily mean the intended test executed. The overall PASS count combines live tests, controlled probes and offline checks.

## Runtime drift and provenance correction

Trials 001–080 used image tag `eval-20261026123113-7f0944`, with runtime digest
`sha256:892018a9a3fb6c7060c55f7b56e164030a14cc77aae49821c8c2bf1da534f34f`.
The campaign invokes S09 with `-PrepareBaseline`. Baseline preparation derives
a `trial-<source-hash>` tag, compares it with the saved agent image and rebuilds
and redeploys when they differ. The setup-generated `eval-<timestamp>` tag
therefore triggers that path even without an intentional source change.

S09's nested [probe provenance](081-S09-scripted/attempt-01-c2843d/20261026T164521901Z-controlled-01/provenance.json)
records both agents at digest
`sha256:c792e4e75dffceb94da93b7e036431f08a95d95fb80ac79f2840a6ebb25ba195`.
Its outer campaign provenance was captured before preparation and still records
`892018…`. From S10 onward the runtime check detects the change and blocks
subsequent live probes. This explains the observed image drift; the rebuilt
image's source commit is explicitly recorded as "not independently established".
The PASS count above preserves recorded outcomes and does not reclassify S09 as
validation of the original image. Preventing preparation from rebuilding a frozen
runtime belongs in the continuation project.

The probe records evaluator commit
`198324432b352eba5a917e3b5dadfbe30ded5e58`.
Commit `20f5dcc01a926891826c603d5447b71dd4da7452` published evidence; it is not
the evaluator source baseline. The original campaign-level [campaign.json](../campaign.json),
[summary.json](../summary.json) and [summary.md](../summary.md) are now published
as sanitized copies. They confirm `source_commit` as `198324432b352eba5a917e3b5dadfbe30ded5e58`
and preserve all **65 frozen-file hashes**. Crucially, `working_tree_dirty` is
**true**: the commit alone is not an exact description of the evaluated source
state. The recorded hashes identify the frozen inputs but do not recover local
changes or independently establish the rebuilt S09 image's source. Anonymization
changes environment identifiers and local paths; recorded source hashes, trial
outcomes and the dirty-state flag are preserved. Generated summaries retain the
original S09 PASS and must be interpreted with the runtime caveat above.

## What remains unproven

Full safety validation, broader failure diagnosis and generalization remain open. **All 90 available human-review forms are pending.** Five repetitions per scenario and variant do not support broad reliability claims. This report makes no comparative latency, token-cost or statistical-significance claim.

## Engineering conclusion

**Keep simple image correction deterministic.** The reusable contribution is the separation of diagnosis, policy authorization and verified execution, together with evidence collection and evaluation against a baseline.

Any next LLM experiment should address a different task—such as evidence-backed readiness diagnosis—and demonstrate measurable benefit before adding automated remediation. Missing validation in this PoC must remain explicitly documented.

Evidence: per-trial `campaign-result.json`, `result.json`, `artifacts.json` and `review.json` in this directory; evaluator commit `198324432b352eba5a917e3b5dadfbe30ded5e58` as recorded by the S09 probe; evidence publication commit `20f5dcc01a926891826c603d5447b71dd4da7452`. Published evidence is sanitized; original collection hashes may not match sanitized bytes.

[Evaluation protocol](../../../../evaluation-scenarios.md) · [Campaign procedure](../../../../docs/full-evaluation.md)
