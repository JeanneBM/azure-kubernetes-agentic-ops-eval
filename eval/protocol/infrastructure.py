"""Live identities, Kubernetes scope, handoff authentication and ingress probes."""
import copy
import json
import time
import uuid

from eval.handoff.run import runner_manifest
from eval.protocol.live import LiveTrial, wait_until, utc

PROBE = '''
import json,os,urllib.request,urllib.error,socket
base=os.environ['AGENTIC_OPS_REMEDIATION_URL'].rstrip('/')
result={'event':'infrastructure_probe','statuses':{}}
def call(name,path,body=None,token=None):
    headers={'Content-Type':'application/json'}
    if token: headers['X-Agent-Token']=token
    try:
        req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urllib.request.urlopen(req,timeout=8) as response: result['statuses'][name]=response.status
    except urllib.error.HTTPError as error: result['statuses'][name]=error.code
    except (urllib.error.URLError,TimeoutError,socket.timeout): result['statuses'][name]='unreachable'
call('health','/healthz')
if os.environ['EVAL_PROBE_MODE']=='allowed':
    from azure.identity import WorkloadIdentityCredential
    from agentic_ops.acr import AcrRegistry
    from agentic_ops.safety import parse_image
    credential=WorkloadIdentityCredential()
    token=credential.get_token('https://management.azure.com/.default')
    result['workload_identity_authenticated']=bool(token.token)
    result['registry_read_succeeded']=AcrRegistry(credential=credential).exists(parse_image(os.environ['EVAL_GOOD_IMAGE']))
    body={'namespace':'kube-system','pod':'not-a-real-target','workload':'forbidden',
          'reason':'ImagePullBackOff','correlation_id':'infra-probe',
          'facts':{'evidence':[],'groundedness':1,'safe_action':{'name':'fix_image','parameters':{'image':os.environ['EVAL_GOOD_IMAGE']}},
                   'summary':'scope probe','pull_failures':[{'container':'api','image':'invalid.example/tset-app:1.4.2'}]}}
    call('missing_token','/internal/v1/remediate',body)
    call('wrong_token','/internal/v1/remediate',body,'incorrect-evaluation-token')
    call('forbidden_namespace','/internal/v1/remediate',body,os.environ['AGENTIC_OPS_REMEDIATION_TOKEN'])
print(json.dumps(result),flush=True)
'''


