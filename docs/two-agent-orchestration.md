# Rationale for the Two-Agent Architecture

## Separation of responsibilities

| Agent | Permissions | Output |
| --- | --- | --- |
| Diagnostic agent | May use internet search and read-only AKS data. | Structured facts, a confidence score, and one remediation proposal. |
| Remediation agent | Has no browser, search capability, or dependency on external results. It receives only the Facts contract. | Independently authorizes the operation, executes it, and verifies the rollout. |

## Why this design

Internet-search output can help diagnose an incident, but it is external and untrusted input. It can be outdated, incorrect, or contain instructions unrelated to the incident. The first agent therefore has no access to the executor and cannot choose the namespace, Deployment, or container.

The second agent is intentionally narrower. It does not use the network or research tools, so a web page or model response cannot expand the operation's scope. It verifies local facts and safety rules: an allowed registry, a small image-name change, the corrected image's existence in ACR, and the correct AKS target.

## Completion condition

An incident has status resolved only when the second agent successfully authorizes the operation, executes it, and independently confirms a healthy rollout. A policy rejection, execution error, infrastructure error, or failed verification by the second agent ends the incident as escalated, with the reason and evidence available for human review.

## Incident deduplication

While an incident is in flight on a namespace/Deployment, every other signal for
that Deployment is answered as a duplicate, including one with a different
failure fingerprint. It is not queued: the watcher delivers it again on the pod's
next status change (image-pull backoff reaches five minutes), and webhook callers
must retry. Once handling finishes, the outcome is kept per (Deployment,
fingerprint), so the cooldown suppresses only matching fingerprints. Late events
from an earlier rollout therefore stay duplicates after a newer rollout on the
same Deployment was handled. Both AKS app builders resolve the fingerprint from
live pod and ReplicaSet reads before invoking diagnostics, for watcher and webhook
requests alike. Webhook callers and model output cannot set this context.

If that context cannot be read, nothing is diagnosed or executed. The webhook
answers 422 when the pod or its ReplicaSet no longer exists, 409 when the pod is
no longer owned by the requested Deployment, and 502 for other lookup failures.
The watcher skips the first two cases with a log line; other lookup failures
are logged by its per-event exception handler, which continues consuming events.

The fingerprint includes the Deployment owner's UID, ReplicaSet UID and rollout
revision, pod-template hash, and sorted failing container/image pairs. Replica
names and correlation IDs are excluded. A new image failure or rollout revision
can therefore start another incident without restarting the agent. The revision
also distinguishes reintroducing the same bad image when Kubernetes reuses a
ReplicaSet. Lingering old-pod events keep the old revision after remediation;
the current Deployment generation is deliberately not used.

Each completed (Deployment, fingerprint) entry expires after its own cooldown
(15 minutes by default) and is pruned on the next managed trigger; in-flight
entries are retained however long they run. Callers that
construct an orchestrator without a cluster resolver retain the legacy
workload-only cooldown unless they supply a fingerprint. Missing ReplicaSet
revision annotations reduce recurrence detection to the other identity fields.
This remains process-local state, not distributed deduplication across replicas.

Local regression tests cover different failures, repeated notifications, reused
rollouts, interleaved notifications from two rollouts, concurrent delivery,
context-lookup failures, and both event entry points. A live AKS check with
two sequential incidents and no agent restart is still required. Existing live
test preparation scripts retain their restarts until that check is completed.
