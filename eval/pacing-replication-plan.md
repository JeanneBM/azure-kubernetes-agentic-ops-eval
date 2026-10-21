# Pacing and readiness replication plan

Status: **planned, not executed.** This document defines a prospective experiment; it contains no experimental results.

## Key takeaways

- Primary endpoint: SETUP_FAIL rate across all six scenarios, with equal scenario weights and comparisons within repetition blocks.
- Primary comparison: readiness gate C versus no added gate or pause A. Pause B versus A is secondary.
- S01 is the stable reference control; S02 probes decision variability.
- Ninety attempts form an exploratory study. Expansion uses the operational criterion below, fixed before execution.
- This phase evaluates test reliability. LLM value versus scripts and uninterrupted operation require separate comparisons.

## Question

With the environment, runner and configuration held constant, does a fixed pause or an explicit readiness gate improve the reliability of sequential scenario execution?

Historical scripts, preparation checks and the execution environment changed together. This experiment tests pacing and readiness prospectively under a fixed configuration.

## Held constant

- Application and agent image digests; runner and scenario revisions.
- One lab, execution environment and tool versions, for example local Windows Git Bash with PowerShell.
- Model deployment, available model version, prompt, parameters and agent configuration.
- Scenario order, expected outcomes, fault injection and verification logic.
- Baseline restoration, agent restart policy, timeouts, retry policy and evidence collection.
- Permissions, permitted repair scope and mandatory safety checks in every arm.

Record these values in a run manifest. A required implementation change starts a new experimental revision; do not silently pool results across revisions.

## Arms

| Arm | Added pause between trials | Additional readiness gate before injection |
| --- | --- | --- |
| A | 0 s | None beyond the common preparation procedure. |
| B | 60 s | Same as A. |
| C | 0 s | Wait for the configured ready replicas, including exactly one current-generation diagnostic replica, and the scenario's healthy baseline. |

Keep the common preparation procedure identical. Arm C adds a bounded, explicitly logged wait; it must not introduce extra repairs, retries or a different baseline. Define the gate timeout before the first trial. A gate timeout is a SETUP_FAIL and remains in the results.

The added pause is measured from the end of the previous trial's evidence collection and restoration to the start of the next trial's common preparation. Log the actual interval between faults as well: 0 s added pause does not mean zero elapsed preparation time. Use the same block-start preparation for every arm.

These three arms compare pause versus no pause and gate versus no gate. They do not estimate an interaction between pause and gate; that would require a fourth arm with both.

## Scope and execution

Start with six scenarios to limit cost:

- Historically fragile scenarios: S03, S04, S05 and S07.
- Stable reference control: S01, which passed in the reported runs. This is an operational reference, not a guarantee of future success.
- Decision-variability scenario: S02, included because a later sequence exposed inconsistent repair decisions. It is not a stable control.

Three arms × six scenarios × five repetition blocks = **90 attempts**, including failed setup and inconclusive attempts. Within each block, run all three arms with the same scenario order. Randomize and counterbalance arm order across blocks, using a recorded seed, so one arm does not consistently run first or last.

First run a small pilot to verify that arms differ only as specified and that evidence collection works. Pilot attempts may count toward the 90 only if the protocol remains unchanged; otherwise retain them separately. Apply the expansion criterion below after the completed study.

This phase evaluates isolated scenarios under a documented, identical restoration and restart policy. It does not establish uninterrupted agent operation. Later continuous-operation tests are defined separately below.

## Fault confirmation, including S04

In **every arm**, record injection time and independently confirm that the intended fault actually occurs after injection, before attributing the result to the agent. Use the same observation window and evidence capture in every arm; retain any decision made during that window.

For S04, confirm the intended authentication failure on the workload's actual image-pull path. A role change or pod deletion alone is not proof that access failed. If the fault is not observed within the defined window, classify SETUP_FAIL rather than agent failure. Cached credentials or an alternative access path are hypotheses to investigate; an additional pause alone is not a demonstrated remedy.

Fault confirmation is a shared validity check, not an extra readiness gate exclusive to C. The evaluated incident timeline starts at injection, not after fault confirmation.

## Recorded per attempt

