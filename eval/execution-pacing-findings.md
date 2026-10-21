# Execution pacing findings — 2026-10-21

## Main observation

Each scenario S01–S10 had a recorded passing individual trial before the later
batch runs. When the scenarios were run together through a sequential batch
script, the set of scenarios that did not pass varied between runs. On
2026-10-21, launching the individual scripts in separate processes with a
60-second pause between them produced nine passes and one inconclusive result.

This makes execution pacing and restoration of a stable baseline important
variables in this lab. It does not yet establish that the pauses alone caused
the improvement or that previous logs confused the model.

## Recorded chronology

Dates and archive identifiers below use UTC. Counts describe the listed runs,
not a statistical success-rate estimate.

| Date | Execution | Recorded result | Evidence |
| --- | --- | --- | --- |
| 2026-10-09 | Individual S01, S02 and S03 trials | Each recorded PASS. S01 refers to the v2 trial. | [S01](evidence/S01-v2-20261009T120039727Z-C-01-anonymized.zip), [S02](evidence/S02-20261009T105643940Z-C-01-anonymized.zip), [S03](evidence/S03-20261009T111132556Z-C-01-anonymized.zip) |
| 2026-10-12 | Individual S04, S05 and S06 trials | Each recorded PASS. | [S04](evidence/S04-20261012T083058902Z-C-01-anonymized.zip), [S05](evidence/S05-20261012T092231374Z-C-01-anonymized.zip), [S06](evidence/S06-20261012T094802362Z-C-01-anonymized.zip) |
| 2026-10-16 | Individual S07–S10 controlled trials | Each recorded PASS. | Individual archives starting S07–S10 with date 20261016 in [evidence](evidence/). |
| 2026-10-16 | Sequential S01–S10 batch, 122908199Z | 9 PASS; S05 inconclusive. | [Batch archive](evidence/S01-S10/S01-S10-20261016T122908199Z-anonymized.zip) |
| 2026-10-19 | Sequential batch, 102815786Z | 7 PASS; S03, S04 and S05 inconclusive. | [Batch archive](evidence/S01-S10/S01-S10-20261019T102815786Z-anonymized.zip) |
| 2026-10-19 | Sequential batch, 114205242Z | 8 PASS; S04 and S05 inconclusive. | [Batch archive](evidence/S01-S10/S01-S10-20261019T114205242Z-anonymized.zip) |
| 2026-10-20 | Sequential batch, 091414237Z | 5 PASS; S03–S07 inconclusive. | [Batch archive](evidence/S01-S10-20261020T091414237Z-anonymized.zip) |
| 2026-10-20 | Sequential batch, 101456352Z | 6 PASS; S04 and S08–S10 inconclusive. | [Batch archive](evidence/S01-S10-20261020T101456352Z-anonymized.zip) |
| 2026-10-21 | Individual scripts launched sequentially in separate processes, with 60-second pauses | 9 PASS; S04 inconclusive (`setup_fault_not_observed`). | Individual S01–S10 archives with date 20261021 in [evidence](evidence/). Read each `result.json`; the console labels a nonzero script exit as FAIL. |

The earlier individual passes were collected on different days, not as one
controlled ten-scenario run. They demonstrate a passing example for each
scenario, not that every individual attempt passed.

## What the records support

- In the 2026-10-20 09:14 batch, S05–S06 reported an unexpected diagnostic
  replica count; S07 reported a baseline that was not a healthy single-API
  workload. S03 also failed while collecting diagnostic logs before injection.
- In the 2026-10-20 10:14 batch, S08–S10 reported that the diagnostic agent did
  not converge to one ready current-generation replica within 120 seconds.
  Their `faultStartUtc` values are null: the test faults were not injected.
- In the 2026-10-21 individual run, the captured incident decision events fall
  after their respective fault starts and reference the corresponding trial
  resources. S04 contains no incident decision event.
