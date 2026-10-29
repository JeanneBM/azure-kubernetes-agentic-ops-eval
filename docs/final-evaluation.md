# Final evaluation

**Status: closed on 29 October 2026 without human review.** Read the
[final report](../eval/evidence/final/trials/evaluation-report-2026-10-26.md)
and [closeout record](closeout.md). The procedure below is retained for reference;
this closeout does not claim that every validation requirement was satisfied.

Use the [full one-by-one campaign](full-evaluation.md) for the complete required
A/C protocol. It prepares 98 trials with five repetitions of S01-S08 per variant,
controlled S09/S10, live K01-K03, offline P01-P08, handoff and infrastructure checks.
No live result is implied by the implementation.

The [legacy S01-S10 launcher](test-sequence.md) remains a shorter functional
smoke sequence. It is not a substitute for the repeated A/C campaign.

## K02 safety finding

The previous K02 fixture demonstrated that image existence and edit distance
could authorize a different service. The gate now requires an independently
configured intended image for each workload/container. Missing or conflicting
intent refuses execution. K02 is a normal passing refusal regression test;
the expected-failure marker has been removed after implementing this restriction.
The new image and policy mapping still require live deployment and validation.

## Closeout

Keep all attempts and raw redacted evidence, complete the per-trial human review,
report failed/inconclusive/unrun cases, and verify cleanup. A retry does not erase
an earlier failed safety trial. Optional no-policy/model-size/human comparisons
remain follow-up studies, not claims made by this campaign.
