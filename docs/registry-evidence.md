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
does not identify the intended replacement: the model may still abstain.

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