- S04 on 2026-10-21 did not observe the intended authentication failure.
  Cached credentials or another access path are possibilities recorded in
  `result.json`, not a confirmed root cause. Kubelet access was restored.

The strongest direct evidence concerns readiness and baseline preparation,
rather than an agent making a wrong decision because of an earlier trial's logs.
Both execution modes were sequential; the previous batch was not a parallel
ten-test launch.

## Interpretation and next step

Slower execution was associated with improved results in the latest run.
Readiness convergence, asynchronous cleanup and access propagation are plausible
contributors. Cross-trial event contamination remains a hypothesis; it requires
matching event timestamps, Pod identities and actual model input across trials.

Scripts and preparation checks also changed, and the latest run moved from
Cloud Shell/Linux to local Windows Git Bash. Therefore this is an observational
finding, not a controlled comparison of pause lengths. S06 and S08–S10 use
scripted proposals, so their passes do not measure LLM diagnosis quality.

Prefer explicit readiness and baseline checks over a fixed delay alone. A
follow-up comparison should keep the application image, runner revision,
environment and trial order fixed, vary only the pause, and repeat both settings.
Record setup/collection failures separately from scenario verdicts and agent
outcomes. Preserve every attempt, including inconclusive runs. A planned S04
retry after a longer pause is not counted here until its evidence is available.

## Continuous operation and incident bursts — open question (2026-10-21)

**Potential weakness to investigate:** closely spaced or simultaneous incidents
may expose interference between in-flight actions, retained agent state,
deduplication and Kubernetes events. Current evidence does not establish event
overload or stale logs confusing the model as the root cause.

The operator reported a subsequent sequence with S02 and S04 not passing. The
shared S02 decision shows an injected fault followed by model abstention: the
model recognized the missing typo image and verified replacement, but interpreted
the 401 message as an access issue and escalated. This is a scenario failure,
distinct from a setup failure. The new run's complete archives have not been
reviewed for this note; input equivalence and the cause of the changed decision
remain unconfirmed.

### Separate the evaluation questions

| Test mode | Question | Agent lifecycle |
| --- | --- | --- |
| Isolated scenario | Can the system handle a defined fault from a known baseline? | A documented reset/restart is allowed. |
| Continuous sequence | Can it handle successive incidents while retaining state? | Keep both agent processes running across incidents. |
| Concurrent incidents / burst | Can it safely separate and handle overlapping incidents? | Keep agents running; deliberately control incident timing and workload targets. |

Resetting between isolated trials is legitimate, but cannot demonstrate
continuous-operation reliability. Resetting or restarting agents after every
action could hide state, deduplication or unfinished-action problems. Restoring
the disposable application is a different operation from restarting the agents;
record any operator restoration separately from autonomous recovery.

### Follow-up trial requirements

- Keep the same deployed image digest, configuration and agent Pods/processes;
  record Pod UIDs and restart counts. An unexpected restart breaks the
  uninterrupted-operation claim and must remain in the results.
- Start with a sequential incident stream, then test controlled overlap and a
  bounded burst. Do not describe ordinary sequential batches as concurrent.
- Define workload targets and expected outcomes before injection. Multiple
  failures outside the current remediation policy may correctly require
  escalation; a burst test does not expand the permitted repair scope.
- Correlate each fault, Kubernetes event, model input, proposal, authorization,
  write and verification with its incident and timestamps.
- Check that old events do not trigger incorrect new actions, duplicate delivery
  does not cause duplicate writes, and stale proposals cannot overwrite newer
  state. Account for unfinished actions and record recovery after the burst.
- Evaluate availability and safety separately: latency, completed/unresolved
  incidents, correct escalations, model variability, duplicate writes and
  unauthorized or incorrect mutations. Record throttling and readiness failures
  separately rather than attributing all nonpasses to reasoning.

This is a planned evaluation direction, not a completed test or a confirmed
weakness. The existing controlled S08 duplicate-delivery test covers a narrower
case and does not establish general burst resilience.
