# v0.2.0 — Evaluation closeout

Closes the two-agent AKS image-correction experiment with documented limitations.
The deterministic baseline outperformed the configured gpt-4.1-nano (2025-04-14)
variant on the narrow evaluated task: A 35/35 PASS, C 31/35 PASS after excluding
S04 setup failures.

- 98 recorded outcomes: 75 PASS, 17 SETUP_FAIL, 3 AGENT_FAIL, 1 TIMEOUT,
  2 INCONCLUSIVE. Recorded outcomes combine live trials and offline checks.
- Sanitized trial evidence, original campaign metadata and 65 frozen-file hashes
  are published. The campaign recorded a dirty working tree.
- S09 used a rebuilt image outside the frozen runtime; later live probes were
  blocked by drift. S04 setup and the S08-C timeout remain limitations.
- Closed without human review: 90 review forms remain incomplete.
- Current CI includes tests, SAST, dependency/secret/IaC/container scans and SBOM.
  Runtime hardening postdates the live campaign and has not been revalidated on Azure.
- Azure resource deletion is not independently confirmed; GitHub closeout does
  not establish cleanup completion or cessation of billing.
- Original project code and documentation are licensed under MIT; third-party
  material retains its own terms.

[Final report](https://github.com/JeanneBM/azure-kubernetes-agentic-ops-eval/blob/main/eval/evidence/final/trials/evaluation-report-2026-10-26.md)
· [Closeout record](https://github.com/JeanneBM/azure-kubernetes-agentic-ops-eval/blob/main/docs/closeout.md)
· [Continuation: Agentic Ops Lab](https://github.com/JeanneBM/azure-kubernetes-agentic-ops-lab)
