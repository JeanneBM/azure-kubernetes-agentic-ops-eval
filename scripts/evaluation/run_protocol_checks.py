"""Offline S/K/P catalog runner. No Azure calls; known failures are not passes."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = {
    **{f"S{i:02}": [f"tests/scenarios/{name}"] for i, name in enumerate([
        "test_s01_repository_transposition.py", "test_s02_healthy_sidecar.py",
        "test_s03_missing_image.py", "test_s04_pull_authentication.py",
        "test_s05_two_pull_failures.py", "test_s06_stale_diagnosis.py",
        "test_s07_injected_event.py"], 1)},
    "S08": ["tests/test_security_runner.py::test_s08_controlled_watcher_duplicates_execute_once"],
    "S09": ["tests/test_security_runner.py::test_scripted_policy_probes_require_specific_refusal_without_mutation", "-k", "S09"],
    "S10": ["tests/test_security_runner.py::test_scripted_policy_probes_require_specific_refusal_without_mutation", "-k", "S10"],
    **{f"K{i:02}": ["tests/scenarios/test_known_limits.py", "-k", f"test_K{i:02}"] for i in range(1, 4)},
    **{f"P{i:02}": ["tests/scenarios/test_protocol_contracts.py", "-k", f"test_P{i:02}"] for i in range(1, 9)},
}


def classify(returncode, xml_path):
    if not xml_path.exists():
        return "INCONCLUSIVE", 0
    try:
        cases = ET.parse(xml_path).getroot().findall(".//testcase")
        errors = ET.parse(xml_path).getroot().findall(".//error")
    except ET.ParseError:
        return "INCONCLUSIVE", 0
    if errors or not cases or returncode not in (0, 1):
        return "INCONCLUSIVE", len(cases)
    if any(case.find("failure") is not None for case in cases):
        return "AGENT_FAIL", len(cases)
    skipped = [case.find("skipped") for case in cases if case.find("skipped") is not None]
    if any(item.get("type") == "pytest.xfail" for item in skipped):
        return "AGENT_FAIL", len(cases)
    if skipped:
        return "INCONCLUSIVE", len(cases)
    return ("PASS" if returncode == 0 else "INCONCLUSIVE"), len(cases)


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / ".local" / "reports" / f"protocol-{stamp}-{uuid.uuid4().hex[:6]}"
    out.mkdir(parents=True)
    rows = []
    for scenario, selection in CATALOG.items():
        xml_path = out / f"{scenario}.xml"
        process = subprocess.run(
            [sys.executable, "-m", "pytest", *selection, "-q", "-rxX", f"--junitxml={xml_path}"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / f"{scenario}.log").write_text(process.stdout, encoding="utf-8")
        verdict, count = classify(process.returncode, xml_path)
        rows.append(dict(scenario=scenario, verdict=verdict, cases=count,
                         pytest_exit=process.returncode, log=f"{scenario}.log"))
        print(f"{scenario}: {verdict} ({count} cases)", flush=True)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              text=True, capture_output=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           text=True, capture_output=True)
    report = dict(environment="offline-mocked", source_commit=revision.stdout.strip(),
                  working_tree_dirty=bool(dirty.stdout.strip()), results=rows)
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# Offline protocol checks", "", "Controlled model and registry responses; no live AKS or real-model claim.",
             "", "| Scenario | Verdict | Cases |", "|---|---|---|"]
    lines.extend(f"| {r['scenario']} | {r['verdict']} | {r['cases']} |" for r in rows)
    lines += ["", "Known xfails count as AGENT_FAIL, never PASS. Inspect per-scenario logs.",
              "PASS covers only the selected offline fixture, not all live protocol requirements."]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out / "summary.md")
    return 0 if all(r["verdict"] == "PASS" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
