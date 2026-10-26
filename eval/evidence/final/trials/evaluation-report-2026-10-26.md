# PoC evaluation summary — 26 October 2026

**Result: controlled image correction worked; adding an LLM did not improve outcomes over the deterministic baseline.**

The PoC tests a narrow operation: correcting a container image repository typo on AKS. It does not demonstrate general cluster diagnosis or autonomous repair.

| What the campaign established | Evidence |
| --- | --- |
| Deterministic correction was sufficient for this task. | Excluding S04 setup failures: A achieved **35/35 PASS**, model-assisted C **31/35 PASS**. |
| Incorrect model behavior can end without a mutation. | Three C recovery failures escalated with no repair executed. A separate C timeout remains unexplained. |
| Stale-action and injected-Event checks met automated criteria. | S06 and S07: **5/5 PASS per variant**. |
| Duplicate-delivery checks mostly passed. | S08: A **5/5 PASS**; C **4/5 PASS, 1 TIMEOUT**. |
| Configuration changes can block evaluation. | Drift detection stopped subsequent live checks; its root cause remains unresolved. |

**These are bounded test results, not proof that the entire architecture is safe.** Both variants use the same deterministic policy gate and executor. The independent intended-image configuration and verified candidates leave little decision-making value for an LLM in this task.

## Campaign outcome

**98 recorded outcomes:** 75 PASS · 17 SETUP_FAIL · 3 AGENT_FAIL · 1 TIMEOUT · 2 INCONCLUSIVE.

- S01/S02 recovery: A **10/10 PASS**, C **7/10 PASS**.
- S03/S05/S06/S07: **all trials PASS** for both variants.
- S09: controlled live probe PASS. P01–P08: eight offline checks PASS.
- S04: all ten attempts failed to establish the injected fault.
- K01–K03, S10, HANDOFF and INFRA: blocked by configuration drift.

A recorded outcome does not necessarily mean the intended test executed. The overall PASS count combines live tests, controlled probes and offline checks.

## What remains unproven

Full safety validation, broader failure diagnosis and generalization remain open. **All 90 available human-review forms are pending.** Five repetitions per scenario and variant do not support broad reliability claims. This report makes no comparative latency, token-cost or statistical-significance claim.

## Engineering conclusion

**Keep simple image correction deterministic.** The reusable contribution is the separation of diagnosis, policy authorization and verified execution, together with evidence collection and evaluation against a baseline.

Any next LLM experiment should address a different task—such as evidence-backed readiness diagnosis—and demonstrate measurable benefit before adding automated remediation. Missing validation in this PoC must remain explicitly documented.

Evidence: per-trial `campaign-result.json`, `result.json`, `artifacts.json` and `review.json` in this directory; baseline commit `20f5dcc01a926891826c603d5447b71dd4da7452`. Published evidence is sanitized; original collection hashes may not match sanitized bytes.

[Evaluation protocol](../../../../evaluation-scenarios.md) · [Campaign procedure](../../../../docs/full-evaluation.md)
