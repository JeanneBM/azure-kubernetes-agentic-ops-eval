import json
from agentic_ops.telemetry import Trace, tool


def test_trace_writes_metadata_and_hashes_only(tmp_path,monkeypatch):
    path=tmp_path/'events.jsonl';monkeypatch.setenv('AGENT_TELEMETRY_FILE',str(path))
    with Trace('diagnostic'):
        tool('kubectl_get',{'secret_argument':'do-not-store-this'})
    raw=path.read_text();events=[json.loads(line) for line in raw.splitlines()]
    assert 'do-not-store-this' not in raw and 'secret_argument' not in raw
    assert [e['type'] for e in events]==['run_started','tool_call','run_finished']
    assert len(events[1]['args_hash'])==64
    assert events[-1]['status']=='success'


def test_failed_run_produces_error_not_success(tmp_path,monkeypatch):
    path=tmp_path/'events';monkeypatch.setenv('AGENT_TELEMETRY_FILE',str(path))
    try:
        with Trace('remediation'): raise RuntimeError('private-provider-body')
    except RuntimeError: pass
    raw=path.read_text()
    assert 'private-provider-body' not in raw
    assert json.loads(raw.splitlines()[-1])['status']=='error'
