# Two-Workload PoC Deployment

The supplied manifest runs the PoC as two independently authenticated workloads.

## Handoff timeouts and uncertain execution

Both workloads load the same `agentic-ops-timeouts` ConfigMap. Defaults are
`AGENTIC_OPS_VERIFY_TIMEOUT_SECONDS=120` and
`AGENTIC_OPS_HANDOFF_TIMEOUT_SECONDS=180`. Startup rejects non-finite/non-positive
values and requires handoff to exceed verification by more than 30 seconds.
The HTTP read timeout is the handoff budget; connection, write and pool timeouts
are 10 seconds. This is an inactivity timeout, not a total wall-clock deadline.
The margin allows for policy checks, patching, polling and transport, but does not
guarantee completion if an upstream service stalls. After changing the ConfigMap,
restart both workloads to load the same values.

`action_executed` in the webhook/audit (and `executed` in the handoff) has three
values: `true` means execution was confirmed, `false` means no execution was
reported, and `null` means the handoff outcome could not be confirmed. A timeout,
transport error, non-success HTTP status or malformed response escalates with
`null`, never an inferred `false`. The client does not automatically retry the
remediation POST. Inspect the workload and remediation logs before retrying an
uncertain operation. A verification exception after a confirmed patch preserves
`true` and escalates. Consumers must compare explicitly with `true`/`false` rather
than treating `null` as false; the security runner treats unknown as inconclusive.

Local tests simulate a lost acknowledgement after execution. Live AKS verification
of the longer handoff and sequential incidents without agent restarts is pending.

| Workload | Identity and Kubernetes permissions | External capability |
| --- | --- | --- |
| Diagnostic agent | Read-only access to Pods, Events, ReplicaSets, and Deployments. | Azure AI Foundry inference, read-only ACR manifest evidence, and the authenticated internal remediation handoff. |
| Remediation agent | Read and patch access to Deployments only. | ACR tag validation, Kubernetes rollout verification, and the internal remediation API. It has no Foundry configuration. |

## Required Azure identities

Create two user-assigned identities and two federated credentials:

- diagnostic identity subject: system:serviceaccount:agentic-ops:agentic-ops-diagnostic
- remediation identity subject: system:serviceaccount:agentic-ops:agentic-ops-remediation

Grant Cognitive Services OpenAI User only to the diagnostic identity. Grant registry-scoped AcrPull to both identities: diagnostics reads the failing manifest; remediation independently validates both old and proposed images. Only remediation has Kubernetes patch permission. Remediation must not receive the OpenAI inference role.

Set DIAGNOSTIC_AZURE_CLIENT_ID and REMEDIATION_AZURE_CLIENT_ID when rendering deploy/aks-agentic-ops.yaml.

## Internal handoff

Create the required token Secret before applying the manifest:

~~~sh
kubectl create secret generic agentic-ops-remediation   --namespace agentic-ops   --from-literal=token="$(openssl rand -base64 32)"
~~~

The diagnostic agent sends typed Facts to the cluster-internal remediation Service. The remediation API rejects requests without this token. The NetworkPolicy allows its ingress only from the diagnostic pod label; it also retains the optional webhook ingress.

## Egress boundary

The code and identities prevent the remediation agent from using Foundry or a web-search tool. Standard Kubernetes NetworkPolicy cannot safely express an allowlist for Azure services whose addresses can change without knowing the cluster's egress design. Therefore this portable manifest does not make a false claim of a public-egress block.

Before a production deployment, enforce the final boundary at the network layer: allow remediation egress only to the AKS API, ACR, DNS, and the workload's required Azure identity endpoints, using Azure Firewall, an egress gateway, or a CNI policy with FQDN support. The diagnostic workload may additionally reach the approved research and Foundry endpoints.

## Rollback

Switching AGENTIC_OPS_ROLE back to all-in-one is supported only for local compatibility. The supplied AKS manifest always uses the two-workload design.
