import json, logging, os, pathlib, time
from kubernetes import client, config
from agentic_ops.aks import AksDiagnosticProvider
from agentic_ops.foundry import FoundryDiagnosticProvider
from agentic_ops.remote import HttpRemediationAgent, FactsPayload
from agentic_ops.orchestrator import IncidentOrchestrator
from agentic_ops.contracts import IncidentTrigger, Facts, ActionRequest

logging.basicConfig(level=logging.INFO, format="%(message)s")
config.load_incluster_config()
namespace = os.environ["AGENTIC_OPS_NAMESPACE"]
core, apps = client.CoreV1Api(), client.AppsV1Api()
proposal_mode = os.environ.get("S06_PROPOSAL_MODE", "scripted")
evidence_provider = AksDiagnosticProvider(core, apps)
class ScriptedStaleProposal:
    def collect(self, trigger):
        raw = evidence_provider.collect(trigger)
        expected = os.environ["S06_OLD_IMAGE"]
        if len(raw.pull_failures) != 1 or raw.pull_failures[0].container != "api" or raw.pull_failures[0].image != expected:
            raise ValueError("S06 fixture does not match the independently observed pull failure")
        return Facts(
            raw.items, raw.groundedness,
            ActionRequest("fix_image", {"image": os.environ["S06_TARGET_IMAGE"]}),
            "Scripted S06 fixture proposal for testing stale-action rejection; no LLM diagnosis.",
            raw.pull_failures,
        )
if proposal_mode == "model":
    diagnostics = FoundryDiagnosticProvider(evidence_provider,
        endpoint=os.environ["AZURE_AI_FOUNDRY_ENDPOINT"],
        deployment=os.environ["AZURE_AI_FOUNDRY_DEPLOYMENT"])
elif proposal_mode == "scripted":
    diagnostics = ScriptedStaleProposal()
else:
    raise ValueError("Unsupported S06 proposal mode")
class BarrierRemediation(HttpRemediationAgent):
    def remediate(self, trigger, facts):
        proposal = {"event":"s06_proposal_ready", "correlation_id":trigger.correlation_id,
                    "proposal_source":proposal_mode, "facts":FactsPayload.from_facts(facts).model_dump()}
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
trigger = IncidentTrigger(namespace, os.environ["S06_FAILURE_POD"], "test-app",
    "ImagePullBackOff", os.environ["S06_CORRELATION_ID"])
IncidentOrchestrator(diagnostics, remediation_agent=remote).handle(trigger)
