# Changelog

Notable changes to this project are recorded here, newest first.

Changes are grouped under Added, Changed, Fixed, Removed, or Security when
applicable. Merged changes remain under Unreleased until a release is published.
Release entries use the published version and an ISO date (`YYYY-MM-DD`).
The package version alone does not establish a release date.

## [Unreleased]

### Changed

- Live S01 now loads setup registry/kubeconfig automatically, reports collection
  errors in the console and displays the API image by container name.

- Replace `stop-agentic-ops.ps1` with `delete-environment-resource-group.ps1` for complete
  PoC resource-group deletion, typed confirmation and a completion check.

### Fixed

- Remove eligible Network Watchers with the Cloud Shell-confirmed `az resource
  delete --resource-group ... --name ... --resource-type Microsoft.Network/networkWatchers`
  command, using discovered names/groups and verifying absence afterwards.

- Cleanup resolves one native Azure CLI executable, bypassing `az` functions or
  aliases and duplicate PATH matches. Remaining AKS node groups no longer stop
  regional watcher checks, but still fail completion; retained shared watchers
  and the retry inventory path are reported explicitly.

- S02 pre-injection readiness checks now inspect only active Pods owned by the
  current Deployment revision, excluding old or terminating rollout Pods. Require
  the desired replica count and running, ready metrics sidecars; capture selected
  Pods and report setup errors directly in the console.

- Environment deletion now captures and verifies AKS node groups, cleans unused
  regional Network Watcher leftovers and empty NetworkWatcherRG, and retains
  shared/nonempty watchers with an explicit report. Cleanup inventory supports
  retries without guessing resource ownership after group deletion.

### Added

- Add `scripts/test-s03.ps1` for a live missing-image escalation trial, with ACR
  repository inventory, post-injection spec/generation preservation checks and
  evidence ZIP capture. Transport/model errors do not count as a scenario pass.

- Add `scripts/test-s02.ps1` and a live S02 guide for healthy-sidecar preparation,
  API-only fault injection, verified recovery and preservation checks, and evidence ZIP capture.

- `scripts/test-s01.ps1` for one separate live S01 trial, with fault injection,
  bounded observation, audit/rollout/spec validation, failure evidence and ZIP
  export. No automatic manual repair after injection.

- `scripts/setup-environment.ps1` for clean Azure provisioning and healthy PoC
  deployment, with quota checks, resumable names, separate kubeconfig, setup
  snapshots and a setup guide. It runs no tests and injects no faults.
- Git/build exclusions for local setup state and credentials.

- `eval/evidence/` for redacted live PoC logs, resource snapshots and screenshots,
  organized by scenario and UTC run ID, with a run evidence template and manual
  collection guidance. No live results or automatic log collection are introduced.

- S05 two-container pull failures and S06 stale-diagnosis scenario modules
  (20 new checks). S05 covers both container orders and rejects before registry
  lookup. S06 injects a synchronized external image update after policy
  authorization, rejects the stale action, and preserves the external change
  without an agent patch. Full constrained suite: 124 passed.

- S03 missing-image and S04 pod pull-authentication scenario modules, with five
  fresh trials per input case (20 new checks). Both assert evidence-backed
  escalation, no attempted patch, and an unchanged Deployment. S03 covers
  model abstention and an absent proposed correction; S04 covers both watcher
  pull reasons while remediation registry authentication succeeds.

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

- README links to the demo recording and project solution PDF.
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

