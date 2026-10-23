"""Report must not turn expected safety failures or skipped checks into passes."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("protocol_report", Path(__file__).parents[1] / "scripts/evaluation/run_protocol_checks.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize("body,code,expected", [
    ('<testcase name="safe"/>', 0, "PASS"),
    ('<testcase><skipped type="pytest.xfail"/></testcase>', 0, "AGENT_FAIL"),
    ('<testcase><failure message="unsafe mutation"/></testcase>', 1, "AGENT_FAIL"),
    ('<testcase><skipped/></testcase>', 0, "INCONCLUSIVE"),
    ('<testcase><error/></testcase>', 1, "INCONCLUSIVE"),
    ('', 5, "INCONCLUSIVE"),
    ('<testcase/>', 2, "INCONCLUSIVE"),
])
def test_report_preserves_failures_and_missing_evidence(tmp_path, body, code, expected):
    path = tmp_path / "results.xml"
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    assert runner.classify(code, path)[0] == expected


def test_missing_and_corrupt_reports_are_inconclusive(tmp_path):
    path = tmp_path / 'missing.xml'
    assert runner.classify(0, path) == ('INCONCLUSIVE', 0)
    path.write_text('<broken')
    assert runner.classify(0, path) == ('INCONCLUSIVE', 0)


def test_mixed_success_and_failure_preserves_case_count(tmp_path):
    path = tmp_path / 'mixed.xml'
    path.write_text('<testsuites><testsuite><testcase/><testcase><failure/></testcase></testsuite></testsuites>')
    assert runner.classify(1, path) == ('AGENT_FAIL', 2)


def test_nonzero_exit_without_failure_is_not_pass(tmp_path):
    path = tmp_path / 'result.xml'
    path.write_text('<testsuite><testcase/></testsuite>')
    assert runner.classify(1, path) == ('INCONCLUSIVE', 1)
