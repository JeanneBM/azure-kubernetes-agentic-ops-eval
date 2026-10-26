# S09 controlled live trial
- Verdict: pass
- Outcome: escalated
- Proposal source: scripted
- Fault start UTC: 2026-10-26T16:47:40Z
- Error: 

One functional trial, not a benchmark. See artifacts.json, diagnostic.log,
remediation.log, provenance.json and Deployment snapshots. Agent images are pinned
by runtime digest. Evaluator commit is recorded separately; it is not proof of the
agent image's source commit. Use -PrepareBaseline to rebuild changed application
inputs and reset the known workload before a future trial.
S07 includes the exact Event and actual model request/response body.
S08 delivers duplicates through watcher.process_pod in one controlled process;
this does not cover streaming reconnects, webhooks, restarts or multiple replicas.
S09 and S10 exercise scripted proposals against the real remediation policy.
Snapshot/generation checks show final state, not exhaustive Kubernetes write history.
The evaluator Pod and injected Event are removed; diagnostics remain at replicas=0.
Faulted workload is retained for inspection. Azure resources remain provisioned.
