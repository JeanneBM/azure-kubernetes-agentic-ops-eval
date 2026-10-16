import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest

spec = importlib.util.spec_from_file_location("evidence_packager",
    Path(__file__).resolve().parents[1] / "scripts" / "packaging" / "sanitize-evidence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_packaging_preserves_outcome_and_anonymizes_consistently(tmp_path):
    source = tmp_path / "evidence"
    source.mkdir()
    identifier = "11111111-2222-3333-4444-555555555555"
    original = {"scenario": "S06", "verdict": "pass", "action_executed": False,
                "reference": identifier, "contact": "example@example.org"}
    raw = json.dumps(original)
    (source / "result.json").write_text(raw)
    (source / "log.txt").write_text(identifier)
    destination = tmp_path / "evidence.zip"
    module.package(source, destination)
    assert (source / "result.json").read_text() == raw
    with zipfile.ZipFile(destination) as archive:
        result = json.loads(archive.read("result.json"))
        assert result["verdict"] == "pass" and result["action_executed"] is False
        assert result["reference"] == archive.read("log.txt").decode()
        assert identifier not in str(result)
        assert "example@example.org" not in str(result)
        assert "mapping" not in json.loads(archive.read("ANONYMIZATION.json"))


def test_nested_archives_are_processed(tmp_path):
    source = tmp_path / "evidence"
    source.mkdir()
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("entry.json", '{"password":"example-secret"}')
    (source / "nested.zip").write_bytes(nested.getvalue())
    destination = tmp_path / "bundle.zip"
    module.package(source, destination)
    with zipfile.ZipFile(destination) as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read("nested.zip"))) as inner:
            assert json.loads(inner.read("entry.json"))["password"] == "REDACTED_SECRET"


def test_unsupported_input_does_not_leave_an_archive(tmp_path):
    source = tmp_path / "evidence"
    source.mkdir()
    (source / "unsupported.bin").write_bytes(b"\x89\x00\xff")
    destination = tmp_path / "bundle.zip"
    destination.write_bytes(b"old-output")
    with pytest.raises(ValueError):
        module.package(source, destination)
    assert not destination.exists()


@pytest.mark.parametrize("sample", [
    'INFO {"password": "sample-private", "api_key": "sample-private"}',
    'AGENTIC_OPS_REMEDIATION_TOKEN=sample-private',
    'token=sample-private',
    "secret: 'sample private value'",
    r'INFO {\"password\": \"sample-private\"}',
    'client_secret: sample-private',
])
def test_log_variants_are_processed(sample):
    result = module.Sanitizer().content("run.log", sample.encode()).decode()
    assert "sample-private" not in result
    assert "sample private value" not in result
    assert "REDACTED_SECRET" in result


def test_final_check_rejects_unprocessed_assignments(monkeypatch):
    sanitizer = module.Sanitizer()
    monkeypatch.setattr(sanitizer, "text", lambda value: value)
    with pytest.raises(ValueError):
        sanitizer.content("run.log", b'INFO {"password": "sample-private"}')


def test_pod_projected_token_metadata_packages_without_false_alarm(tmp_path):
    source = tmp_path / "evidence"
    source.mkdir()
    pod = {"items": [{"spec": {"volumes": [{"projected": {"sources": [
        {"serviceAccountToken": {"path": "token", "expirationSeconds": 3600}},
    ]}}], "containers": [{"env": [
        {"name": "ACCESS_TOKEN", "value": "sample-private"},
    ]}]}}]}
    raw = json.dumps(pod)
    (source / "agents-after.json").write_text(raw)
    destination = tmp_path / "S07.zip"
    module.package(source, destination)
    assert (source / "agents-after.json").read_text() == raw
    with zipfile.ZipFile(destination) as archive:
        result = json.loads(archive.read("agents-after.json"))
    spec = result["items"][0]["spec"]
    assert spec["volumes"][0]["projected"]["sources"][0]["serviceAccountToken"]["path"] == "token"
    assert spec["containers"][0]["env"][0]["value"] == "REDACTED_SECRET"


@pytest.mark.parametrize("value", [{"password": "sample-private"}, ["token=sample-private"]])
def test_nested_secret_containers_are_still_sanitized(value):
    raw = json.dumps({"serviceAccountToken": value})
    result = module.Sanitizer().content("pod.json", raw.encode()).decode()
    assert "sample-private" not in result
    assert "REDACTED_SECRET" in result

