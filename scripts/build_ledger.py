#!/usr/bin/env python3
"""Build a ledger from ZIP archives or extracted run folders.

Usage: python scripts/build_ledger.py eval/evidence eval/ledger.md
Existing manual comments are retained by timestamp and correlation ID.
"""
import argparse
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def ts(value):
    value = re.sub(r'(\.\d{6})\d+', r'\1', value.strip())
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def load_runs(root):
    runs = []
    packages = [(p, None) for p in sorted(root.rglob('*.zip'))]
    folders = {p.parent for name in ('result.json', 'fault-start-utc.txt') for p in root.rglob(name)}
    packages += [(p, p) for p in sorted(folders)]
    for path, folder in packages:
        if folder:
            files = {p.relative_to(folder).as_posix(): p.read_text(encoding='utf-8-sig')
                     for p in folder.rglob('*') if p.is_file() and p.suffix in ('.log', '.json', '.txt')}
        else:
            with zipfile.ZipFile(path) as archive:
                files = {name: archive.read(name).decode('utf-8-sig') for name in archive.namelist()
                         if name.endswith(('.log', '.json', '.txt'))}
        # Archives may wrap the run in one top-level folder.
        result_names = [n for n in files if Path(n).name == 'result.json']
        fault_names = [n for n in files if Path(n).name == 'fault-start-utc.txt']
        result = json.loads(files[result_names[0]]) if result_names else {}
        start = ts(result['faultStartUtc']) if result.get('faultStartUtc') else None
        end = ts(result['finishedUtc']) if result.get('finishedUtc') else None
        legacy = False
        if not result_names and fault_names:
            start = ts(files[fault_names[0]])
            end = start + timedelta(seconds=60)
            legacy = True
        match = re.search(r'S\d+', path.name)
        runs.append(dict(path=path, files=files, start=start, end=end, legacy=legacy,
                         scenario=result.get('scenario') or (match[0] if match else '?'),
                         verdict=result.get('verdict')))
    return runs


def build(root, output):
    runs = load_runs(root)
    decisions, posts = {}, {}
    for run in runs:
        for name, content in run['files'].items():
            base = Path(name).name
            if not (base.startswith('diagnostic') and base.endswith('.log') or base == 'remediation.log'):
                continue
            for number, line in enumerate(content.splitlines(), 1):
                source = f"{run['path'].relative_to(root).as_posix()} → {name}:{number}"
                match = re.match(r'^(\S+)\s+(\{.*\})\s*$', line)
                if match:
                    data = json.loads(match[2])
                    if data.get('event') == 'two_agent_incident_decision':
                        key = (match[1], data.get('correlation_id', '-'))
                        row = decisions.setdefault(key, dict(time=ts(match[1]), stamp=match[1], data=data, sources=[]))
                        if row['data'] != data:
                            raise ValueError(f'Conflicting decision: {key}')
                        row['sources'].append(source)
                match = re.match(r'^(\S+) .*"POST /internal/v1/remediate HTTP/1\.1" (\d+)', line)
                if match:
                    key = (match[1], match[2])
                    row = posts.setdefault(key, dict(time=ts(match[1]), stamp=match[1], code=match[2], sources=[]))
                    row['sources'].append(source)
    rows = list(decisions.values())
    # Timestamp proximity is only a heuristic: access logs lack correlation IDs.
    # Require the same package and a unique decision within three seconds after POST.
    for post in posts.values():
        packages = {s.split(' → ')[0] for s in post['sources']}
        matches = [r for r in rows if 0 <= (r['time'] - post['time']).total_seconds() < 3
                   and packages.intersection(s.split(' → ')[0] for s in r['sources'])]
        if len(matches) != 1:
            rows.append(dict(post, data=dict(status='no decision in package',
                        reason=f"POST /internal/v1/remediate → HTTP {post['code']}",
                        correlation_id='-', action_executed=None, groundedness=None)))
        else:
            matches[0]['sources'].extend(post['sources'])
    notes = {}
    if output.exists():
        for line in output.read_text().splitlines():
            if line.startswith('| ') and not line.startswith('| #'):
                cells = line.strip('| ').split(' | ')
                if len(cells) == 10:
                    notes[(cells[1], cells[7].strip('`'))] = cells[9]
    rows.sort(key=lambda r: r['time'])
    for row in rows:
        candidates = [r for r in runs if r['start'] and r['end']
                      and r['start'] - timedelta(seconds=10) <= row['time'] <= r['end'] + timedelta(seconds=10)]
        row['trial'] = candidates[0] if len(candidates) == 1 else None
        row['label'] = (f"{candidates[0]['scenario']} (verdict={candidates[0]['verdict'] or 'not recorded'})"
                        if len(candidates) == 1 else 'AMBIGUOUS' if candidates else 'OUTSIDE TRIAL')
    inside = sum(r['trial'] is not None for r in rows)
    text = ['# Decision ledger', '',
            'Generated by `scripts/build_ledger.py` from diagnostic*.log decision events and remediation.log API calls. Times are UTC. Trial assignment uses faultStartUtc..finishedUtc ±10 s. Legacy S01 has no result.json: its provisional window is fault-start-utc.txt +60 s, with the same tolerance; this is a historical classification, not a recorded verdict.', '',
            'Duplicate decision events are merged by full timestamp and correlation ID; all source occurrences are preserved. API-call matching uses a unique decision in the same package within three seconds after the call and is a heuristic, not correlation-ID proof. HTTP 200 alone does not confirm execution or successful repair.', '',
            f'Rows: **{len(rows)}**; in trial windows: **{inside}**; outside or ambiguous: **{len(rows)-inside}**.', '',
            '| # | UTC | Classification | Status | Reason | Executed | groundedness | Correlation ID | Evidence | Comment |',
            '|---|---|---|---|---|---|---|---|---|---|']
    def cell(value):
        return str(value).replace('|', '&#124;').replace('\n', '<br>')
    for i, row in enumerate(rows, 1):
        d = row['data']; cid = d.get('correlation_id', '-')
        comment = notes.get((row['stamp'], cid), '')
        values = [i, row['stamp'], row['label'], d['status'], d.get('reason') or '(empty)',
                  'unknown' if d.get('action_executed') is None else str(d['action_executed']).lower(),
                  d.get('groundedness'), f'`{cid}`', '<br>'.join(row['sources']), comment]
        text.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
    text += ['', '## Status counts', '']
    for (label, status), count in sorted(Counter((r['label'], r['data']['status']) for r in rows).items()):
        text.append(f'- {label} / {status}: {count}')
    text += ['', '## Interpretation', '',
             'Manual comments are preserved by timestamp and correlation ID when regenerating this file. Existing archives do not contain raw proposals for rejected actions; future audit events include proposed_action separately from the authorized action.', '',
             'Background triggers and transport failures remain visible. Define the metric and unit before choosing a denominator: watcher repeats are additional attempts on the same fault, not independent scenario trials; the unmatched API call has an unknown outcome. Model groundedness is a recorded score, not an independently measured accuracy metric.', '']
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(text), encoding='utf-8')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence_root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    rows = build(args.evidence_root, args.output)
    print(f'Wrote {len(rows)} ledger rows to {args.output}')
