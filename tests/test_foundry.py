import json

import httpx
import pytest

from agentic_ops import Facts
from agentic_ops.foundry import FoundryDiagnosticProvider
from conftest import NEW, make_facts, make_trigger


def with_check(raw, *, status="missing", candidate_status="complete", candidates=(NEW,),
               container=None, image=None):
    from agentic_ops.contracts import Evidence as Item
    failure = raw.pull_failures[0]
    check = Item("authenticated-registry-manifest", json.dumps({
        "container": container or failure.container, "image": image or failure.image,
        "status": status, "candidate_status": candidate_status,
        "verified_candidates": list(candidates),
    }), "acr://verified-check")
    return Facts(raw.items + (check,), raw.groundedness, raw.safe_action, raw.summary,
                 raw.pull_failures)


def provider(reply):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    class Evidence:
        def collect(self, trigger):
            return with_check(make_facts(None, params=None, groundedness=1.0, summary=""))

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


def test_missing_registry_evidence_fails_closed_before_model():
    raw = make_facts(None, params=None)  # one pull failure, no authenticated check at all
    result = guarded_provider(raw).collect(make_trigger())
    assert result.safe_action is None and "unique typo repair" in result.summary


@pytest.mark.parametrize("kwargs", [
    {"image": "acrprod.azurecr.io/other:1.0"},      # check describes a different image
    {"container": "metrics"},                        # check describes a different container
])
def test_registry_check_for_another_image_or_container_fails_closed(kwargs):
    raw = with_check(make_facts(None, params=None), **kwargs)
    result = guarded_provider(raw).collect(make_trigger())
    assert result.safe_action is None


def test_no_failing_container_abstains_before_model():
    from agentic_ops.contracts import Facts as F
    raw = F(make_facts(None, params=None).items, 1.0, pull_failures=())
    result = guarded_provider(raw).collect(make_trigger())
    assert result.safe_action is None and "No container" in result.summary


@pytest.mark.parametrize("proposed", [
    "acrprod.azurecr.io/test-app:1.4.3",             # same repo, different tag
    "acrprod.azurecr.io/test-api:1.4.2",             # another nearby repository
    "evil.azurecr.io/test-app:1.4.2",
])
def test_model_proposal_other_than_unique_verified_candidate_is_rejected(proposed):
    p, _ = provider(json.dumps({"groundedness": 1.0, "summary": "x",
                                "safe_action": {"name": "fix_image", "parameters": {"image": proposed}}}))
    with pytest.raises(ValueError, match="unique verified candidate"):
        p.collect(make_trigger())


def test_system_prompt_has_no_unguarded_fallback_clause():
    assert "registry_checks is absent" not in FoundryDiagnosticProvider._system_prompt()


@pytest.mark.parametrize("candidate", [None, "", "   ", 42, {}])
def test_invalid_unique_candidate_abstains_before_model(candidate):
    raw = with_check(make_facts(None, params=None), candidates=[candidate])
    assert guarded_provider(raw).collect(make_trigger()).safe_action is None
