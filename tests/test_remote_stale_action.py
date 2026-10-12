from fastapi.testclient import TestClient

from agentic_ops.agents import SafeRemediationAgent
from agentic_ops.remote import FactsPayload, HandoffPayload, create_remediation_app
from agentic_ops.safety import StaleActionError
from conftest import FakeExecutor, make_facts, make_policy, make_trigger


def test_stale_executor_refusal_survives_http_handoff_without_execution():
    class StaleExecutor(FakeExecutor):
        def execute(self, action):
            raise StaleActionError("Deployment image changed since diagnosis; refusing to overwrite it")

    executor = StaleExecutor()
    app = create_remediation_app(SafeRemediationAgent(make_policy(), executor), agent_token="test-token")
    trigger = make_trigger()
    payload = HandoffPayload(
        namespace=trigger.namespace, pod=trigger.pod, workload=trigger.workload,
        reason=trigger.reason, correlation_id=trigger.correlation_id,
        facts=FactsPayload.from_facts(make_facts()),
    )
    with TestClient(app) as client:
        response = client.post("/internal/v1/remediate", json=payload.model_dump(),
                               headers={"X-Agent-Token": "test-token"})
    assert response.status_code == 200
    assert response.json()["executed"] is False
    assert response.json()["successful"] is False
    assert response.json()["action"] is None
    assert "Deployment image changed since diagnosis" in response.json()["reason"]
    assert executor.actions == []
