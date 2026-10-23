"""Durable one-trial-at-a-time campaign. No resources are provisioned here."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scripts.run_protocol_checks import CATALOG, classify
from eval.protocol.live import LiveTrial, ROOT


def utc(): return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2),encoding='utf-8')
    os.replace(temporary,path)


def freeze():
    paths=[ROOT/'pyproject.toml',ROOT/'constraints.txt',ROOT/'evaluation-scenarios.md']
    for directory in ('src','eval/protocol','eval/handoff','tests/scenarios','scripts/tests'):
        paths.extend(p for p in (ROOT/directory).rglob('*') if p.suffix in ('.py','.ps1'))
    paths.extend([ROOT/'scripts/run_protocol_checks.py',ROOT/'eval/protocol/catalog.json'])
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}


def plan(repetitions=5):
    rows=[]
    def add(scenario,variant,environment):
        rows.append(dict(id=f'{len(rows)+1:03}-{scenario}-{variant}',scenario=scenario,
                         variant=variant,environment=environment,status='NOT_RUN',attempts=[]))
    for repeat in range(1,repetitions+1):
        # Alternate order to reduce drift; a whole pair completes before the next scenario.
        for number in range(1,9):
            for variant in (('A','C') if repeat%2 else ('C','A')):
                add(f'S{number:02}',variant,'live-aks')
                rows[-1]['repetition']=repeat
    for scenario in ('S09','S10'): add(scenario,'scripted','controlled-live-aks')
    for scenario in ('K01','K02','K03'):
        for variant in ('A','C'): add(scenario,variant,'live-aks')
    for number in range(1,9): add(f'P{number:02}','scripted','offline-mocked')
    add('HANDOFF','scripted','controlled-live-aks')
    add('INFRA','probe','live-aks')
    return rows


def validate_fixtures(fixtures):
    if fixtures.get('split') not in ('development','held-out') or not fixtures.get('revision'):
        raise ValueError('Fixtures require revision and development/held-out split')
    repositories=fixtures.get('fault_repositories',{})
    for key in ('S01','S02','S05','S06','S07','S08'):
        value=repositories.get(key)
        from agentic_ops.safety import edit_distance
        import re
        if not isinstance(value,str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,60}',value) or not 1<=edit_distance(value,'test-app')<=2:
            raise ValueError('Each repair fixture requires a valid nearby repository typo')
    return fixtures


def init(path,repetitions,fixtures=None):
    fixtures=validate_fixtures(fixtures or json.loads((ROOT/'eval/protocol/catalog.json').read_text()))
    if path.exists(): raise ValueError('Campaign already exists; choose another directory')
    path.mkdir(parents=True)
    rev=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    dirty=subprocess.run(['git','-C',str(ROOT),'status','--porcelain'],capture_output=True,text=True,check=True).stdout.strip()
    manifest=dict(schema_version=1,created_utc=utc(),source_commit=rev,working_tree_dirty=bool(dirty),
                  frozen_files=freeze(),fixtures=dict(fixtures,registry_fixture_namespace=uuid.uuid4().hex[:8]),repetitions=repetitions,trials=plan(repetitions))
    write_json(path/'campaign.json',manifest)
    report(path,manifest)
    return manifest


def offline(row,directory):
    xml=directory/'junit.xml'
    result=subprocess.run([sys.executable,'-m','pytest',*CATALOG[row['scenario']],'-q','-rxX',
                           f'--junitxml={xml}'],cwd=ROOT,capture_output=True,text=True,timeout=180)
    (directory/'console.log').write_text(result.stdout+result.stderr)
    verdict,cases=classify(result.returncode,xml)
    return dict(verdict=verdict,cases=cases,pytest_exit=result.returncode,environment='offline-mocked')


def existing(row,directory,timeout):
    scenario=row['scenario']; pwsh=shutil.which('pwsh')
    if not pwsh: raise ValueError('PowerShell 7 required for controlled integration runners')
    if scenario=='HANDOFF':
        process=subprocess.run([sys.executable,str(ROOT/'eval/handoff/run.py'),
                  '--evidence-dir',str(directory/'handoff')],cwd=ROOT,capture_output=True,text=True,timeout=1500)
        path=directory/'handoff/summary.json'
    else:
        process=subprocess.run([pwsh,'-NoProfile','-NonInteractive','-File',
                  str(ROOT/f'scripts/tests/test-{scenario.lower()}.ps1'),'-PrepareBaseline',
                  '-TimeoutSeconds',str(max(180,timeout)),'-EvidenceRoot',str(directory)],
                  cwd=ROOT,capture_output=True,text=True,timeout=1800)
        files=list(directory.rglob('result.json'))
        if len(files)!=1: raise ValueError('Expected exactly one controlled trial result')
        path=files[0]
    (directory/'console.log').write_text(process.stdout+process.stderr)
    result=json.loads(path.read_text(encoding='utf-8-sig'))
    verdict={'pass':'PASS','fail':'AGENT_FAIL','inconclusive':'INCONCLUSIVE'}.get(result.get('verdict'),'INCONCLUSIVE')
    if process.returncode and verdict=='PASS': verdict='INCONCLUSIVE'
    return dict(result,verdict=verdict,environment='controlled-live-aks',script_exit=process.returncode)


def runtime_fingerprint(provenance):
    model=provenance['model']
    return dict(runtime_image=provenance['runtime_image'],source_hashes=provenance['source_hashes'],
                model=model.get('properties',{}).get('model'),sku=model.get('sku'),
                intended_images=next(e.get('value') for e in provenance['remediation_template']['spec']['template']['spec']['containers'][0]['env']
                                     if e['name']=='AGENTIC_OPS_INTENDED_IMAGES'))


def check_runtime(path,manifest,directory):
    fingerprint=runtime_fingerprint(json.loads((directory/'provenance.json').read_text()))
    if 'runtime' not in manifest:
        manifest['runtime']=fingerprint
        write_json(path/'campaign.json',manifest)
    elif manifest['runtime']!=fingerprint:
        raise ValueError('Runtime/model/policy configuration drift; start a new campaign')


def run_one(path,manifest,*,trial_id=None,retry=False,setup_timeout=300,timeout=180):
    if manifest['frozen_files']!=freeze(): raise ValueError('Frozen evaluator/source changed; start a new campaign')
    row=next((r for r in manifest['trials'] if r['id']==trial_id),None) if trial_id else next(
        (r for r in manifest['trials'] if r['status']=='NOT_RUN'),None)
    if row is None: raise ValueError('No matching unrun trial')
    if row['status']!='NOT_RUN' and not retry: raise ValueError('Trial already attempted; explicit --retry required')
    if row['status']=='PASS' and retry: raise ValueError('Passing trials cannot be overwritten; create a new campaign')
    directory=path/'trials'/row['id']/f'attempt-{len(row["attempts"])+1:02}-{uuid.uuid4().hex[:6]}'
    directory.mkdir(parents=True)
    attempt=dict(started_utc=utc(),directory=str(directory),verdict='INTERRUPTED')
    row['attempts'].append(attempt); row['status']='RUNNING'
    write_json(path/'campaign.json',manifest)
    result={'verdict':'INCONCLUSIVE'}
    try:
        state=json.loads((ROOT/'.local/rg-agentic-ops-lab.json').read_text(encoding='utf-8-sig')) if row['environment']!='offline-mocked' else None
        if row['environment']=='offline-mocked': result=offline(row,directory)
        elif row['scenario']=='INFRA':
            from eval.protocol.infrastructure import run
            result=run(state,directory,validate=lambda:check_runtime(path,manifest,directory))
        elif row['scenario'] in ('S09','S10','HANDOFF'):
            guard=LiveTrial(state,directory)
            guard.preflight()
            check_runtime(path,manifest,directory)
            result=existing(row,directory,timeout)
        else:
            trial=LiveTrial(state,directory,setup_timeout=setup_timeout,decision_timeout=timeout,fixtures=manifest.get('fixtures'))
            original=trial.preflight
            def frozen_preflight():
                original()
                check_runtime(path,manifest,directory)
            trial.preflight=frozen_preflight
            result=trial.run(row['scenario'],row['variant'])
    except Exception as error:
        result=dict(verdict='INCONCLUSIVE',error=f'{type(error).__name__}: {error}')
    finally:
        if row['environment']!='offline-mocked' and not (directory/'review.json').exists():
            write_json(directory/'review.json',dict(manifest.get('fixtures',{}).get('human_review',{}),
                review_status='pending',scenario=row['scenario'],rubric=manifest.get('fixtures',{}).get('rubric',{}).get(row['scenario'])))
        attempt.update(result,finished_utc=utc())
        row['status']=attempt['verdict']
        write_json(directory/'campaign-result.json',dict(row_id=row['id'],**attempt))
        write_json(path/'campaign.json',manifest)
        report(path,manifest)
    print(f"{row['id']}: {row['status']}\nEvidence: {directory}",flush=True)
    return result


def report(path,manifest,pricing=None):
    lines=['# Evaluation campaign','',f"Source commit: `{manifest['source_commit']}`",'',
           '| Trial | Environment | Status | Attempts |','| --- | --- | --- | ---: |']
    lines += [f"| {r['id']} | {r['environment']} | {r['status']} | {len(r['attempts'])} |" for r in manifest['trials']]
    groups={}
    for row in manifest['trials']:
        # All attempts remain in denominators; rerunning a failure cannot erase it.
        for a in row['attempts']:
            key=f"{row['scenario']}/{row['variant']}"
            groups.setdefault(key,[]).append(a)
    stats={}
    for key,attempts in groups.items():
        success=[a['timing']['intervals']['failure_to_recovery'] for a in attempts
                 if a['verdict']=='PASS' and a.get('outcome')=='resolved'
                 and a.get('timing',{}).get('intervals',{}).get('failure_to_recovery') is not None]
        stats[key]=dict(attempts=len(attempts),passed=sum(a['verdict']=='PASS' for a in attempts),
                        failures=sum(a['verdict']=='AGENT_FAIL' for a in attempts),
                        timeouts=sum(a['verdict']=='TIMEOUT' for a in attempts),
                        setup_failures=sum(a['verdict']=='SETUP_FAIL' for a in attempts),
                        successful_recovery_seconds={'median':statistics.median(success),'min':min(success),'max':max(success)} if success else None)
    pending_review=0
    for row in manifest['trials']:
        for attempt in row['attempts']:
            review=Path(attempt['directory'])/'review.json'
            if review.exists() and json.loads(review.read_text()).get('review_status')!='completed':
                pending_review+=1
    summary=dict(human_reviews_pending=pending_review,source_commit=manifest['source_commit'],total=len(manifest['trials']),
        passed=sum(r['status']=='PASS' for r in manifest['trials']),
        unrun=sum(r['status']=='NOT_RUN' for r in manifest['trials']),statistics=stats,
        automated_checks_clean=all(r['status']=='PASS' and len(r['attempts'])==1 for r in manifest['trials']),
        clean_evaluation=pending_review==0 and all(r['status']=='PASS' and len(r['attempts'])==1 for r in manifest['trials']))
    if pricing:
        if not all(k in pricing for k in ('date','currency','input_per_million','output_per_million')):
            raise ValueError('Pricing requires date, currency and input/output_per_million')
        costs=[]
        for row in manifest['trials']:
            for a in row['attempts']:
                usage=a.get('usage')
                if usage is None: continue
                complete=all(u and 'prompt_tokens' in u and 'completion_tokens' in u for u in usage)
                costs.append(dict(trial=row['id'],attempt=a['directory'],cost=sum(
                    (u['prompt_tokens']*pricing['input_per_million']+u['completion_tokens']*pricing['output_per_million'])/1e6
                    for u in usage) if complete else None))
        summary.update(pricing=pricing,measured_trial_costs=costs,
            cost_scope='Decision calls only; warmup usage recorded separately; infrastructure billed separately')
    write_json(path/'summary.json',summary)
    lines += ['', '## Scope and interpretation','',
        'P01-P08 are intentionally offline parser/policy/transport checks. Live rows use AKS/ACR; A does not call a model.',
        'S09/S10 and HANDOFF are controlled integration probes, not real-model quality measurements.',
        'All failed attempts are retained. A retry does not erase the original safety/timing finding.',
        'Timing reports include only successful recoveries, alongside failures/timeouts/setup counts.',
        'No production-security guarantee or latency advantage is inferred from zero observed failures.',
        'Raw evidence may contain application data. Use the existing anonymizing packager before publication.']
    (path/'summary.md').write_text('\n'.join(lines)+'\n')
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('init','next','run','report','list'))
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--repetitions',type=int,default=5)
    parser.add_argument('--trial')
    parser.add_argument('--retry',action='store_true')
    parser.add_argument('--continue-on-failure',action='store_true')
    parser.add_argument('--setup-timeout',type=int,default=300)
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--pricing',type=Path)
    parser.add_argument('--fixtures',type=Path,help='Private predeclared fixture JSON for a separate held-out campaign')
    parser.add_argument('--pause-seconds',type=int,default=60)
    options=parser.parse_args(argv)
    if not 1<=options.repetitions<=100 or not 30<=options.timeout<=900 or not 30<=options.setup_timeout<=1800:
        parser.error('Invalid repetitions or timeouts')
    if not 0<=options.pause_seconds<=3600: parser.error('Invalid pause')
    path=options.campaign.resolve()
    if options.action=='init':
        manifest=init(path,options.repetitions,json.loads(options.fixtures.read_text()) if options.fixtures else None)
        print(f"Created {len(manifest['trials'])} planned trials. No Azure requests.\n{path/'summary.md'}")
        return 0
    manifest=json.loads((path/'campaign.json').read_text())
    if options.action in ('report','list'):
        pricing=json.loads(options.pricing.read_text()) if options.pricing else None
        report(path,manifest,pricing)
        print('\n'.join(f"{r['id']}: {r['status']}" for r in manifest['trials']))
        print(path/'summary.md'); return 0
    # Atomic lock covers the full live session, including cleanup; stale locks are
    # never auto-adopted because another operator may still be changing the lab.
    lock=ROOT/'.local/protocol-live.lock'
    lock.parent.mkdir(exist_ok=True)
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.write(fd,json.dumps(dict(pid=os.getpid(),campaign=str(path),started_utc=utc())).encode()); os.close(fd)
    try:
        while True:
            # Do not skip an interrupted run without explicit operator review.
            if any(r['status']=='RUNNING' for r in manifest['trials']) and not options.retry:
                raise ValueError('Interrupted RUNNING trial; review cleanup and use --trial ID --retry')
            if options.action=='run' and not any(r['status']=='NOT_RUN' for r in manifest['trials']): break
            result=run_one(path,manifest,trial_id=options.trial,retry=options.retry,
                           setup_timeout=options.setup_timeout,timeout=options.timeout)
            if result.get('cleanup_errors'):
                print('Cleanup failed. Stop and restore the baseline before continuing.'); return 1
            if result['verdict']!='PASS' and not options.continue_on_failure: return 1
            if options.action=='next' or options.trial: return 0 if result['verdict']=='PASS' else 1
            if any(r['status']=='NOT_RUN' for r in manifest['trials']):
                print(f'Waiting {options.pause_seconds} seconds before the next trial...',flush=True)
                time.sleep(options.pause_seconds)
        return 0 if all(r['status']=='PASS' and all(a['verdict']=='PASS' for a in r['attempts']) for r in manifest['trials']) else 1
    finally:
        lock.unlink()
