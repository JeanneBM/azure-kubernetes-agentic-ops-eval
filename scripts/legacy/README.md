# Older S-only launchers

These launchers remain available for existing workflows. They run S scenarios;
they do not implement the complete S/K/P/handoff evaluation campaign.

- `S01-S06-tests.ps1`: S01–S06 batch.
- `S01-S10-tests.ps1`: S01–S10 batch.
- `run-tests-one-by-one.ps1`: selected S scenarios, separate processes and optional pauses.

For the full campaign, use `python scripts/evaluation/run_evaluation.py` from the
repository root and follow the [evaluation guide](../../docs/full-evaluation.md).
Individual scenario scripts are in [scenarios/](../scenarios/).
