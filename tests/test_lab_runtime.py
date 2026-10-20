"""Execute lifecycle guards against deterministic local native-command substitutes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PWSH = os.environ.get('PWSH_BIN') or shutil.which('pwsh')
pytestmark = pytest.mark.skipif(not PWSH, reason='PowerShell 7 required')
ROOT = Path(__file__).parents[1]


def execute(tmp_path, body, env=None):
    script = tmp_path / 'check.ps1'
    helper = ROOT / 'scripts/environment/lab-runtime.ps1'
    script.write_text("$ErrorActionPreference='Stop'\n. '" + str(helper) + "'\n" + body)
    return subprocess.run([PWSH, '-NoProfile', '-File', str(script)],
                          capture_output=True, text=True, env=env, timeout=20)


def test_ready_guard_rejects_zero_stale_and_terminating_only_pods(tmp_path):
    body = r'''
$d = '{"metadata":{"generation":3},"spec":{"replicas":1,"template":{"spec":{"containers":[{"image":"r/agent:v1"}]}}},"status":{"observedGeneration":3,"replicas":1,"updatedReplicas":1,"readyReplicas":1,"availableReplicas":1}}' | ConvertFrom-Json
$p = '{"items":[{"metadata":{"deletionTimestamp":null},"status":{"phase":"Running","containerStatuses":[{"ready":true,"image":"r/agent:v1"}]}}]}' | ConvertFrom-Json
if (-not (Test-LabAgentReady $d $p)) { throw 'Healthy agent rejected' }
$d.spec.replicas=0
if (Test-LabAgentReady $d $p) { throw 'Zero replicas accepted' }
$d.spec.replicas=1; $d.status.observedGeneration=2
if (Test-LabAgentReady $d $p) { throw 'Stale generation accepted' }
$d.status.observedGeneration=3; $p.items[0].metadata.deletionTimestamp='now'
if (Test-LabAgentReady $d $p) { throw 'Terminating-only pod accepted' }
$p.items[0].metadata.deletionTimestamp=$null; $p.items[0].status.containerStatuses[0].image='r/agent:old'
if (Test-LabAgentReady $d $p) { throw 'Old image accepted' }
'''
    result = execute(tmp_path, body)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('operation,failures,expected_calls,success', [
    ('logs', 2, 3, True), ('logs', 9, 4, False), ('patch', 2, 1, False)])
def test_only_logs_retry_and_exhaustion_is_an_error(tmp_path, operation, failures, expected_calls, success):
    counter = tmp_path / 'count'
    executable = tmp_path / 'kubectl'
    executable.write_text('#!' + sys.executable + '\n' + f'''
import pathlib,sys
p=pathlib.Path({str(counter)!r}); n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n))
if n <= {failures}: sys.exit(1)
print('captured-log')
''')
    executable.chmod(0o755)
    result = execute(tmp_path, f"Invoke-LabKubectl -Executable '{executable}' -Kubeconfig offline -Arguments @('{operation}','pod') -RetryDelaySeconds 0")
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    assert int(counter.read_text()) == expected_calls
    if success:
        assert 'captured-log' in result.stdout


def test_batch_runs_each_scenario_in_a_fresh_process_and_keeps_results(tmp_path):
    root = tmp_path / 'repo'
    (root / 'scripts/tests').mkdir(parents=True)
    (root / 'scripts/packaging').mkdir()
    (root / '.local').mkdir()
    shutil.copy(ROOT / 'scripts/tests/S01-S10-tests.ps1', root / 'scripts/tests/S01-S10-tests.ps1')
    (root / '.local/rg-agentic-ops-lab.json').write_text(json.dumps({'subscriptionId':'offline'}))
    fixture = r'''
param([int]$TimeoutSeconds,[string]$EvidenceRoot,[switch]$PrepareBaseline)
$ErrorActionPreference='Stop'
if (Get-Variable poison -Scope Global -ErrorAction SilentlyContinue) { throw 'Inherited parent state' }
$global:poison='child-state'
$id=([IO.Path]::GetFileNameWithoutExtension($PSCommandPath) -replace 'test-','').ToUpper()
$dir=Join-Path $EvidenceRoot 'one-trial'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
@{scenario=$id;verdict='pass';outcome='fixture';processId=$PID} | ConvertTo-Json | Set-Content (Join-Path $dir 'result.json')
Compress-Archive -Path (Join-Path $dir '*') -DestinationPath (Join-Path $EvidenceRoot "$id-offline-anonymized.zip")
'''
    for i in range(1, 11):
        (root / f'scripts/tests/test-s{i:02}.ps1').write_text(fixture)
    (root / 'scripts/packaging/package-evidence.ps1').write_text(r'''
param([string]$SourceDirectory,[string]$DestinationPath)
New-Item -ItemType Directory -Force -Path (Split-Path $DestinationPath -Parent) | Out-Null
Compress-Archive -Path (Join-Path $SourceDirectory '*') -DestinationPath $DestinationPath
''')
    bindir = tmp_path / 'bin'; bindir.mkdir()
    az = bindir / 'az'; az.write_text('#!/bin/sh\necho true\n'); az.chmod(0o755)
    entry = tmp_path / 'parent.ps1'
    entry.write_text("$global:poison='parent-state'\n& '" + str(root / 'scripts/tests/S01-S10-tests.ps1') + "'\n")
    result = subprocess.run([PWSH, '-NoProfile', '-File', str(entry)],
        env={**os.environ,'PATH':str(bindir)+os.pathsep+os.environ['PATH']},
        capture_output=True,text=True,timeout=50)
    assert result.returncode == 0, result.stdout + result.stderr
    batch = next((root / '.local/evidence/batches').iterdir())
    summary = json.loads((batch / 'summary.json').read_text())
    assert len(summary) == 10 and all(r['verdict'] == 'pass' for r in summary)
    processes = [json.loads(p.read_text())['processId'] for p in batch.rglob('result.json')]
    assert len(set(processes)) == 10
    assert len(list(batch.rglob('runner-console.log'))) == 10
