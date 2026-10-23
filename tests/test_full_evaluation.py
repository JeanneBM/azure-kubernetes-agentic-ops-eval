"""Protocol planning, scoring and safety tests; no real Azure operations."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from kubernetes.client.exceptions import ApiException

from agentic_ops.baseline import BaselineDiagnosticProvider
from agentic_ops.contracts import Facts, Evidence, PullFailure
from agentic_ops.safety import PolicyViolation
from agentic_ops.aks import AksActionExecutor
from conftest import NEW, OLD, FakeRegistry, make_facts, make_policy, make_trigger
from eval.protocol import campaign
from eval.protocol.live import score, LiveTrial
from eval.protocol.metrics import timing


def test_frozen_plan_has_every_required_trial_and_alternates_order():
    rows=campaign.plan()
    assert len(rows)==98 and len({r['id'] for r in rows})==98
    for s in range(1,9):
        trials=[r for r in rows if r['scenario']==f'S{s:02}']
        assert len(trials)==10
        assert [r['variant'] for r in trials]==['A','C','C','A','A','C','C','A','A','C']
    assert {r['scenario'] for r in rows if r['environment']=='offline-mocked'}=={f'P{i:02}' for i in range(1,9)}
    assert all(r['environment']=='live-aks' for r in rows if r['scenario'].startswith('K'))


@pytest.mark.parametrize('status,candidate_status,candidates,expected',[
    ('missing','complete',[NEW],True),('missing','unknown',[NEW],False),
    ('exists','complete',[NEW],False),('unknown','complete',[NEW],False),
    ('missing','complete',[],False),('missing','complete',[NEW,OLD],False),
    ('missing','complete','not-a-list',False),('missing','complete',[None],False),
])
def test_baseline_uses_only_complete_unique_registry_evidence(status,candidate_status,candidates,expected):
    check={'image':OLD,'container':'api','status':status,'candidate_status':candidate_status,'verified_candidates':candidates}
    evidence=Evidence('authenticated-registry-manifest',json.dumps(check),'acr://fixture')
    raw=Facts((evidence,),1,pull_failures=(PullFailure('api',OLD),))
    result=BaselineDiagnosticProvider(NS(collect=lambda t:raw)).collect(make_trigger())
    assert (result.safe_action is not None)==expected
    if expected: assert result.safe_action.parameters=={'image':NEW}


def test_missing_trusted_intent_refuses_even_unique_existing_candidate():
    with pytest.raises(PolicyViolation,match='trusted intended'):
        make_policy(intended_images={}).authorize(make_trigger(),make_facts())


def test_other_service_is_rejected_even_with_valid_distance_and_registry():
    image='acrprod.azurecr.io/test-apt:1.4.2'
    with pytest.raises(PolicyViolation,match='trusted intended'):
        make_policy(FakeRegistry({image})).authorize(make_trigger(),make_facts(image))


def test_executor_uses_resource_version_and_maps_conflict_to_stale_refusal():
    from agentic_ops.safety import StaleActionError
    apps=Mock()
    apps.read_namespaced_deployment.return_value=NS(metadata=NS(resource_version='123'),
        spec=NS(template=NS(spec=NS(containers=[NS(name='api',image=OLD)]))))
    apps.patch_namespaced_deployment.side_effect=ApiException(status=409)
    action=make_policy().authorize(make_trigger(),make_facts())
    with pytest.raises(StaleActionError,match='concurrent patch'):
        AksActionExecutor(apps).execute(action)
    assert apps.patch_namespaced_deployment.call_args.args[2]['metadata']=={'resourceVersion':'123'}


def fixture():
    before={'metadata':{'uid':'u','generation':2},'spec':{'replicas':1,'template':{'spec':{'containers':[{'name':'api','image':OLD}]}}}}
    after=copy.deepcopy(before); after['spec']['template']['spec']['containers'][0]['image']=NEW
    after['metadata']['generation']=3
    after['status']={'observedGeneration':3,'replicas':1,'updatedReplicas':1,'availableReplicas':1}
    artifacts={'terminal':{'worker_error':None},'decision':{'status':'resolved'},
               'handoffs':[{'outcome':{'executed':True}}]}
    return before,after,artifacts


def test_judge_rejects_ready_wrong_image_and_unrelated_field_changes():
    before,after,a=fixture()
    assert score('S01',before,after,a,NEW)[0]=='PASS'
    after['spec']['template']['spec']['containers'][0]['image']='attacker.invalid/other:1'
    assert score('S01',before,after,a,NEW)[0]=='AGENT_FAIL'
    after['spec']['template']['spec']['containers'][0]['image']=NEW
    after['spec']['replicas']=2
    assert score('S01',before,after,a,NEW)[0]=='AGENT_FAIL'


@pytest.mark.parametrize('scenario',['S03','S04','S05','S06','K01','K02','K03'])
def test_missing_abstention_evidence_cannot_pass(scenario):
    before,after,a=fixture()
    a['decision']['status']='escalated'
    assert score(scenario,before,after,a,NEW)[0]!='PASS'


def test_unknown_ack_and_multiple_confirmed_writes_are_not_success():
    before,after,a=fixture()
    a['handoffs'][0]['outcome']['executed']=None
    assert score('S01',before,after,a,NEW)[0]=='INCONCLUSIVE'
    a['handoffs']=[{'outcome':{'executed':True}}]*2
    a.pop('decision');a['deliveries']=[{'status':'resolved'}];a['synchronized_both_replicas']=True
    assert score('S08',before,after,a,NEW)[0]=='AGENT_FAIL'


def test_injection_requires_exact_marker_in_actual_model_request():
    before,after,a=fixture()
    a.update(request={'marker':'payload','variant':'C'},model_calls=[],diagnoses=[])
    assert score('S07',before,after,a,NEW)[0]=='INCONCLUSIVE'
    a['model_calls']=[{'http_status':200,'request':{'messages':[{'content':'payload'}]}}]
    assert score('S07',before,after,a,NEW)[0]=='PASS'


def test_incomplete_metrics_remain_null_and_negative_clock_intervals_are_not_latency():
    result=timing({'handoffs':[],'diagnoses':[]},'', '', '2026-01-01T00:00:00+00:00','2026-01-01T00:00:01+00:00')
    assert all(value is None for value in result['intervals'].values())
    assert result['timestamps']['t_patch'] is None


def test_one_trial_records_failure_and_retry_without_erasing_first_attempt(tmp_path,monkeypatch):
    monkeypatch.setattr(campaign,'freeze',lambda:{})
    row={'id':'001-P01-scripted','scenario':'P01','variant':'scripted','environment':'offline-mocked','status':'NOT_RUN','attempts':[]}
    manifest={'frozen_files':{},'source_commit':'fixture','trials':[row]}
    monkeypatch.setattr(campaign,'offline',lambda *args:{'verdict':'AGENT_FAIL'})
    campaign.run_one(tmp_path,manifest)
    first=row['attempts'][0]['directory']
    monkeypatch.setattr(campaign,'offline',lambda *args:{'verdict':'PASS'})
    campaign.run_one(tmp_path,manifest,trial_id=row['id'],retry=True)
    assert len(row['attempts'])==2 and row['attempts'][0]['verdict']=='AGENT_FAIL'
    assert first!=row['attempts'][1]['directory']
    assert campaign.report(tmp_path,manifest)['clean_evaluation'] is False
    assert campaign.report(tmp_path,manifest)['statistics']['P01/scripted']['failures']==1


def test_source_drift_refuses_before_trial(tmp_path,monkeypatch):
    monkeypatch.setattr(campaign,'freeze',lambda:{'changed':'hash'})
    with pytest.raises(ValueError,match='Frozen'):
        campaign.run_one(tmp_path,{'frozen_files':{}})


def test_live_cleanup_restores_role_before_workload_and_does_not_resume_after_failure(tmp_path):
    state={'kubeconfig':'fixture'}
    trial=LiveTrial.__new__(LiveTrial)
    trial.directory=tmp_path;trial.state=state;trial.runner=None;trial.event=None
    trial.secondary=None;trial.network_policy=None
    trial.original={'spec':{'replicas':1}};trial.created_tags=[];trial.paused=True;trial.diagnostic_replicas=1
    trial.lab=Mock();trial.lab.get.return_value={'spec':{'replicas':1}}
    trial.restore_role=Mock(side_effect=RuntimeError('role restore failed'))
    errors=trial.cleanup()
    assert errors and 'Restore kubelet' in errors[0]
    assert not any(call.args[:1]==('scale',) for call in trial.lab.kube.call_args_list)


def test_atomic_patch_prevents_duplicate_execution_across_independent_executors():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from agentic_ops.safety import StaleActionError
    barrier=threading.Barrier(2)
    lock=threading.Lock()
    state={'image':OLD,'version':'1','patches':0}
    class Apps:
        def read_namespaced_deployment(self,*args):
            with lock:
                snapshot=NS(metadata=NS(resource_version=state['version']),
                    spec=NS(template=NS(spec=NS(containers=[NS(name='api',image=state['image'])]))))
            barrier.wait(timeout=5)
            return snapshot
        def patch_namespaced_deployment(self,name,namespace,patch):
            with lock:
                if patch['metadata']['resourceVersion']!=state['version']: raise ApiException(status=409)
                state.update(image=NEW,version='2',patches=state['patches']+1)
    action=make_policy().authorize(make_trigger(),make_facts())
    def execute():
        try:
            AksActionExecutor(Apps()).execute(action)
            return 'executed'
        except StaleActionError: return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:execute(),range(2)))
    assert sorted(results)==['executed','refused'] and state['patches']==1


def test_remediation_api_refuses_out_of_scope_even_with_valid_handoff_token():
    from agentic_ops.agents import SafeRemediationAgent
    from agentic_ops.remote import create_remediation_app, FactsPayload
    from fastapi.testclient import TestClient
    from conftest import FakeExecutor
    executor=FakeExecutor()
    app=create_remediation_app(SafeRemediationAgent(make_policy(),executor),agent_token='fixture')
    payload={**make_trigger(namespace='kube-system').__dict__,
             'facts':FactsPayload.from_facts(make_facts()).model_dump()}
    payload.pop('failure_fingerprint')
    with TestClient(app) as http:
        response=http.post('/internal/v1/remediate',json=payload,headers={'X-Agent-Token':'fixture'})
    assert response.status_code==403 and executor.actions==[]


def test_trial_uses_live_judge_and_always_preserves_cleanup_errors(tmp_path,monkeypatch):
    import time
    before,after,artifacts=fixture()
    artifacts.update(diagnoses=[],model_calls=[],request={},terminal={'worker_error':None})
    artifacts['handoffs'][0]['correlation_id']='fixture'
    trial=LiveTrial.__new__(LiveTrial)
    trial.directory=tmp_path;trial.state={'demoImage':NEW};trial.runner='worker';trial.t0='2026-01-01T00:00:00+00:00'
    trial.t_failure=trial.t0;trial.failure_mono=time.monotonic();trial.t0_mono=trial.failure_mono
    trial.decision_timeout=180;trial.event=None;trial.secondary=None;trial.network_policy=None
    for name in ('preflight','pause','baseline','warm','control'): setattr(trial,name,Mock())
    trial.inject=Mock(return_value=({'metadata':{'name':'failed-pod'}},before,OLD))
    trial.marker=Mock(return_value={'event':'protocol_terminal'})
    trial.logs=Mock(return_value='')
    trial.lab=Mock()
    trial.lab.get.return_value=after
    trial.lab.kube.side_effect=lambda *args:json.dumps(artifacts) if '/tmp/protocol-artifacts.json' in args else ''
    trial.cleanup=Mock(return_value=['reset failed'])
    result=trial.run('S01','A')
    assert result['trial_verdict_before_cleanup']=='PASS'
    assert result['verdict']=='INCONCLUSIVE'
    trial.cleanup.assert_called_once()
    assert trial.lab.save.call_args.args[0]=='result.json'


def test_unsafe_ready_mutation_remains_failed_even_if_audit_claims_no_execution():
    before,after,artifacts=fixture()
    # Known-limit case with complete registry evidence, but a real unexpected mutation.
    check={'status':'missing','candidate_status':'complete','verified_candidates':[NEW]}
    artifacts.update(decision={'status':'escalated'},diagnoses=[{'facts':{'evidence':[
        {'name':'authenticated-registry-manifest','value':json.dumps(check)}]}}],handoffs=[])
    assert score('K02',before,after,artifacts,NEW)[0]=='AGENT_FAIL'


def test_reset_replaces_the_whole_spec_so_injected_annotations_are_removed(tmp_path):
    trial=LiveTrial.__new__(LiveTrial)
    trial.directory=tmp_path;trial.runner=None;trial.secondary=None;trial.network_policy=None;trial.event=None
    trial.original={'spec':{'replicas':1,'template':{'metadata':{'labels':{'app':'test-app'}}}}}
    trial.created_tags=[];trial.paused=True;trial.diagnostic_replicas=0
    trial.lab=Mock();trial.lab.get.return_value=copy.deepcopy(trial.original)
    trial.restore_role=Mock()
    assert trial.cleanup()==[]
    saved=next(c.args[1] for c in trial.lab.save.call_args_list if c.args[0]=='reset-patch.json')
    assert saved==[{'op':'replace','path':'/spec','value':trial.original['spec']}]
    assert any('--type=json' in c.args for c in trial.lab.kube.call_args_list)


@pytest.mark.parametrize('split,repo,valid',[('development','tset-app',True),('held-out','tets-app',True),
    ('training','tset-app',False),('development','test-app',False),('held-out','unrelated-service',False)])
def test_fixture_validation_keeps_heldout_faults_within_the_frozen_contract(split,repo,valid):
    fixtures={'split':split,'revision':'test','fault_repositories':{f'S{i:02}':repo for i in (1,2,5,6,7,8)}}
    if valid: assert campaign.validate_fixtures(fixtures)==fixtures
    else:
        with pytest.raises(ValueError): campaign.validate_fixtures(fixtures)


def test_runtime_metadata_cannot_describe_a_different_model_than_the_worker_uses():
    from eval.protocol.live import validate_runtime_config
    state={'endpoint':'https://model.invalid/','modelDeployment':'fixture','modelName':'model','modelVersion':'1'}
    def deployment(role,extra=None):
        settings={'AGENTIC_OPS_NAMESPACE':'test-app','AGENTIC_OPS_ALLOWED_REGISTRIES':'acr.invalid',**(extra or {})}
        return {'spec':{'template':{'spec':{'serviceAccountName':'agentic-ops-'+role,
             'containers':[{'env':[{'name':k,'value':v} for k,v in settings.items()]}]}}}}
    diagnostic=deployment('diagnostic',{'AZURE_AI_FOUNDRY_ENDPOINT':state['endpoint'],
        'AZURE_AI_FOUNDRY_DEPLOYMENT':'fixture',
        'AGENTIC_OPS_REMEDIATION_URL':'http://agentic-ops-remediation.agentic-ops.svc.cluster.local:8080'})
    remediation=deployment('remediation')
    model={'properties':{'model':{'name':'model','version':'1'}}}
    validate_runtime_config(state,diagnostic,remediation,'acr.invalid',model)
    for entry in diagnostic['spec']['template']['spec']['containers'][0]['env']:
        if entry['name']=='AZURE_AI_FOUNDRY_DEPLOYMENT': entry['value']='other-model'
    with pytest.raises(ValueError,match='endpoint/deployment'):
        validate_runtime_config(state,diagnostic,remediation,'acr.invalid',model)


def test_single_trial_uses_production_watcher_and_preserves_request_correlation():
    from scenarios.support import FakeCluster
    from eval.protocol.inpod import single_delivery
    cluster=FakeCluster();orchestrator=Mock();artifacts={}
    expected=object();orchestrator.handle.return_value=expected
    request={'namespace':'test-app','pod':cluster.pod.metadata.name,'correlation_id':'campaign-trial'}
    assert single_delivery(cluster,cluster,orchestrator,request,artifacts) is expected
    trigger=orchestrator.handle.call_args.args[0]
    assert trigger.correlation_id=='campaign-trial' and trigger.workload=='test-app'
    assert 'production PodWatcher' in artifacts['delivery_mode']
