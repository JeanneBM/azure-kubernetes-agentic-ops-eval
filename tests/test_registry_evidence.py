import json

import httpx
import pytest

from agentic_ops.acr import AcrRegistry, RegistryError, RegistryEvidenceProvider
from agentic_ops.contracts import Evidence, Facts, PullFailure
from agentic_ops.foundry import FoundryDiagnosticProvider
from agentic_ops.safety import PolicyViolation, parse_image
from conftest import FakeDiagnostics, FakeRegistry, OLD, NEW, make_facts, make_trigger, make_policy


def enrich(raw, registry, **kwargs):
    if not hasattr(registry, "candidates"):
        registry.candidates = lambda image: ()
    return RegistryEvidenceProvider(FakeDiagnostics(raw), registry,
                                   namespace='test-app',
                                   allowed_registries=['acrprod.azurecr.io'], **kwargs)


@pytest.mark.parametrize('existing,status', [([], 'missing'), ([OLD], 'exists')])
def test_manifest_status_is_independent_of_kubelet_message(existing, status):
    raw = make_facts(None)
    raw = Facts(raw.items + (Evidence('pod-events', 'NotFound; anonymous token: 401 Unauthorized',
                                    'k8s://events/test-app/pod'),), 1, pull_failures=raw.pull_failures)
    registry = FakeRegistry(existing)
    result = enrich(raw, registry).collect(make_trigger())
    data = json.loads(result.items[-1].value)
    assert data['status'] == status
    assert data['kubelet_access'] == 'not_verified'
    assert registry.calls == [OLD]
    assert result.items[:-1] == raw.items
    assert result.pull_failures == raw.pull_failures
    assert result.safe_action is None


@pytest.mark.parametrize('error', ['401', '403', 'timeout'])
def test_unavailable_registry_is_unknown_not_missing(error):
    result = enrich(make_facts(None), FakeRegistry(error=RegistryError(error))).collect(make_trigger())
    assert json.loads(result.items[-1].value)['status'] == 'unknown'
    assert result.safe_action is None


def test_foreign_registry_is_never_contacted():
    registry = FakeRegistry()
    raw = make_facts(None, failures=(PullFailure('api', 'attacker.example.invalid/app:v1'),))
    with pytest.raises(PolicyViolation):
        enrich(raw, registry).collect(make_trigger())
    assert registry.calls == []


def test_foreign_namespace_is_rejected_before_collection():
    source = FakeDiagnostics(make_facts(None))
    provider = RegistryEvidenceProvider(source, FakeRegistry(), namespace='test-app',
                                        allowed_registries=['acrprod.azurecr.io'])
    with pytest.raises(PolicyViolation):
        provider.collect(make_trigger(namespace='kube-system'))
    assert source.calls == 0


@pytest.mark.parametrize('failures', [(), (PullFailure('api', OLD), PullFailure('metrics', OLD))])
def test_no_failure_or_ambiguous_failure_is_not_selected(failures):
    raw = make_facts(None, failures=failures)
    registry = FakeRegistry()
    assert enrich(raw, registry).collect(make_trigger()) == raw
    assert registry.calls == []


def test_foundry_receives_authenticated_evidence_and_remediation_rechecks():
    diagnostic_registry = FakeRegistry([NEW])
    diagnostic_registry.candidates = lambda image: (parse_image(NEW),)
    observed = {}

    def model(request):
        observed.update(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'groundedness': 0.9, 'summary': 'typo candidate',
            'safe_action': {'name': 'fix_image', 'parameters': {'image': NEW}},
        })}}]})

    provider = FoundryDiagnosticProvider(enrich(make_facts(None), diagnostic_registry),
        endpoint='https://model.example', deployment='model', token_provider=lambda: 'offline',
        http_client=httpx.Client(transport=httpx.MockTransport(model)))
    facts = provider.collect(make_trigger())
    evidence = json.loads(observed['messages'][1]['content'])['evidence']
    assert json.loads(evidence[-1]['value'])['status'] == 'missing'
    assert json.loads(evidence[-1]['value'])['verified_candidates'] == [NEW]
    assert diagnostic_registry.calls == [OLD]
    independent_registry = FakeRegistry([OLD, NEW])  # Changed after diagnosis.
    with pytest.raises(PolicyViolation, match='Current image exists'):
        make_policy(independent_registry).authorize(make_trigger(), facts)
    assert independent_registry.calls == [OLD]


