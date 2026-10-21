# Pacing and readiness replication plan

Status: **planned, not executed.** This document defines a prospective experiment; it contains no experimental results.

## Question

With the environment, runner and configuration held constant, does a fixed pause or an explicit readiness gate improve the reliability of sequential scenario execution?

The historical runs cannot isolate the effect of pauses because scripts, preparation checks and the execution environment also changed. This experiment tests the proposed mechanisms prospectively; it does not retrospectively identify which historical change caused the improvement.

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
- Reference scenarios: S01 and S02. S01 was stable in the reported runs; S02 is included specifically because a later sequence exposed decision variability.

Three arms × six scenarios × five repetition blocks = **90 attempts**, including failed setup and inconclusive attempts. Within each block, run all three arms with the same scenario order. Randomize and counterbalance arm order across blocks, using a recorded seed, so one arm does not consistently run first or last.

First run a small pilot to verify that arms differ only as specified and that evidence collection works. Pilot attempts may count toward the 90 only if the protocol remains unchanged; otherwise retain them separately. Define the expansion criterion before interpreting results. Extend beyond this exploratory study only if the evidence and remaining uncertainty justify the cost.

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

## Analysis and interpretation

- Report counts by category, arm and scenario. Keep every attempt in the end-to-end denominator; do not replace failed attempts with successful reruns.
- Also report agent outcomes conditional on a confirmed, evaluable fault, with the denominator explicit. Setup success and agent success answer different questions.
- Report uncertainty. With five attempts per arm and scenario, estimates are exploratory. Wilson intervals may describe proportions, but do not assume that shared-lab repetitions are independent; retain block and order information.
- Fewer SETUP_FAIL outcomes in C would support readiness gating as a contributor under the tested conditions. It would not prove that readiness was the sole historical cause.
- Similar A and B results with wide uncertainty mean the study is inconclusive about pacing, not that pacing has no effect.
- Compare preparation time, incident latency, total elapsed time and model usage alongside outcomes. A pause can improve apparent completion while increasing total duration.
- Inspect whether any apparent improvement depends on a particular scenario or execution order before pooling results.

## Separate track: S02 decision variability

The S02 attempt identified by `20261021T124423158Z-C-01` showed an injected image-name typo followed by escalation. The model recognized the missing image and a verified replacement, but interpreted a 401 message as an access problem and proposed no action. Relative to the expected repair, this is an AGENT_FAIL; escalation without a write is a separate execution observation.

Replay the exact captured model request about ten times, retaining the same messages, evidence, tool responses, model deployment and parameters. Keep each replay independent, record input hashes and available model metadata, and preserve every response and error. Compare the captured request with an earlier passing S02 request before claiming equivalent inputs.

This measures observed repeatability for that input. Ten identical decisions would not establish general determinism. Offline replay also does not test live collection, authorization or repair execution. Complete archives for the later sequence still require review.

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