- Arm, block, scenario, execution order and immutable configuration references.
- Expected behavior and observed outcome category, using the [shared taxonomy](readiness-and-baseline-findings.md#outcome-taxonomy).
- Script exit code, original scenario verdict, outcome reason and any evidence limitations.
- UTC timestamps for preparation, readiness, injection, fault observation, decision, write, verification and restoration.
- Added pause, actual interval between faults, gate duration, retries and timeouts.
- Agent and workload Pod UIDs, restart counts, generations and image digests.
- Model input hash, correlation identifiers and returned model metadata where available.
- Operator intervention separately from autonomous recovery.
- Archive path containing `result.json`, relevant events, decisions and available execution/audit evidence.

## Primary endpoint and analysis

**Primary endpoint:** the proportion of attempts classified SETUP_FAIL in each arm, aggregated over the six scenarios and stratified by repetition block. Each completed arm has 30 attempts: six scenarios × five blocks.

For arm X in block b, define `p[X,b] = SETUP_FAIL count / 6`. The arm rate is the mean of its five block rates; this gives every scenario and block equal weight. The **primary contrast** is the mean of the five paired differences `p[C,b] - p[A,b]`, expressed in percentage points. Negative values favor readiness gating. Report the five block contrasts alongside the aggregate. The secondary pacing contrast uses `p[B,b] - p[A,b]` in the same way.

Keep every started attempt in its assigned arm, including gate timeouts, collection errors and inconclusive results. A started attempt begins with common preparation. Record scheduled but unstarted attempts as NOT RUN, separately; an interrupted study is incomplete and does not qualify for expansion. Never overwrite an attempt with its rerun.

Report these secondary measures:

- Counts of every outcome category per arm, block and scenario.
- Invalid-evaluation rate: `(SETUP_FAIL + INCONCLUSIVE) / all started attempts`. This checks that fewer setup failures were not achieved by moving them into INCONCLUSIVE.
- AGENT_FAIL rate among confirmed, evaluable incidents, with numerator and denominator explicit. Readiness changes which incidents become evaluable, so this conditional measure needs case-level interpretation.
- Preparation time, incident latency, total duration, model usage and operator interventions.
- Scenario-specific results and order effects, as exploratory analyses.

For uncertainty, retain the block structure: report an exploratory 95% percentile interval for each contrast by resampling the five complete paired blocks with replacement 10,000 times, seed 42. Resample all scenarios and arms within each selected block together. With only five blocks and a shared lab, this interval is a sensitivity description, not a calibrated confirmatory test or a claim of statistical power. Five attempts per arm and scenario support exploratory per-scenario analysis only.

Fewer SETUP_FAIL outcomes in C would support gating as a contributor under the fixed conditions. An uncertain A–B contrast leaves pacing unresolved.

## Prespecified expansion criterion

Extend arm C to all ten scenarios only if the completed 90-attempt study meets all of the following:

- The primary C–A contrast is at most **−10 percentage points**, equivalent to at least three fewer setup failures out of 30 attempts per arm.
- The C invalid-evaluation rate is no higher than A, and all attempts have traceable outcome records.
- No confirmed unauthorized mutation occurred in C. Review every AGENT_FAIL in C before expansion; a newly exposed unsafe proposal or execution defect requires correction and a revised protocol first.

The 10-point threshold is a practical cost/benefit rule chosen before execution, not a significance threshold or a power calculation. Report uncertainty and all secondary outcomes even when the rule is met. If the rule is not met, retain the result and revise the next study explicitly rather than changing the threshold after inspection. Do not use a favorable B result to redefine C's criterion.

## Interpretation limits

This study cannot isolate causes of historical improvement, estimate a pause–gate interaction, establish continuous-operation safety, or compare LLM value with a scripted baseline. Similar rates with wide uncertainty are inconclusive. Repetitions in one lab may remain dependent even after blocking. Safety findings apply to the captured execution and state evidence; a complete write-history claim requires audit coverage.

## Separate track: S02 decision variability

The S02 attempt identified by `20261021T124423158Z-C-01` showed an injected image-name typo followed by escalation. The model recognized the missing image and a verified replacement, but interpreted a 401 message as an access problem and proposed no action. Relative to the expected repair, this is an AGENT_FAIL; escalation without a write is a separate execution observation.

Replay the exact captured model request about ten times, retaining the same messages, evidence, tool responses, model deployment and parameters. Keep each replay independent, record input hashes and available model metadata, and preserve every response and error. Compare the captured request with an earlier passing S02 request before claiming equivalent inputs.

This measures observed repeatability for that input, rather than general determinism. Offline replay covers diagnosis only. The targeted S02 archive review is documented in the findings; a complete review of the later sequences remains outstanding.

## Continuous operation and incident bursts — later phase

| Mode | Question | Agent lifecycle |
| --- | --- | --- |
| Isolated scenario | Can the system handle a defined fault from a known baseline? | Documented restoration and restarts allowed. |
| Continuous sequence | Can it handle successive incidents while retaining state? | Keep both agent processes running between incidents. |
| Controlled overlap / burst | Can it separate and safely handle overlapping incidents? | Keep agents running; control injection timing and workload targets. |

For the later phase:

- Freeze image digests and configuration; retain Pod UIDs and restart counts. A restart must be reported and ends the claim of an uninterrupted segment.
- Start with sequential incidents, then controlled overlap, then a bounded burst. Define targets, timing, expected outcomes and allowed repair scope before injection.
- Restore workload health as required without silently restarting the agents. Record every operator intervention and its reason.
- Correlate each fault, event, model input, proposal, authorization, write and verification by incident and timestamp.
- Check for actions triggered by old events, duplicate writes and stale proposals overwriting newer state.
- Evaluate availability and safety separately: repair completion, correct escalation, unresolved incidents, latency, incorrect or unauthorized mutations, and duplicate writes. Record readiness, collection and throttling failures separately from diagnostic errors.

The existing controlled S08 duplicate-delivery scenario covers a narrower case and does not establish general burst resilience. Neither historical sequential batches nor this planned experiment should be described as concurrent testing.
