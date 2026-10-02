# Changelog

Notable changes to this project are recorded here, newest first.

Changes are grouped under Added, Changed, Fixed, Removed, or Security when
applicable. Merged changes remain under Unreleased until a release is published.
Release entries use the published version and an ISO date (`YYYY-MM-DD`).
The package version alone does not establish a release date.

## [Unreleased]

### Added

- Functional development checks for S01 repository transposition and S02 a
  failing application container with a healthy sidecar. Each case uses five
  fresh mocked trials; S02 covers both container orderings. Checks assert the
  intended image, exactly one permitted image patch, a resolved outcome after
  simulated rollout verification, and preservation of unrelated Deployment
  spec fields. ([#1])
- `eval/README.md` documenting reproduction commands, observed local results,
  and the boundary between mocked checks and live AKS evaluation. ([#1], [#2])
- `tests/README.md` documenting scenario selection, the test directory map,
  and conventions for extending the scenario catalog. ([#2])
- This changelog and a convention for recording future changes alongside the
  pull request that introduces them.

### Changed

- Organized S01 and S02 into dedicated modules under `tests/scenarios/`,
  with shared fixtures and recovery assertions in `support.py`. Existing
  component and rejection tests remain separate. ([#2])
- Updated the in-memory Kubernetes fixture to apply image patches by container
  name while preserving other fields, enabling meaningful sidecar checks. ([#1])

### Removed

- Redundant S01 smoke test, covered by the stronger repeated scenario checks.
  The reorganized suite contains 84 tests, including 15 S01/S02 cases. ([#2])

### Validation scope

The S01/S02 changes exercise production application code with fake Kubernetes,
ACR, and model responses. They do not change agent runtime behavior or establish
live AKS recovery, real-model diagnostic quality, or A/C benchmark results.
Local validation after reorganization: 84 tests passed on Python 3.12 with the
constrained development dependencies. Detailed evidence and limitations belong
in `eval/`; the full evaluation protocol is in `evaluation-scenarios.md`.

## Maintenance

- Add a concise entry under Unreleased in the same pull request as a notable
  change. Describe the resulting behavior and link the pull request.
- Record only implemented changes here. Keep planned work in issues or the
  evaluation protocol, and measurements in evaluation reports.
- When publishing a release, move the relevant entries into a versioned section
  with the actual release date; retain Unreleased for subsequent work.
- Earlier project history has not been reconstructed into release entries.
  This changelog begins with the S01/S02 evaluation work.

[Unreleased]: https://github.com/JeanneBM/azure-kubernetes-agentic-ops-eval/compare/0c627fa5884471e93356c8c5c90b900ed82a35f7...main
[#1]: https://github.com/JeanneBM/azure-kubernetes-agentic-ops-eval/pull/1
[#2]: https://github.com/JeanneBM/azure-kubernetes-agentic-ops-eval/pull/2
