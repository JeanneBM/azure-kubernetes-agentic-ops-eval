# Authenticated registry evidence for image-pull diagnosis

The S01-S10 batch recorded on 2026-10-16 exposed an ambiguity: Kubernetes reported
both NotFound and an anonymous-token 401 for a misspelled image. In S01 and S02 the
model returned no action, so the expected recovery failed. S07 safely abstained.
Those historical outcomes remain unchanged.

Before model inference, RegistryEvidenceProvider now checks the exact failing
image using diagnostic Workload Identity and registry-scoped AcrPull. A manifest
200 means exists; 404 means missing. Registry auth/network errors produce unknown
or propagate to incident escalation; they are never interpreted as missing.
Only one cluster-reported failing container is probed. Namespace and registry
allowlists are checked before registry requests. Events and model output cannot
select another registry for this read.

The model receives the structured authenticated-registry-manifest evidence plus
the original Kubernetes evidence. A registry lookup uses diagnostic credentials,
so it does not establish that the kubelet has pull access. An absent image also
does not identify the intended replacement. When it is absent, diagnostics reads
the registry repository catalog and checks nearby repository spellings with the
same tag. Only manifest-confirmed existing images are included in
`verified_candidates`. Candidate discovery does not use the evaluator's intended
image or hardcode the test-app replacement.

Discovery requires a complete catalog of fewer than 100 repositories, at most ten
nearby spellings, and successful authenticated manifest checks. Pagination,
authorization errors, invalid inventory and partial lookup failures produce
`candidate_status=unknown` with no candidates. Repository distance uses the same
maximum of two as the default remediation policy. This discovery fixes repository
spelling candidates at the unchanged tag; it does not enumerate alternate tags.
The model is instructed to propose the sole verified candidate and abstain on
empty, unknown or ambiguous discovery. It can still abstain, and that remains
visible in the live outcome rather than being overridden by a scripted repair.

This is additional evidence, not a fallback that automatically repairs when the
model returns null. Remediation keeps its own credentials and independently
checks the original and proposed images, policy, stale state and rollout.
No Kubernetes write permission is added to diagnostics. S07 uses the same evidence
provider as the production diagnostic workload; S08-S10 keep scripted proposals.

For an existing recorded lab, preparation grants the diagnostic read-only role
and rebuilds changed application inputs. Azure role propagation may take time;
unknown results must be investigated rather than treated as successful diagnosis.
Run S01 and S02 again after updating the checkout, then rerun security scenarios
to evaluate this changed version. Offline tests establish adapter behavior only;
they do not establish a new live recovery rate.

## Structured model input and lab audit

The model request includes `pull_failures` and `registry_checks` as structured JSON
fields in addition to the original evidence strings. The decision procedure counts
failing containers rather than healthy sidecars and gives authenticated candidate
checks precedence over the mixed anonymous-token 401 message. Model abstention is
still recorded; no deterministic replacement is injected into a null response.

The disposable lab enables `AGENTIC_OPS_RECORD_MODEL_IO=1` during setup/preparation.
Diagnostic logs then contain `diagnostic_model_input` and `diagnostic_model_response`
with correlation IDs and the actual request body/response, excluding authorization
headers. These are separate from the minimal monitoring telemetry. They may contain
raw workload evidence; package through the anonymizer before publishing. Omit or
disable this flag outside the evidence-collection lab. Audit is off by default in
the provider itself.

## Fail-closed diagnostic gate and tag rule

- The model is consulted only when exactly one container fails to pull and an authenticated
  registry check for that exact container and image reports `status: missing`,
  `candidate_status: complete` and exactly one verified candidate. Missing, mismatched or
  ambiguous evidence abstains before the model; no failing container also abstains.
- The model may only select that candidate. Any other image is a contract violation
  (`proposed image is not the unique verified candidate`) and is escalated.
- `SelfCurePolicy` requires the corrected image to keep the current tag. A tag names a
  version; changing it (`1.4.3` -> `1.4.2`, `v1.10` -> `v1.1`) is not a typo fix.
