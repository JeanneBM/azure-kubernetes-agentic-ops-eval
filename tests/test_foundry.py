import json

import httpx
import pytest

from agentic_ops import Facts
from agentic_ops.foundry import FoundryDiagnosticProvider
from conftest import NEW, make_facts, make_trigger


def provider(reply):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    class Evidence:
        def collect(self, trigger):
            return make_facts(None, params=None, groundedness=1.0, summary="")

    p = FoundryDiagnosticProvider(
        Evidence(), endpoint="https://f.openai.azure.com/", deployment="gpt",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        token_provider=lambda: "tok",
    )
    return p, seen


def test_valid_reply_becomes_facts_and_keeps_cluster_read_pull_failures():
    reply = json.dumps({"groundedness": 0.93, "summary": "typo",
                        "safe_action": {"name": "fix_image", "parameters": {"image": NEW}}})
    p, seen = provider(reply)
    facts = p.collect(make_trigger())
    assert facts.groundedness == 0.93 and facts.summary == "typo"
    assert facts.safe_action.parameters["image"] == NEW
    assert facts.pull_failures  # came from the AKS provider, not the model
    assert seen["auth"] == "Bearer tok"
    assert seen["body"]["temperature"] == 0


def test_null_action_is_allowed():
    p, _ = provider(json.dumps({"groundedness": 0.9, "summary": "x", "safe_action": None}))
    assert p.collect(make_trigger()).safe_action is None


def test_lab_audit_records_actual_io_without_authorization_header(monkeypatch, caplog):
    monkeypatch.setenv('AGENTIC_OPS_RECORD_MODEL_IO', '1')
    p, seen = provider(json.dumps({'groundedness': 0.9, 'summary': 'x', 'safe_action': None}))
    with caplog.at_level('INFO', logger='agentic_ops.foundry'):
        p.collect(make_trigger())
    records = [json.loads(record.message) for record in caplog.records
               if record.name == 'agentic_ops.foundry']
    assert records[0]['event'] == 'diagnostic_model_input'
    assert records[0]['payload'] == seen['body']
    assert records[1]['event'] == 'diagnostic_model_response'
    assert records[1]['payload']['choices'][0]['message']['content']
    assert 'Bearer tok' not in caplog.text


def test_lab_audit_is_disabled_by_default(monkeypatch, caplog):
    monkeypatch.delenv('AGENTIC_OPS_RECORD_MODEL_IO', raising=False)
    p, _ = provider(json.dumps({'groundedness': 0.9, 'safe_action': None}))
    with caplog.at_level('INFO', logger='agentic_ops.foundry'):
        p.collect(make_trigger())
    assert not [r for r in caplog.records if r.name == 'agentic_ops.foundry']


@pytest.mark.parametrize("reply", [
    "not json",
    json.dumps({"summary": "no groundedness"}),
    json.dumps({"groundedness": 2, "safe_action": None}),
    json.dumps({"groundedness": 0.9, "safe_action": {"name": "scale", "parameters": {"replicas": "0"}}}),
    json.dumps({"groundedness": 0.9, "safe_action": {"name": "fix_image", "parameters": "oops"}}),
    json.dumps({"groundedness": 0.9, "safe_action": "fix_image"}),
])
def test_contract_violations_raise_value_error(reply):
    p, _ = provider(reply)
    with pytest.raises(ValueError):
        p.collect(make_trigger())


def guarded_provider(raw):
    class Source:
        def collect(self, trigger):
            return raw

    def forbidden(request):
        pytest.fail("Structural abstention must not call the model")

    return FoundryDiagnosticProvider(
        Source(), endpoint="https://f.openai.azure.com", deployment="gpt",
        http_client=httpx.Client(transport=httpx.MockTransport(forbidden)),
        token_provider=lambda: pytest.fail("No model token should be requested"),
    )


def test_two_failures_abstain_before_model_even_with_low_groundedness():
    from agentic_ops.contracts import PullFailure
    raw = make_facts(None, params=None, groundedness=0.0)
    raw = Facts(raw.items, 0.0, pull_failures=(
        raw.pull_failures[0], PullFailure("metrics", NEW)))
    result = guarded_provider(raw).collect(make_trigger())
    assert result.safe_action is None
    assert result.pull_failures == raw.pull_failures


@pytest.mark.parametrize("status,candidate_status,candidates", [
    ("missing", "complete", []),
    ("missing", "complete", [NEW, NEW + "2"]),
    ("missing", "unknown", []),
    ("unknown", "not_checked", []),
    ("exists", "not_checked", []),
])
def test_authenticated_registry_abstention_does_not_depend_on_model(status, candidate_status, candidates):
    from agentic_ops.contracts import Evidence
    raw = make_facts(None, params=None)
    failure = raw.pull_failures[0]
    check = Evidence("authenticated-registry-manifest", json.dumps({
        "container": failure.container, "image": failure.image,
        "status": status, "candidate_status": candidate_status,
        "verified_candidates": candidates,
    }), "acr://verified-check")
    raw = Facts(raw.items + (check,), 1.0, pull_failures=raw.pull_failures)
    result = guarded_provider(raw).collect(make_trigger())
    assert result.safe_action is None
    assert result.items == raw.items
