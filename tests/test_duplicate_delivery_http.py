"""Real local HTTP/watch overlap with two isolated orchestrator states; no Azure."""
import copy
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from agentic_ops.agents import SafeRemediationAgent, RemediationOutcome
from agentic_ops.aks import AksActionExecutor
from agentic_ops.safety import StaleActionError
from conftest import FakeDiagnostics, make_facts, make_policy
from scenarios.support import FakeCluster
from eval.protocol.inpod import duplicates


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def test_watcher_and_actual_http_overlap_into_two_independent_states(tmp_path):
    cluster=FakeCluster()
    agent=SafeRemediationAgent(make_policy(),AksActionExecutor(cluster,verify_timeout=1,poll_interval=0))
    write_lock=threading.Lock()
    artifacts=[{'diagnoses':[],'handoffs':[],'model_calls':[]} for _ in range(2)]
    class Remote:
        def __init__(self,record): self.record=record
        def manages(self,ns): return ns=='test-app'
        def remediate(self,trigger,facts):
            with write_lock:
                try: outcome=agent.remediate(trigger,facts)
                except StaleActionError:
                    outcome=RemediationOutcome(None,False,False,'second agent policy: stale action')
            self.record['handoffs'].append({'correlation_id':trigger.correlation_id,'outcome':asdict(outcome)})
            return outcome
    first,second=port(),port()
    directories=[tmp_path/'primary',tmp_path/'secondary']
    for path in directories: path.mkdir()
    request={'namespace':'test-app','pod':cluster.pod.metadata.name,'correlation_id':'duplicate-fixture',
             'peer_url':f'http://127.0.0.1:{second}'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        peer=pool.submit(duplicates,cluster,cluster,FakeDiagnostics(make_facts()),Remote(artifacts[1]),
            dict(request,replica='secondary',listen_port=second,control_directory=str(directories[1])),artifacts[1])
        primary=pool.submit(duplicates,cluster,cluster,FakeDiagnostics(make_facts()),Remote(artifacts[0]),
            dict(request,replica='primary',listen_port=first,control_directory=str(directories[0])),artifacts[0])
        try:
            deadline=time.monotonic()+15
            while not all((p/'proposal-ready.json').exists() for p in directories):
                if primary.done(): primary.result()
                if peer.done(): peer.result()
                assert time.monotonic()<deadline,'Both proposal barriers must be reached before releasing either'
                time.sleep(.05)
            for path in directories: (path/'release.json').write_text('{}')
            primary.result(timeout=20)
        finally:
            for path in directories:
                (path/'release.json').write_text('{}')
                (path/'finish.json').write_text('{}')
        peer.result(timeout=15)
    assert len(cluster.patches)==1
    assert sum(h['outcome']['executed'] is True for a in artifacts for h in a['handoffs'])==1
    assert len(artifacts[0]['diagnoses'])==len(artifacts[1]['diagnoses'])==1
    assert {'watcher','peer-webhook'} <= {d['source'] for d in artifacts[0]['deliveries']}
    assert any(d.get('deduplicated') for d in artifacts[0]['deliveries'])
