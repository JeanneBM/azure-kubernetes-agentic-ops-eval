"""Host driver: explicit recorded AKS lab only; no provisioning or model requests."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def command(args, *, timeout=180):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout)
    if result.returncode:
        # Never include command arguments (runner source/env) in an error.
        raise RuntimeError(f"{Path(args[0]).name} {args[1]} failed: {result.stderr[-1500:]}")
    return result.stdout


class Lab:
    def __init__(self, state, evidence):
        self.state, self.evidence = state, evidence
        self.kubectl = shutil.which("kubectl")
        if not self.kubectl or not state.get("kubeconfig"):
            raise ValueError("kubectl and recorded kubeconfig are required")

    def kube(self, *args):
        return command([self.kubectl, "--kubeconfig", self.state["kubeconfig"], *args])

    def get(self, kind, name=None, namespace="agentic-ops", label=None):
        args = ["get", kind]
        if name:
            args.append(name)
        args += ["-n", namespace, "-o", "json"]
        if label:
            args += ["-l", label]
        return json.loads(self.kube(*args))

    def save(self, name, value):
        (self.evidence / name).write_text(json.dumps(value, indent=2), encoding="utf-8")

    def rollout(self, name, namespace):
        self.kube("rollout", "status", f"deployment/{name}", "-n", namespace, "--timeout=120s")

    def set_image(self, image):
        self.kube("set", "image", "deployment/test-app", f"api={image}", "-n", "test-app")


def runner_manifest(template, image, code, name, env):
    spec = copy.deepcopy(template["spec"]["template"]["spec"])
    if len(spec["containers"]) != 1 or spec.get("initContainers"):
        raise ValueError("single-container diagnostic template required")
    spec["restartPolicy"] = "Never"
    spec["activeDeadlineSeconds"] = 420
    container = spec["containers"][0]
    container.update(image=image, command=["python", "-u", "-c", code], args=[])
    for field in ("livenessProbe", "readinessProbe", "startupProbe"):
        container.pop(field, None)
    container["env"] = [e for e in container.get("env", []) if not e["name"].startswith("EVAL_")]
    container["env"] += [{"name": k, "value": v} for k, v in env.items()]
    labels = copy.deepcopy(template["spec"]["template"].get("metadata", {}).get("labels", {}))
    labels.pop("pod-template-hash", None)
    labels.update(app="agentic-ops", role="diagnostic", eval="handoff")
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {
        "name": name, "namespace": "agentic-ops", "labels": labels}, "spec": spec}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-group", default="rg-agentic-ops-lab")
    parser.add_argument("--evidence-dir", type=Path)
    options = parser.parse_args()
    if options.resource_group != "rg-agentic-ops-lab":
        raise ValueError("this evaluator is restricted to rg-agentic-ops-lab")
    root = Path(__file__).resolve().parents[2]
    state = json.loads((root / ".local" / f"{options.resource_group}.json").read_text(encoding="utf-8-sig"))
    if state["resourceGroup"] != options.resource_group:
        raise ValueError("recorded lab mismatch")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = options.evidence_dir or root / ".local/evidence/handoff" / f"{stamp}-{uuid.uuid4().hex[:6]}"
    evidence.mkdir(parents=True)
    lab = Lab(state, evidence)
    reports, errors, cleanup_errors = [], [], []
    paused, runner_name, replicas = False, None, None
    good = state["demoImage"]
    if not good.endswith("/test-app:1.4.2"):
        raise ValueError("expected recorded test-app:1.4.2 image")
    bad = good.replace("/test-app:", "/tset-app:")
    try:
        # Verify subscription/resource identity before the first cluster mutation.
        az = shutil.which("az")
        if not az:
            raise ValueError("Azure CLI required for recorded cluster identity check")
        aks = json.loads(command([az, "aks", "show", "-g", state["resourceGroup"],
                                  "-n", state["aksName"], "--subscription", state["subscriptionId"],
                                  "--only-show-errors", "-o", "json"]))
        server = lab.kube("config", "view", "--minify", "-o",
                          "jsonpath={.clusters[0].cluster.server}").strip()
        if urlparse(server).hostname not in {aks.get("fqdn"), aks.get("privateFqdn")}:
            raise ValueError("kubeconfig does not match recorded AKS")
        diagnostic = lab.get("deployment", "agentic-ops-diagnostic")
        replicas = diagnostic["spec"]["replicas"]
        if replicas not in (0, 1):
            raise ValueError("expected at most one diagnostic replica")
        remediation = lab.get("deployment", "agentic-ops-remediation")
        if remediation["spec"]["replicas"] != 1:
            raise ValueError("one remediation replica required")
        lab.rollout("agentic-ops-remediation", "agentic-ops")
        pods = lab.get("pods", label="app=agentic-ops,role=remediation")["items"]
        pods = [p for p in pods if not p["metadata"].get("deletionTimestamp")]
        if len(pods) != 1:
            raise ValueError("one active remediation pod required")
        status = pods[0]["status"]["containerStatuses"]
        if len(status) != 1 or not status[0]["ready"]:
            raise ValueError("remediation pod not ready")
        digest = re.search(r"sha256:[a-f0-9]{64}$", status[0]["imageID"])
        if not digest:
            raise ValueError("cannot establish remediation runtime digest")
        image_repo = re.sub(r":[^/:]+$", "", remediation["spec"]["template"]["spec"]["containers"][0]["image"].split("@")[0])
        recorded_repo = re.sub(r":[^/:]+$", "", state["agentImage"].split("@")[0])
        if image_repo != recorded_repo:
            raise ValueError("runtime agent repository differs from recorded lab")
        image = image_repo + "@" + digest.group()
        code = (Path(__file__).parent / "trial.py").read_text(encoding="utf-8")
        lab.save("provenance.json", {"evaluatorCommit": command(["git", "-C", str(root), "rev-parse", "HEAD"]).strip(),
                 "runnerSha256": hashlib.sha256(code.encode()).hexdigest(), "runtimeImage": image,
                 "agentSourceCommit": "not independently established", "proposalSource": "scripted"})
        baseline = lab.get("deployment", "test-app", "test-app")
        containers = baseline["spec"]["template"]["spec"]["containers"]
        if len(containers) != 1 or containers[0]["name"] != "api" or containers[0]["image"] != good:
            raise ValueError("healthy single-api test-app baseline required; run S01 first")
        lab.rollout("test-app", "test-app")
        lab.save("deployment-before.json", baseline)
        paused = True
        lab.kube("scale", "deployment/agentic-ops-diagnostic", "-n", "agentic-ops", "--replicas=0")
        lab.kube("wait", "--for=delete", "pods", "-n", "agentic-ops",
                 "-l", "app=agentic-ops,role=diagnostic", "--timeout=90s")
        for mode in ("delayed", "lost-ack"):
            print(f"Starting {mode}: real remediation, scripted proposal", flush=True)
            lab.set_image(bad)
            injected = lab.get("deployment", "test-app", "test-app")
            lab.save(f"{mode}-injected.json", injected)
            deadline = time.monotonic() + 120
            failed = None
            while time.monotonic() < deadline:
                for pod in lab.get("pods", namespace="test-app", label="app=test-app")["items"]:
                    if pod["metadata"].get("deletionTimestamp"):
                        continue
                    for status in pod["status"].get("containerStatuses", []):
                        if status["name"] == "api" and status.get("state", {}).get("waiting", {}).get("reason") in {"ErrImagePull", "ImagePullBackOff"}:
                            if any(c["name"] == "api" and c["image"] == bad for c in pod["spec"]["containers"]):
                                failed = pod["metadata"]["name"]
                if failed:
                    break
                time.sleep(2)
            if not failed:
                raise TimeoutError("injected pull failure was not observed")
            runner_name = f"handoff-{mode}-{uuid.uuid4().hex[:8]}"
            manifest = runner_manifest(diagnostic, image, code, runner_name, {
                "EVAL_HANDOFF_MODE": mode, "EVAL_FAILURE_POD": failed,
                "EVAL_GOOD_IMAGE": good, "EVAL_BAD_IMAGE": bad, "EVAL_CORRELATION_ID": runner_name,
            })
            manifest_path = evidence / f"{mode}-pod.json"
            lab.save(manifest_path.name, manifest)
            lab.kube("create", "-f", str(manifest_path))
            deadline, report = time.monotonic() + 450, None
            while time.monotonic() < deadline:
                phase = lab.get("pod", runner_name)["status"]["phase"]
                if phase in {"Succeeded", "Failed"}:
                    logs = lab.kube("logs", runner_name, "-n", "agentic-ops", "--timestamps")
                    (evidence / f"{mode}.log").write_text(logs, encoding="utf-8")
                    for line in logs.splitlines():
                        offset = line.find("{")
                        if offset < 0:
                            continue
                        try:
                            record = json.loads(line[offset:])
                        except ValueError:
                            continue
                        if record.get("event") == "handoff_trial_result" and record.get("correlation_id") == runner_name:
                            report = record
                    break
                time.sleep(3)
            if not report:
                raise TimeoutError("runner has no terminal result; inspect pod/logs")
            # Rule out intervening changes between host injection and in-pod collection.
            before = report.get("before", {})
            if before.get("metadata", {}).get("generation") != injected["metadata"]["generation"]:
                report["verdict"] = "inconclusive"
                report["attribution_error"] = "Deployment changed before handoff"
            current = lab.get("deployment", "test-app", "test-app")
            if (current["metadata"]["uid"] != report.get("after", {}).get("metadata", {}).get("uid")
                    or current["metadata"]["generation"] != report.get("after", {}).get("metadata", {}).get("generation")):
                report["verdict"] = "inconclusive"
                report["attribution_error"] = "Deployment changed after handoff"
            reports.append(report)
            lab.save(f"{mode}-result.json", report)
            print(f"{mode}: {report['verdict']}", flush=True)
            lab.kube("delete", "pod", runner_name, "-n", "agentic-ops", "--wait=true", "--timeout=60s")
            runner_name = None
            if report["verdict"] != "pass":
                raise RuntimeError("trial did not pass; subsequent trial skipped")
    except Exception as error:
        errors.append(str(error))
    finally:
        if paused:
            # Collect first; always attempt cleanup even when collection fails.
            for name, get_args in (("deployment-final.json", ("deployment", "test-app", "test-app")),
                                   ("agents-final.json", ("pods",))):
                try:
                    lab.save(name, lab.get(*get_args))
                except Exception as error:
                    cleanup_errors.append(str(error))
            try:
                (evidence / "remediation.log").write_text(lab.kube("logs", "deployment/agentic-ops-remediation",
                    "-n", "agentic-ops", "--timestamps"), encoding="utf-8")
                if runner_name:
                    (evidence / "runner-final.log").write_text(lab.kube("logs", runner_name,
                        "-n", "agentic-ops", "--timestamps"), encoding="utf-8")
            except Exception as error:
                cleanup_errors.append(str(error))
            if runner_name:
                try:
                    lab.kube("delete", "pod", runner_name, "-n", "agentic-ops", "--ignore-not-found=true", "--timeout=60s")
                except Exception as error:
                    cleanup_errors.append(str(error))
            try:
                lab.set_image(good)
                lab.rollout("test-app", "test-app")
                lab.kube("scale", "deployment/agentic-ops-diagnostic", "-n", "agentic-ops", f"--replicas={replicas}")
                if replicas:
                    lab.rollout("agentic-ops-diagnostic", "agentic-ops")
            except Exception as error:
                cleanup_errors.append("Restore failed; diagnostic may remain paused: " + str(error))
        summary = {"verdict": "fail" if any(r["verdict"] == "fail" for r in reports) else
                   "pass" if len(reports) == 2 and all(r["verdict"] == "pass" for r in reports)
                   and not errors and not cleanup_errors else "inconclusive",
                   "errors": errors, "cleanup_errors": cleanup_errors,
                   "trials": [{k: r.get(k) for k in ("mode", "verdict", "elapsed_seconds", "action_executed", "proxy_requests")} for r in reports]}
        lab.save("summary.json", summary)
        print(json.dumps(summary, indent=2), flush=True)
        print(f"Evidence: {evidence}", flush=True)
    return 0 if summary["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
