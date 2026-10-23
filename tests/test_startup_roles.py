"""Startup wiring must preserve the diagnostic/write capability boundary."""
from unittest.mock import Mock

import pytest
from kubernetes import client, config
from agentic_ops import split_app, web
from agentic_ops import acr, aks, foundry, orchestrator, watcher


@pytest.fixture
def wiring(monkeypatch):
    for key, value in {
        'AGENTIC_OPS_NAMESPACE': 'test-app',
        'AGENTIC_OPS_ALLOWED_REGISTRIES': 'acr.azurecr.io,,',
        'AGENTIC_OPS_REMEDIATION_TOKEN': 'fixture',
        'AGENTIC_OPS_REMEDIATION_URL': 'http://remediation',
        'AZURE_AI_FOUNDRY_ENDPOINT': 'https://model.invalid',
        'AZURE_AI_FOUNDRY_DEPLOYMENT': 'fixture',
    }.items():
        monkeypatch.setenv(key, value)
    for key in ('AGENTIC_OPS_VERIFY_TIMEOUT_SECONDS', 'AGENTIC_OPS_HANDOFF_TIMEOUT_SECONDS', 'AGENTIC_OPS_WEBHOOK_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    mocks = {}
    for module, name in [(config, 'load_incluster_config'), (client, 'CoreV1Api'),
                         (client, 'AppsV1Api'), (acr, 'AcrRegistry'),
                         (acr, 'RegistryEvidenceProvider'), (aks, 'AksDiagnosticProvider'),
                         (aks, 'AksActionExecutor'), (foundry, 'FoundryDiagnosticProvider'),
                         (watcher, 'PodWatcher'), (orchestrator, 'IncidentOrchestrator')]:
        mocks[name] = Mock()
        monkeypatch.setattr(module, name, mocks[name])
    return mocks


def test_remediation_startup_never_constructs_model_or_watcher(wiring, monkeypatch):
    monkeypatch.setenv('AGENTIC_OPS_ROLE', 'remediation')
    app = split_app.build_app()
    assert any(route.path == '/internal/v1/remediate' for route in app.routes)
    wiring['AksActionExecutor'].assert_called_once()
    wiring['FoundryDiagnosticProvider'].assert_not_called()
    wiring['PodWatcher'].assert_not_called()
    wiring['AksDiagnosticProvider'].assert_not_called()


def test_diagnostic_startup_uses_remote_executor_only(wiring, monkeypatch):
    monkeypatch.setenv('AGENTIC_OPS_ROLE', 'diagnostic')
    remote = Mock()
    create = Mock()
    monkeypatch.setattr(split_app, 'HttpRemediationAgent', remote)
    monkeypatch.setattr(split_app, 'create_app', create)
    assert split_app.build_app() is create.return_value
    wiring['AksActionExecutor'].assert_not_called()
    wiring['FoundryDiagnosticProvider'].assert_called_once()
    remote.assert_called_once_with('http://remediation', 'fixture', 'test-app',
                                   handoff_timeout=180, verify_timeout=120)
    assert create.call_args.kwargs['webhook_token'] is None
    assert create.call_args.kwargs['watcher'] is wiring['PodWatcher'].return_value


def test_legacy_startup_disables_webhook_without_token(wiring, monkeypatch, caplog):
    create = Mock()
    monkeypatch.setattr(web, 'create_app', create)
    assert web.build_app() is create.return_value
    assert create.call_args.kwargs['webhook_token'] is None
    assert 'webhook is disabled' in caplog.text


def test_all_in_one_delegates_to_legacy(monkeypatch):
    monkeypatch.delenv('AGENTIC_OPS_ROLE', raising=False)
    legacy = Mock()
    monkeypatch.setattr(split_app, 'build_legacy_app', legacy)
    assert split_app.build_app() is legacy.return_value


def test_unknown_role_is_rejected(wiring, monkeypatch):
    monkeypatch.setenv('AGENTIC_OPS_ROLE', 'typo')
    with pytest.raises(ValueError, match='AGENTIC_OPS_ROLE'):
        split_app.build_app()
    wiring['AksActionExecutor'].assert_not_called()
    wiring['FoundryDiagnosticProvider'].assert_not_called()
