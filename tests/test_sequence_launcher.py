"""Run the real PowerShell launcher against harmless child-script fixtures."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PWSH = shutil.which('pwsh')
pytestmark = pytest.mark.skipif(not PWSH, reason='PowerShell 7 is required')


@pytest.mark.parametrize('keep_going', [False, True])
@pytest.mark.parametrize('mode,expected', [
    ('pass', 'PASS'), ('fail', 'FAIL'), ('missing', 'ERROR'),
    ('corrupt', 'ERROR'), ('mismatch', 'ERROR'), ('nonzero', 'FAIL'),
])
def test_sequence_requires_matching_evidence_and_success_exit(tmp_path, mode, expected, keep_going):
    scripts = tmp_path / 'scripts/legacy'
    scripts.mkdir(parents=True)
    scenarios = tmp_path / 'scripts/scenarios'
    scenarios.mkdir()
    shutil.copy(ROOT / 'scripts/legacy/run-tests-one-by-one.ps1', scripts)
    state = tmp_path / '.local/rg-agentic-ops-lab.json'
    state.parent.mkdir()
    state.write_text('{}')
    write = {
        'missing': '',
        'corrupt': "Set-Content (Join-Path $EvidenceRoot 'result.json') '{broken'",
        'mismatch': "Set-Content (Join-Path $EvidenceRoot 'result.json') '{\"scenario\":\"S09\",\"verdict\":\"pass\"}'",
    }.get(mode, "Set-Content (Join-Path $EvidenceRoot 'result.json') '" + json.dumps(
        {'scenario': 'S01', 'verdict': 'fail' if mode == 'fail' else 'pass', 'outcome': 'fixture'}) + "'")
    (scenarios / 'test-s01.ps1').write_text(
        'param($TimeoutSeconds,$EvidenceRoot)\n' + write + '\n' +
        ('exit 1' if mode == 'nonzero' else 'exit 0'))
    # S02 must remain NOT RUN when S01 fails; a separate success run tests continuation.
    (scenarios / 'test-s02.ps1').write_text('param($TimeoutSeconds,$EvidenceRoot)\n'
        "Set-Content (Join-Path $EvidenceRoot 'result.json') '{\"scenario\":\"S02\",\"verdict\":\"pass\",\"outcome\":\"fixture\"}'")
    run = subprocess.run([PWSH, '-NoProfile', '-File', str(scripts / 'run-tests-one-by-one.ps1'),
                          '-To', '2', '-PauseSeconds', '0', *(['-ContinueOnFailure'] if keep_going else [])], capture_output=True, text=True, timeout=30)
    report = next((tmp_path / '.local/evidence/sequences').glob('*/summary.json'))
    rows = json.loads(report.read_text(encoding='utf-8-sig'))
    assert rows[0]['Status'] == expected
    assert rows[1]['Status'] == ('PASS' if mode == 'pass' or keep_going else 'NOT RUN')
    assert (run.returncode == 0) == (mode == 'pass')
    assert report.with_suffix('.md').exists()
    assert report.with_suffix('.csv').exists()
