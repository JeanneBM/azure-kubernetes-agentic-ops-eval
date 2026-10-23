"""Read-only diagnostic trial worker. Host owns fault injection; live remote owns writes.

Warm before injection, then wait for a host-supplied request. All artifacts are
written before the terminal marker. No cloud/cluster mutation credentials added.
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
from kubernetes import client, config

from agentic_ops.acr import AcrRegistry, RegistryEvidenceProvider
from agentic_ops.aks import AksDiagnosticProvider, resolve_incident_trigger, resolve_pod_workload
from agentic_ops.baseline import BaselineDiagnosticProvider
from agentic_ops.contracts import IncidentTrigger, Facts
from agentic_ops.foundry import FoundryDiagnosticProvider
from agentic_ops.orchestrator import IncidentOrchestrator
from agentic_ops.remote import HttpRemediationAgent, FactsPayload
from agentic_ops.web import create_app
from agentic_ops.watcher import PodWatcher


def utc():
    return datetime.now(timezone.utc).isoformat()


def wait_file(path, seconds=240):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if Path(path).exists():
            return json.loads(Path(path).read_text())
        time.sleep(.2)
    raise TimeoutError(f'Control file unavailable: {path}')


class ModelRecorder:
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.client = httpx.Client(timeout=30)
    def post(self, url, **kwargs):
        item = {'request': kwargs['json'], 'request_utc': utc()}
        self.artifacts['model_calls'].append(item)
        response = self.client.post(url, **kwargs)
        item.update(response_utc=utc(), http_status=response.status_code)
        if response.is_success:
            item['response'] = response.json()
        return response


class Diagnostics:
    def __init__(self, provider, artifacts, *, barrier=None, stale=False, control_directory="/tmp"):
        self.provider, self.artifacts = provider, artifacts
        self.barrier, self.stale = barrier, stale
        self.control_directory=Path(control_directory)
    def collect(self, trigger):
        started = time.monotonic()
        facts = self.provider.collect(trigger)
        self.artifacts['diagnoses'].append(dict(
            utc=utc(), seconds=time.monotonic()-started, correlation_id=trigger.correlation_id,
            facts=FactsPayload.from_facts(facts).model_dump()))
        if self.stale and facts.safe_action is not None:
            (self.control_directory/'proposal-ready.json').write_text(json.dumps({'utc': utc()}))
            wait_file(self.control_directory/'release.json')
        if self.barrier:
            self.barrier.wait(timeout=45)
        return facts


class Remote(HttpRemediationAgent):
    def __init__(self, artifacts, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.artifacts = artifacts
    def remediate(self, trigger, facts):
        record = dict(correlation_id=trigger.correlation_id, utc=utc(),
                      facts=FactsPayload.from_facts(facts).model_dump())
        self.artifacts['handoffs'].append(record)
        result = super().remediate(trigger, facts)
        record.update(finished_utc=utc(), outcome=asdict(result))
        return result


def duplicates(core, apps, provider, remote, request, artifacts):
    """Each invocation lives in a distinct Kubernetes Pod/process."""
    import uvicorn
    ns,pod=request['namespace'],request['pod']
    diagnostics=Diagnostics(provider,artifacts,stale=True,control_directory=request.get("control_directory","/tmp"))
    orch=IncidentOrchestrator(diagnostics,remediation_agent=remote,
        resolve_trigger=lambda t:resolve_incident_trigger(core,apps,t))
    app=create_app(orch,resolve_workload=lambda n,p:resolve_pod_workload(core,apps,n,p),
                   webhook_token='local-eval-only')
    server=uvicorn.Server(uvicorn.Config(app,host='0.0.0.0',port=request.get('listen_port',18081),
                                       log_level='warning',lifespan='off'))
    thread=threading.Thread(target=server.run,daemon=True)
    thread.start()
    try:
        deadline=time.monotonic()+15
        while not server.started:
            if time.monotonic()>deadline: raise TimeoutError('Webhook listener did not start')
            time.sleep(.05)
        if request['replica']=='secondary':
            wait_file(Path(request.get('control_directory','/tmp'))/'finish.json',seconds=300)
            return
        peer=request['peer_url']
        pod_object=core.read_namespaced_pod(pod,ns)
        delivered=[]
        def watch_delivery():
            def handle(t):
                t=replace(t,correlation_id=request['correlation_id']+'-watch')
                result=orch.handle(t)
                delivered.append(dict(source='watcher',executed=result.action_executed,
                                      deduplicated=result.deduplicated,status=result.incident.status.value))
            return PodWatcher(core,apps,ns,handle).process_pod(pod_object)
        def webhook():
            payload=dict(namespace=ns,pod=pod,workload='test-app',reason='ImagePullBackOff',
                         correlation_id=request['correlation_id']+'-peer-http')
            # Peer may still be processing its host control file. Retry only the
            # read-only readiness request, never an incident POST.
            deadline=time.monotonic()+30
            with httpx.Client(timeout=210,trust_env=False) as http:
                while True:
                    try:
                        response=http.get(peer+'/healthz',timeout=2)
                        response.raise_for_status(); break
                    except httpx.HTTPError:
                        if time.monotonic()>deadline: raise
                        time.sleep(.2)
                response=http.post(peer+'/api/v1/incidents',json=payload,
                                   headers={'X-Webhook-Token':'local-eval-only'})
            if response.status_code in (404,409,422):
                delivered.append(dict(source='peer-webhook',status='target_gone_or_changed',
                                      http_status=response.status_code)); return
            response.raise_for_status()
            delivered.append(dict(source='peer-webhook',**response.json()))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(watch_delivery); second=pool.submit(webhook)
            first.result(timeout=240); second.result(timeout=240)
        watch_delivery(); webhook()
        artifacts['deliveries']=delivered
        artifacts['delivery_scope']='two actual Kubernetes Pods and independent processes; watcher plus pod-to-pod HTTP webhook; overlapping and sequential delivery'
    finally:
        server.should_exit=True; thread.join(timeout=10)


def single_delivery(core,apps,orchestrator,request,artifacts):
    outcomes=[]
    def handle(trigger):
        trigger=replace(trigger,correlation_id=request['correlation_id'])
        outcomes.append(orchestrator.handle(trigger))
    pod=core.read_namespaced_pod(request['pod'],request['namespace'])
    accepted=PodWatcher(core,apps,request['namespace'],handle).process_pod(pod)
    if not accepted or len(outcomes)!=1:
        raise ValueError('Observed failed Pod was not accepted by the production watcher')
    artifacts['delivery_mode']='host-observed failed Pod through production PodWatcher.process_pod'
    return outcomes[0]


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    artifacts = {'model_calls': [], 'diagnoses': [], 'handoffs': []}
    terminal = {'event':'protocol_terminal', 'worker_error':None}
    try:
        config.load_incluster_config()
        core, apps = client.CoreV1Api(), client.AppsV1Api()
        namespace = os.environ['AGENTIC_OPS_NAMESPACE']
        if namespace != 'test-app': raise ValueError('Only test-app lab namespace is supported')
        registry = AcrRegistry()
        from agentic_ops.safety import parse_image
        if not registry.exists(parse_image(os.environ['EVAL_GOOD_IMAGE'])):
            raise ValueError('Baseline image is missing')
        # Prime registry credentials and model access before t0. Warm-up is excluded.
        variant = os.environ['EVAL_VARIANT']
        recorder = ModelRecorder(artifacts)
        providers=[]
        for _ in range(1):
            evidence = RegistryEvidenceProvider(AksDiagnosticProvider(core, apps), registry,
                namespace=namespace, allowed_registries=os.environ['AGENTIC_OPS_ALLOWED_REGISTRIES'].split(','))
            providers.append(BaselineDiagnosticProvider(evidence) if variant == 'A' else
                FoundryDiagnosticProvider(evidence, endpoint=os.environ['AZURE_AI_FOUNDRY_ENDPOINT'],
                    deployment=os.environ['AZURE_AI_FOUNDRY_DEPLOYMENT'], http_client=recorder))
        if variant == 'C':
            # Token acquisition happens before injection; paid warm-up also recorded.
            token = providers[0]._token()
            response = recorder.client.post(
                f"{providers[0]._endpoint}/openai/deployments/{providers[0]._deployment}/chat/completions",
                params={'api-version':providers[0]._api_version}, headers={'Authorization':f'Bearer {token}'},
                json={'messages':[{'role':'user','content':'Reply OK.'}], 'temperature':0, 'max_tokens':8})
            response.raise_for_status()
            artifacts['warmup_usage'] = response.json().get('usage')
        ready = dict(event='protocol_ready', utc=utc())
        print(json.dumps(ready), flush=True)
        request = wait_file('/tmp/request.json', seconds=int(os.environ.get('EVAL_CONTROL_TIMEOUT','1200')))
        artifacts['request'] = request
        if request['scenario']=='S08':
            remote=Remote(artifacts, os.environ['AGENTIC_OPS_REMEDIATION_URL'],
                          os.environ['AGENTIC_OPS_REMEDIATION_TOKEN'], namespace)
            duplicates(core, apps, providers[0], remote, request, artifacts)
        else:
            remote=Remote(artifacts, os.environ['AGENTIC_OPS_REMEDIATION_URL'],
                          os.environ['AGENTIC_OPS_REMEDIATION_TOKEN'], namespace)
            diagnostics=Diagnostics(providers[0], artifacts, stale=request['scenario']=='S06')
            orch=IncidentOrchestrator(diagnostics, remediation_agent=remote,
                                     resolve_trigger=lambda t: resolve_incident_trigger(core, apps, t))
            result=single_delivery(core,apps,orch,request,artifacts)
            artifacts['decision'] = dict(status=result.incident.status.value, reason=result.incident.reason,
                executed=result.action_executed, summary=result.incident.facts.summary)
        terminal['finished_utc']=utc()
    except Exception as error:
        terminal['worker_error']=f'{type(error).__name__}: {error}'
    finally:
        artifacts['terminal']=terminal
        Path('/tmp/protocol-artifacts.json').write_text(json.dumps(artifacts))
        print(json.dumps(terminal), flush=True)
        time.sleep(600)  # host collects then deletes the worker


if __name__=='__main__':
    main()