def run(state,directory,validate=None):
    trial=LiveTrial(state,directory)
    result={'verdict':'SETUP_FAIL','environment':'live-aks','checks':{},'started_utc':utc()}
    lab=trial.lab
    created=[]
    try:
        trial.preflight()
        if validate: validate()
        baseline=lab.get('deployment','test-app','test-app')
        roles={}
        for role in ('diagnostic','remediation'):
            identity=trial.azure('identity','show','-g',state['resourceGroup'],'-n',state[role+'Identity'])
            roles[role]=identity
            sa=lab.get('serviceaccount','agentic-ops-'+role)
            if sa['metadata'].get('annotations',{}).get('azure.workload.identity/client-id')!=identity['clientId']:
                raise ValueError('Workload identity ServiceAccount annotation mismatch')
            assignments=trial.azure('role','assignment','list','--assignee',identity['principalId'],
                                    '--scope',trial.acr['id'],'--include-inherited')
            lab.save(role+'-role-assignments.json',assignments)
            all_roles=trial.azure('role','assignment','list','--assignee',identity['principalId'],'--all')
            lab.save(role+'-all-role-assignments.json',all_roles)
            allowed={'AcrPull','Cognitive Services OpenAI User'} if role=='diagnostic' else {'AcrPull'}
            result['checks'][role+'/no-unexpected-Azure-role']=all(a['roleDefinitionName'] in allowed for a in all_roles)
            if role=='diagnostic':
                account_scope=trial.model['id'].split('/deployments/')[0]
                result['checks']['diagnostic/model-role']=any(a['roleDefinitionName']=='Cognitive Services OpenAI User'
                    and a['scope'].lower()==account_scope.lower() for a in all_roles)
            if not any(a['roleDefinitionName']=='AcrPull' and a['scope']==trial.acr['id'] for a in assignments):
                raise ValueError('Required registry-scoped AcrPull missing')
        principals={v['principalId'] for v in roles.values()}
        if len(principals)!=2 or trial.aks['identityProfile']['kubeletidentity']['objectId'] in principals:
            raise ValueError('Diagnostic, remediation and kubelet identities must be distinct')
        result['checks']['distinct_workload_identities']=True
        for role,verb,resource,namespace,expected in [
            ('diagnostic','get','pods','test-app','yes'),
            ('diagnostic','patch','deployments.apps','test-app','no'),
            ('diagnostic','get','secrets','test-app','no'),
            ('remediation','patch','deployments.apps','test-app','yes'),
            ('remediation','patch','deployments.apps','kube-system','no'),
            ('remediation','get','secrets','test-app','no')]:
            # kubectl auth can-i legitimately exits 1 for a denied permission.
            import subprocess
            run=subprocess.run([lab.kubectl,'--kubeconfig',state['kubeconfig'],'auth','can-i',verb,resource,
                '-n',namespace,'--as',f'system:serviceaccount:agentic-ops:agentic-ops-{role}'],
                capture_output=True,text=True,timeout=30)
            answer=run.stdout.strip()
            if run.returncode not in (0,1) or answer not in ('yes','no'):
                raise ValueError('Could not establish effective Kubernetes permission')
            result['checks'][f'{role}/{verb}/{resource}/{namespace}']=(answer==expected)
        for mode in ('allowed','denied'):
            name='protocol-net-'+uuid.uuid4().hex[:10]
            manifest=runner_manifest(trial.template,trial.image,PROBE,name,
                {'EVAL_PROBE_MODE':mode,'EVAL_GOOD_IMAGE':state['demoImage']})
            manifest['spec']['activeDeadlineSeconds']=90
            manifest['metadata']['labels']['role']='diagnostic' if mode=='allowed' else 'protocol-outsider'
            path=directory/(mode+'-probe.json');lab.save(path.name,manifest)
            created.append(name)
            lab.kube('create','-f',str(path))
            wait_until(lambda: lab.get('pod',name).get('status',{}).get('phase') in ('Succeeded','Failed'),
                       120,'Network probe did not finish')
            logs=lab.kube('logs',name,'-n','agentic-ops')
            (directory/(mode+'-probe.log')).write_text(logs)
            records=[]
            for line in logs.splitlines():
                try: record=json.loads(line)
                except ValueError: continue
                if record.get('event')=='infrastructure_probe': records.append(record)
            if len(records)!=1: raise ValueError('Missing probe result')
            if mode=='allowed':
                result['checks']['diagnostic/live-workload-identity']=records[0].get('workload_identity_authenticated') is True
                result['checks']['diagnostic/live-registry-read']=records[0].get('registry_read_succeeded') is True
                check='from azure.identity import WorkloadIdentityCredential; from agentic_ops.acr import AcrRegistry; from agentic_ops.safety import parse_image; import sys; c=WorkloadIdentityCredential(); c.get_token("https://management.azure.com/.default"); print(AcrRegistry(credential=c).exists(parse_image(sys.argv[1])))'
                result['checks']['remediation/live-workload-identity-registry-read']=lab.kube(
                    'exec','deployment/agentic-ops-remediation','-n','agentic-ops','--','python','-c',check,state['demoImage']).strip()=='True'
            statuses=records[0]['statuses']
            expected={'health':200,'missing_token':401,'wrong_token':401,'forbidden_namespace':403} if mode=='allowed' else {'health':'unreachable'}
            for key,value in expected.items(): result['checks'][mode+'/'+key]=(statuses.get(key)==value)
        after=lab.get('deployment','test-app','test-app')
        result['checks']['workload_unchanged']=(baseline['spec']==after['spec'] and
            baseline['metadata']['generation']==after['metadata']['generation'])
        result['verdict']='PASS' if all(result['checks'].values()) else 'AGENT_FAIL'
        result['egress']='Not asserted: inspect and report the cluster network profile and actual egress policies separately.'
        lab.save('cluster-network-profile.json',trial.aks.get('networkProfile',{}))
    except Exception as error:
        result['error']=f'{type(error).__name__}: {error}'
    finally:
        errors=[]
        for name in created:
            try: lab.kube('delete','pod',name,'-n','agentic-ops','--ignore-not-found=true','--timeout=60s')
            except Exception as error: errors.append(str(error))
        result['cleanup_errors']=errors
        if errors: result['verdict']='INCONCLUSIVE'
        lab.save('result.json',result)
    return result
