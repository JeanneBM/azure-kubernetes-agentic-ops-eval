"""Controlled handoff proxy and in-pod evaluator. No model calls, no cluster writes."""
from __future__ import annotations

import copy
import json
import logging
import os
import socket
import threading
import time
from dataclasses import replace
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def encode_report(report):
    """SDK to_dict snapshots contain datetime values, including nested managed fields."""
    def encode_date(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(f"Unsupported report value: {type(value).__name__}")

    return json.dumps(report, default=encode_date)


class HandoffProxy:
    """Forward exactly as requested; inject faults only after a confirmed upstream outcome."""

    def __init__(self, endpoint, token, mode, timeout, *, delay=100, client=None,
                 sleep=time.sleep, clock=time.monotonic):
        import httpx
        if mode not in {"delayed", "lost-ack"}:
            raise ValueError("unknown fault mode")
        self.endpoint, self.token, self.mode = endpoint.rstrip("/"), token, mode
        self.delay, self.sleep, self.clock = delay, sleep, clock
        self.client = client or httpx.Client(timeout=timeout, trust_env=False)
        self.requests = 0
        self.confirmed = []
        self.errors = []
        self.done = threading.Event()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass  # Never print headers or tokens.

            def do_POST(self):
                started = proxy.clock()
                proxy.requests += 1
                try:
                    if self.path != "/internal/v1/remediate":
                        self.send_error(404)
                        return
                    body = self.rfile.read(int(self.headers["Content-Length"]))
                    response = proxy.client.post(
                        proxy.endpoint + self.path, content=body,
                        headers={"Content-Type": "application/json", "X-Agent-Token": proxy.token},
                    )
                    response.raise_for_status()
                    result = response.json()
                    if result.get("executed") is not True or result.get("successful") is not True:
                        raise ValueError("upstream did not confirm successful execution")
                    proxy.confirmed.append(result)
                    if proxy.mode == "lost-ack":
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                    # Hold the acknowledgement until 100 s from request receipt,
                    # rather than adding 100 s to a possibly long rollout.
                    proxy.sleep(max(0, proxy.delay - (proxy.clock() - started)))
                    data = response.content
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as error:
                    proxy.errors.append(type(error).__name__)
                    self.close_connection = True
                finally:
                    proxy.done.set()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.client.close()


def image_only_change(before, after, good):
    """Exactly one generation and only api.image may change after injection."""
    expected = copy.deepcopy(before["spec"])
    containers = expected["template"]["spec"]["containers"]
    if len(containers) != 1 or containers[0]["name"] != "api":
        return False
    containers[0]["image"] = good
    return (expected == after["spec"]
            and after["metadata"]["generation"] == before["metadata"]["generation"] + 1)


def verdict(mode, result, elapsed, requests, confirmed, healthy, image_only, errors):
    if errors or not confirmed or not healthy:
        return "inconclusive"
    if requests != 1 or not image_only:
        return "fail"
    if mode == "delayed":
        return "pass" if (elapsed >= 100 and result.incident.status.value == "resolved"
                          and result.action_executed is True) else "fail"
    return "pass" if (result.incident.status.value == "escalated"
                      and result.action_executed is None) else "fail"


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from kubernetes import client, config
    from agentic_ops.aks import AksActionExecutor, AksDiagnosticProvider, workload_of
    from agentic_ops.contracts import ActionRequest, IncidentTrigger
    from agentic_ops.orchestrator import IncidentOrchestrator
    from agentic_ops.remote import HttpRemediationAgent
    from agentic_ops.timeouts import Timeouts

    mode = os.environ["EVAL_HANDOFF_MODE"]
    namespace = os.environ["AGENTIC_OPS_NAMESPACE"]
    good, bad = os.environ["EVAL_GOOD_IMAGE"], os.environ["EVAL_BAD_IMAGE"]
    correlation = os.environ["EVAL_CORRELATION_ID"]
    report = {"event": "handoff_trial_result", "mode": mode,
              "correlation_id": correlation, "verdict": "inconclusive"}
    try:
        if namespace != "test-app":
            raise ValueError("evaluator restricted to test-app")
        budgets = Timeouts.from_env()
        config.load_incluster_config()
        core, apps = client.CoreV1Api(), client.AppsV1Api()
        pod_name = os.environ["EVAL_FAILURE_POD"]
        pod = core.read_namespaced_pod(pod_name, namespace)
        if workload_of(apps, pod) != "test-app":
            raise ValueError("pod not owned by test-app")
        before = apps.read_namespaced_deployment("test-app", namespace).to_dict()
        # Kubernetes SDK uses snake_case; these fields are unchanged in both snapshots.
        source = AksDiagnosticProvider(core, apps)

        class ScriptedDiagnostics:
            def collect(self, trigger):
                facts = source.collect(trigger)
                if len(facts.pull_failures) != 1 or facts.pull_failures[0].image != bad:
                    raise ValueError("declared pull failure not observed")
                return replace(facts, safe_action=ActionRequest("fix_image", {"image": good}),
                               summary="Scripted proposal for controlled handoff transport trial")

        with HandoffProxy(os.environ["AGENTIC_OPS_REMEDIATION_URL"],
                          os.environ["AGENTIC_OPS_REMEDIATION_TOKEN"], mode,
                          budgets.handoff) as proxy:
            agent = HttpRemediationAgent(proxy.url, "local-evaluator", namespace,
                                         handoff_timeout=budgets.handoff, verify_timeout=budgets.verify)
            orchestrator = IncidentOrchestrator(ScriptedDiagnostics(), remediation_agent=agent)
            started = time.monotonic()
            result = orchestrator.handle(IncidentTrigger(namespace, pod_name, "test-app",
                                                        "ImagePullBackOff", correlation))
            elapsed = time.monotonic() - started
            if not proxy.done.wait(5):
                raise TimeoutError("proxy did not finish")
            after_object = apps.read_namespaced_deployment("test-app", namespace)
            after = after_object.to_dict()
            healthy = AksActionExecutor._rolled_out(after_object, "api", good)
            report.update(elapsed_seconds=elapsed, proxy_requests=proxy.requests,
                          upstream_confirmed=proxy.confirmed, proxy_errors=proxy.errors,
                          action_executed=result.action_executed, status=result.incident.status.value,
                          reason=result.incident.reason, before=before, after=after,
                          proposal_source="scripted", handoff_timeout=budgets.handoff,
                          verify_timeout=budgets.verify)
            report["verdict"] = verdict(mode, result, elapsed, proxy.requests,
                                        bool(proxy.confirmed), healthy,
                                        image_only_change(before, after, good), proxy.errors)
    except Exception as error:
        # Error types only: exception strings from HTTP libraries may contain endpoints.
        report["error"] = type(error).__name__
    print(encode_report(report), flush=True)
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
