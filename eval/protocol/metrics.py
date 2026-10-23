"""Extract actual timestamps; missing evidence stays null, never estimated."""
import json
from datetime import datetime, timezone


def records(text):
    for line in text.splitlines():
        offset=line.find('{')
        if offset<0: continue
        try: record=json.loads(line[offset:])
        except ValueError: continue
        yield record


def timing(artifacts,worker_log,remediation_log,t0,t_failure):
    ids={h['correlation_id'] for h in artifacts.get('handoffs',[])}
    ids.update(d['correlation_id'] for d in artifacts.get('diagnoses',[]))
    events=[]
    for record in records(worker_log+'\n'+remediation_log):
        event=record.get('agent_monitor_event')
        if event and event.get('run_id') in ids: events.append(event)
    def first(kind,agent=None,status=None):
        selected=[e['ts'] for e in events if e.get('type')==kind and
                  (agent is None or e.get('agent')==agent) and (status is None or e.get('status')==status)]
        return datetime.fromtimestamp(min(selected),timezone.utc).isoformat() if selected else None
    moments={'t0':t0,'t_failure':t_failure,'t_detect':first('run_started','diagnostic'),
             't_proposal':min((d['utc'] for d in artifacts.get('diagnoses',[])),default=None),
             't_authorized':first('policy_authorized'),'t_patch':first('patch_accepted'),
             't_healthy':first('verification',status='ok'),
             't_escalated':first('run_finished','diagnostic','escalated')}
    def interval(start,end):
        if not moments[start] or not moments[end]: return None
        value=(datetime.fromisoformat(moments[end])-datetime.fromisoformat(moments[start])).total_seconds()
        return value if value>=0 else None
    return dict(timestamps=moments,intervals={
        'injection_to_recovery':interval('t0','t_healthy'),
        'failure_to_recovery':interval('t_failure','t_healthy'),
        'detection':interval('t_failure','t_detect'),
        'diagnosis':interval('t_detect','t_proposal'),
        'authorization':interval('t_proposal','t_authorized'),
        'rollout':interval('t_patch','t_healthy')},
        clock_note='Host observations use host UTC and monotonic durations; agent events use pod epoch clocks. Negative cross-clock intervals are unavailable. No NTP accuracy claim.')
