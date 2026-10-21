# R01: same symptom, different readiness failures

**Prepared synthetic diagnosis comparison, not a live AKS result.** This is a
new experimental diagnosis prompt. It does not measure the deployed image-pull
agent and does not change its policy or permissions. No Kubernetes API calls,
fault injection, rollback or remediation are performed by this harness.

All six cases have the same symptom: the application becomes unready after a
deployment. Both methods receive exactly the same evidence JSON. The runner
removes the case identifier; only the scorer loads the separate rubric. The
diagnosis and recommendation labels are intentionally published to both methods.

| Case | Evidence to combine | Expected diagnosis / review |
| --- | --- | --- |
| A | Application exception plus paired version comparison under the same config/dependency state | Release regression / review rollback |
| B | Missing-variable log plus Deployment configuration diff | Missing configuration / review configuration |
| C | Dependency timeout, workload-network check and previous version failing on the same dependency | Dependency unavailable / investigate dependency |
| D | Measured 85-second startup versus a 30-second probe budget and early liveness restarts | Startup probe budget / review probes |
| E | Independent evidence for both configuration and dependency failures | Ambiguous / escalate |
| F | Common symptom with no discriminating evidence | Insufficient evidence / escalate |

Cases use neutral identifiers in the files. Some evidence represents **prior
operator measurements** (paired version checks and startup with liveness disabled).
The harness supplies those measurements equally to both methods; it does not
credit the LLM with collecting them autonomously.

## Run offline (no cloud cost)

From the repository root in Git Bash, PowerShell or another shell:

```sh
python -m eval.readiness.benchmark --mode baseline
```

The rule baseline is transparent Python over the published evidence schema.
It is deliberately capable of solving all six cases, rather than a weak
comparison designed to make the model win. Passing these fixed fixtures does
not demonstrate an advantage for LLM reasoning. The structured input makes
this a small contract/smoke benchmark, not yet a difficult generalization test.

## Compare with real Azure OpenAI inference

Use Python 3.11+ and the repository dependencies:

```sh
python -m pip install -c constraints.txt -e .
az login --use-device-code
python -m eval.readiness.benchmark --mode compare --use-lab-state --repetitions 3 --pause-seconds 5
```

`--use-lab-state` reads endpoint and deployment from the existing
`.local/rg-agentic-ops-lab.json`. Alternatively supply `--endpoint` and
`--deployment`, or `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT`.
The CLI account needs model-inference access (the deployed workload identity
does not give that access to your local account automatically).

Comparison makes **6 × repetitions billable model requests**. It does not create
Azure resources. Temperature is zero, but deterministic model output is not
assumed. Each call receives fresh messages: this is not a continuous-state or
burst-load test. Calls are sequential; there are no automatic retries that
could conceal transient failures.

## Results and interpretation

Each invocation writes a new directory under `.local/readiness-eval/`:

- `attempt-*/input.json`: exact public evidence shared by both methods.
- `attempt-*/baseline.json` and `llm.json`: parsed prediction, outcome, duration,
  and model/usage metadata when returned.
- `results.jsonl`, `summary.md`: all attempts, including errors.
- `manifest.json`, `system-prompt.txt`: source revision, file and prompt hashes,
  seed, repetition count and prompt text.

PASS requires the expected diagnosis, recommendation and citation of the required
evidence groups. Explanations are retained for review, not automatically judged
for semantic truth. A wrong but syntactically valid answer is FAIL; transport,
authentication or invalid-schema responses are ERROR. Exit codes: 0 all PASS,
1 at least one FAIL, 2 at least one ERROR. Input hashes must match within each pair.
Reports do not overwrite an existing directory. Raw outputs remain local and
should be reviewed and packaged with the existing anonymization tools before
publication. No live result is claimed by committing this code.

Latency includes authentication/request overhead for the LLM. Token usage is
recorded when returned; monetary cost requires actual deployment pricing.
Recommendation correctness is not proof of execution safety: nothing executes.
Do not pool these results with S01–S10 live operational success counts.

Before drawing conclusions about agent value, freeze the baseline and prompt,
add independently authored held-out cases (including misleading logs and
missing/contradictory evidence), and compare on the same blinded inputs.
Do not tune on the held-out set or give only the LLM extra evidence.
Repeated runs over these six fixed cases measure repeatability, not generalization.

## Next stage: live evidence

A separate future runner should inject the four faults into an isolated test
workload, collect logs/configuration/events and paired observations, and verify
the injected condition independently. It must mark unobserved faults inconclusive,
give both methods the same captured bundle, preserve every attempt and avoid
restarting the operational agents when testing continuous operation. That runner
and any policy-controlled new remediation actions are **not implemented here**.

## Offline checks

```sh
python -m unittest discover -s tests -p test_readiness_benchmark.py -v
```