def catalog_registry(repositories, *, catalog_status=200, link=None, manifest_status=None):
    calls = []

    class Credential:
        def get_token(self, scope):
            return type('Token', (), {'token': 'offline'})()

    def handler(request):
        calls.append(request)
        if request.url.path == '/oauth2/exchange':
            return httpx.Response(200, json={'refresh_token': 'offline'})
        if request.url.path == '/oauth2/token':
            return httpx.Response(200, json={'access_token': 'offline'})
        if request.url.path == '/v2/_catalog':
            assert b'registry%3Acatalog%3A%2A' in next(
                r.content for r in reversed(calls[:-1]) if r.url.path == '/oauth2/token')
            return httpx.Response(catalog_status, json={'repositories': repositories},
                                  headers={'Link': link} if link else {})
        assert request.method == 'HEAD'
        return httpx.Response((manifest_status or {}).get(request.url.path, 404))

    return AcrRegistry(credential=Credential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler))), calls


def test_catalog_delivers_verified_candidate_evidence():
    registry, calls = catalog_registry(['test-app', 'agentic-ops'], manifest_status={
        '/v2/test-app/manifests/1.4.2': 200})
    raw = make_facts(None)
    result = RegistryEvidenceProvider(FakeDiagnostics(raw), registry,
        namespace='test-app', allowed_registries=['acrprod.azurecr.io']).collect(make_trigger())
    evidence = json.loads(result.items[-1].value)
    assert evidence['status'] == 'missing'
    assert evidence['candidate_status'] == 'complete'
    assert evidence['verified_candidates'] == [NEW]
    assert result.safe_action is None  # Candidate discovery never executes or replaces model refusal.
    assert all(r.url.host == 'acrprod.azurecr.io' for r in calls)
    assert not any('/v2/agentic-ops/' in r.url.path for r in calls)


@pytest.mark.parametrize('kwargs', [
    {'catalog_status': 401}, {'catalog_status': 403}, {'catalog_status': 500},
    {'link': '<https://attacker.example.invalid/page>; rel="next"'},
    {'repositories': ['../oauth2/token']}, {'repositories': ['test-app'] * 100},
    {'manifest_status': {'/v2/test-app/manifests/1.4.2': 401}},
])
def test_incomplete_or_unauthorized_discovery_never_returns_a_candidate(kwargs):
    options = {'repositories': ['test-app']}
    options.update(kwargs)
    registry, calls = catalog_registry(**options)
    result = RegistryEvidenceProvider(FakeDiagnostics(make_facts(None)), registry,
        namespace='test-app', allowed_registries=['acrprod.azurecr.io']).collect(make_trigger())
    evidence = json.loads(result.items[-1].value)
    assert evidence['candidate_status'] == 'unknown'
    assert evidence['verified_candidates'] == []
    assert all(r.url.host == 'acrprod.azurecr.io' for r in calls)


def test_ambiguous_candidates_are_preserved_not_arbitrarily_selected():
    registry, _ = catalog_registry(['test-app', 'tset-api'], manifest_status={
        '/v2/test-app/manifests/1.4.2': 200, '/v2/tset-api/manifests/1.4.2': 200})
    candidates = registry.candidates(parse_image(OLD))
    assert {str(c) for c in candidates} == {NEW, 'acrprod.azurecr.io/tset-api:1.4.2'}
