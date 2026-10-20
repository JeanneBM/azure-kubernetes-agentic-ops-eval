import importlib.util
import json
import shutil
from pathlib import Path

spec = importlib.util.spec_from_file_location('build_ledger', Path(__file__).parents[1] / 'scripts/build_ledger.py')
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


def test_missing_finish_does_not_create_trial_or_match_unrelated_package(tmp_path):
    a = tmp_path / 'evidence' / 'S01-a'
    b = tmp_path / 'evidence' / 'S02-b'
    a.mkdir(parents=True); b.mkdir()
    (a / 'result.json').write_text(json.dumps({'scenario': 'S01', 'faultStartUtc': '2026-10-01T10:00:00Z'}))
    event = dict(event='two_agent_incident_decision', correlation_id='one', status='resolved', action_executed=True)
    (a / 'diagnostic-extra.log').write_text('2026-10-01T10:00:01.123456789Z ' + json.dumps(event))
    (b / 'result.json').write_text('{}')
    (b / 'remediation.log').write_text('2026-10-01T10:00:01Z INFO: "POST /internal/v1/remediate HTTP/1.1" 200 OK')
    rows = ledger.build(tmp_path / 'evidence', tmp_path / 'out.md')
    assert len(rows) == 2
    assert all(r['trial'] is None for r in rows)
    assert rows[0]['data']['action_executed'] is None


def test_archived_evidence_counts_and_manual_comments_survive(tmp_path):
    root = Path(__file__).parents[1]
    output = tmp_path / 'ledger.md'
    # Freeze the historical S01-S06 fixture; newly recorded trials must not
    # change the expected counts in this regression test.
    evidence = tmp_path / 'historical-evidence'
    evidence.mkdir()
    # An explicit manifest freezes input membership, not the growing evidence folder.
    historical_archives = (
        'S01-20261006T134759278Z-anonymized.zip',
        'S01-v2-20261009T120039727Z-C-01-anonymized.zip',
        'S02-20261009T105643940Z-C-01-anonymized.zip',
        'S03-20261009T111132556Z-C-01-anonymized.zip',
        'S04-20261012T083058902Z-C-01-anonymized.zip',
        'S05-20261012T092231374Z-C-01-anonymized.zip',
        'S06-20261012T094802362Z-C-01-anonymized.zip',
    )
    archives = [root / 'eval/evidence' / name for name in historical_archives]
    assert all(p.is_file() for p in archives), 'Historical ledger fixture is missing'
    for archive in archives:
        shutil.copy2(archive, evidence / archive.name)
    rows = ledger.build(evidence, output)
    assert len(rows) == 12
    assert sum(r['trial'] is not None for r in rows) == 7
    assert sum(r['data']['status'] == 'no decision in package' for r in rows) == 1
    text = output.read_text().replace('| 1 |', '| 1 |', 1)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('| 1 |'):
            lines[i] = line[:-2] + 'manual note |'
    output.write_text('\n'.join(lines))
    ledger.build(evidence, output)
    assert 'manual note' in output.read_text()
