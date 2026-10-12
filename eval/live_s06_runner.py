import json, logging, os, pathlib, time
from kubernetes import client, config
from agentic_ops.aks import AksDiagnosticProvider
from agentic_ops.foundry import FoundryDiagnosticProvider
from agentic_ops.remote import HttpRemediationAgent, FactsPayload
from agentic_ops.orchestrator import IncidentOrchestrator
from agentic_ops.contracts import IncidentTrigger

logging.basicConfig(level=logging.INFO, format="%(message)s")
config.load_incluster_config()
namespace = os.environ["AGENTIC_OPS_NAMESPACE"]
core, apps = client.CoreV1Api(), client.AppsV1Api()
diagnostics = FoundryDiagnosticProvider(AksDiagnosticProvider(core, apps),
    endpoint=os.environ["AZURE_AI_FOUNDRY_ENDPOINT"],
    deployment=os.environ["AZURE_AI_FOUNDRY_DEPLOYMENT"])
class BarrierRemediation(HttpRemediationAgent):
    def remediate(self, trigger, facts):
        proposal = {"event":"s06_proposal_ready", "correlation_id":trigger.correlation_id,
                    "facts":FactsPayload.from_facts(facts).model_dump()}
        pathlib.Path("/tmp/s06-ready.json").write_text(json.dumps(proposal))
        print(json.dumps(proposal), flush=True)
        deadline = time.monotonic() + 120
        while not pathlib.Path("/tmp/s06-release").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("S06 evaluator did not release the barrier")
            time.sleep(0.25)
        print(json.dumps({"event":"s06_handoff_released","correlation_id":trigger.correlation_id}), flush=True)
        return super().remediate(trigger, facts)
remote = BarrierRemediation(os.environ["AGENTIC_OPS_REMEDIATION_URL"],
    os.environ["AGENTIC_OPS_REMEDIATION_TOKEN"], namespace)
trigger = IncidentTrigger(namespace, os.environ["S06_FAILURE_POD"], "payments-api",
    "ImagePullBackOff", os.environ["S06_CORRELATION_ID"])
IncidentOrchestrator(diagnostics, remediation_agent=remote).handle(trigger)
