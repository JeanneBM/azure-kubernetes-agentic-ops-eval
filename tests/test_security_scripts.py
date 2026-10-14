"""Execute PowerShell wrappers with local native-command substitutes only."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PWSH = os.environ.get('PWSH_BIN') or shutil.which('pwsh')
pytestmark = pytest.mark.skipif(not PWSH, reason='PowerShell 7 is required for offline CLI checks')

FAKE = r'''#!/tmp/eval-venv/bin/python
import json,os,sys,pathlib
root=pathlib.Path(os.environ['OFFLINE_ROOT']); statepath=root/'state.json'
s=json.loads(statepath.read_text()); name=pathlib.Path(sys.argv[0]).name; a=sys.argv[1:]
with (root/'trace.jsonl').open('a') as f:f.write(json.dumps([name,a])+'\n')
def save():statepath.write_text(json.dumps(s))
if name=='az': print(json.dumps({'fqdn':'lab.example','privateFqdn':None}));sys.exit()
if name=='git': print('a'*40);sys.exit()
if a[:1]==['--kubeconfig']: a=a[2:]
if a[:2]==['config','view']: print('https://other.example' if s['mismatch'] else 'https://lab.example');sys.exit()
if a[:2]==['rollout','status'] or a[:1] in (['wait'],['delete']):sys.exit()
if a[:1]==['scale']:
 role='diagnostic' if 'diagnostic' in a[1] else 'remediation'
 s[role]['spec']['replicas']=int(next(x for x in a if x.startswith('--replicas=')).split('=')[1]);save();sys.exit()
if a[:2]==['set','image']:
 dep=s['workload'] if 'payments-api' in a[2] else s['diagnostic'] if 'diagnostic' in a[2] else s['remediation']
 dep['spec']['template']['spec']['containers'][0]['image']=a[3].split('=',1)[1];dep['metadata']['generation']+=1;save();sys.exit()
if a[:1]==['create']:
 data=json.loads(pathlib.Path(a[2]).read_text())
 if data['kind']=='Pod':
  s['runner']=data; env={v['name']:v.get('value') for v in data['spec']['containers'][0]['env']}
  assert data['spec']['restartPolicy']=='Never'
  assert 'readinessProbe' not in data['spec']['containers'][0]
  assert '@sha256:' in data['spec']['containers'][0]['image']
  s['report']={'event':'controlled_trial_result','scenario':env['EVAL_SCENARIO'],'correlationId':env['EVAL_CORRELATION_ID'],'verdict':'pass','outcome':'escalated'}
  s['artifacts']=json.loads(json.dumps({'deployment_before_handoff':s['workload'],'deployment_after_handoff':s['workload']}, sort_keys=True))
 save();sys.exit()
if a[:1]==['logs']:
 if 'diagnostic' in a[1] and 'deployment/' not in a[1]:print('2026-10-14T10:00:00Z '+json.dumps(s['report']))
 sys.exit()
if a[:1]==['exec']:
 if '/tmp/eval-artifacts.json' in a:
  if s['collection_failure']:sys.exit(1)
  print(json.dumps(s['artifacts']))
 else:print('healthy_exists=true; typo_exists=false')
 sys.exit()
if a[:1]==['get']:
 resource=a[1]
 if resource.startswith('deployment'):
  print(json.dumps(s['workload'] if 'payments-api' in resource else s['diagnostic'] if 'diagnostic' in resource else s['remediation']));sys.exit()
 if resource=='pods':
  role=next((r for r in ['diagnostic','remediation'] if any('role='+r in x for x in a)),None)
  if role:
   c=s[role]['spec']['template']['spec']['containers'][0]
   print(json.dumps({'items':[{'metadata':{'name':role},'spec':{'containers':[c]},'status':{'phase':'Running','containerStatuses':[{'ready':True,'imageID':'docker-pullable://registry.example/agentic-ops@sha256:'+'1'*64}]}}]}))
  else:print(json.dumps({'items':[{'metadata':{'name':'failed-pod','uid':'uid'},'status':{'containerStatuses':[{'name':'api','image':s['workload']['spec']['template']['spec']['containers'][0]['image'],'state':{'waiting':{'reason':'ImagePullBackOff'}}}]}}]}))
  sys.exit()
 print(json.dumps({'items':[]}));sys.exit()
raise SystemExit('Unexpected offline command '+str(a))
'''


def setup(tmp_path, mismatch=False, collection_failure=False):
    root = tmp_path / 'repo'; root.mkdir()
    source = Path(__file__).parents[1]
    shutil.copytree(source / 'scripts', root / 'scripts')
    (root / 'eval').mkdir(); shutil.copy(source / 'eval/live_security_runner.py', root / 'eval/live_security_runner.py')
    (root / '.local').mkdir(); (root / 'bin').mkdir()
    def agent(role):
        return dict(metadata={'generation': 1}, spec={'replicas': 1, 'template': {'metadata': {'labels': {'app': 'agentic-ops', 'role': role}}, 'spec': {'containers': [{'name': 'agent', 'image': 'registry.example/agentic-ops:trial', 'env': [], 'readinessProbe': {'httpGet': {'path': '/healthz'}}}]}}})
    state = dict(mismatch=mismatch, collection_failure=collection_failure, diagnostic=agent('diagnostic'), remediation=agent('remediation'),
          workload={'metadata': {'generation': 1}, 'spec': {'replicas': 1, 'template': {'spec': {'containers': [{'name': 'api', 'image': 'registry.example/payments-api:1.4.2'}]}}}})
    (root / 'state.json').write_text(json.dumps(state))
    lab = dict(resourceGroup='rg-agentic-ops-lab', subscriptionId='offline', aksName='lab', kubeconfig='offline',
               demoImage='registry.example/payments-api:1.4.2', agentImage='registry.example/agentic-ops:trial')
    (root / '.local/rg-agentic-ops-lab.json').write_text(json.dumps(lab))
    # Use the current test Python executable, not a hardcoded runtime path.
    import sys
    for tool in ('kubectl', 'az', 'git'):
        p = root / 'bin' / tool
        p.write_text(FAKE.replace('#!/tmp/eval-venv/bin/python', '#!' + sys.executable, 1)); p.chmod(0o755)
    env = dict(os.environ, OFFLINE_ROOT=str(root), PATH=str(root / 'bin') + os.pathsep + os.environ['PATH'])
    return root, env


@pytest.mark.parametrize('scenario', ['s07', 's08', 's09', 's10'])
def test_wrappers_pin_images_collect_evidence_and_leave_watcher_paused(tmp_path, scenario):
    root, env = setup(tmp_path)
    result = subprocess.run([PWSH, '-NoProfile', '-File', str(root / f'scripts/tests/test-{scenario}.ps1')], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((root / 'state.json').read_text())
    assert state['diagnostic']['spec']['replicas'] == 0
    record = json.loads(next((root / 'eval/evidence').rglob('result.json')).read_text())
    assert record['verdict'] == 'pass'
    assert next((root / 'eval/evidence').rglob('*.zip')).is_file()
    trace = [json.loads(l) for l in (root / 'trace.jsonl').read_text().splitlines()]
    assert any(name == 'kubectl' and 'delete' in args and 'pod' in args for name, args in trace)


def test_cluster_mismatch_never_mutates_kubernetes(tmp_path):
    root, env = setup(tmp_path, mismatch=True)
    result = subprocess.run([PWSH, '-NoProfile', '-File', str(root / 'scripts/tests/test-s07.ps1')], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    trace = [json.loads(l) for l in (root / 'trace.jsonl').read_text().splitlines()]
    assert not any(name == 'kubectl' and any(v in args for v in ('scale', 'set', 'create', 'delete')) for name, args in trace)


def test_missing_artifacts_cannot_pass_and_runner_is_removed(tmp_path):
    root, env = setup(tmp_path, collection_failure=True)
    result = subprocess.run([PWSH, '-NoProfile', '-File', str(root / 'scripts/tests/test-s09.ps1')], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    record = json.loads(next((root / 'eval/evidence').rglob('result.json')).read_text())
    assert record['verdict'] == 'inconclusive'
    assert json.loads((root / 'state.json').read_text())['diagnostic']['spec']['replicas'] == 0
    trace = [json.loads(l) for l in (root / 'trace.jsonl').read_text().splitlines()]
    assert any(name == 'kubectl' and 'delete' in args and 'pod' in args for name, args in trace)
