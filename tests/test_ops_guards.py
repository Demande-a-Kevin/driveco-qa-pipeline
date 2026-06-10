# tests/test_ops_guards.py
import pytest

import ops_guards
from ops_guards import (
    PreflightError,
    parse_required_manifest,
    validate_publish_config,
    run_preflight_or_abort,
    runtime_drift_report,
)

MANIFEST = """\
# commentaire
[required]
FOO_REQUIRED
BAR_REQUIRED
[warn]
BAZ_WARN
"""


def _write_manifest(tmp_path):
    p = tmp_path / ".env.qa.required"
    p.write_text(MANIFEST, encoding="utf-8")
    return p


def test_parse_manifest_sections(tmp_path):
    sections = parse_required_manifest(_write_manifest(tmp_path))
    assert sections["required"] == ["FOO_REQUIRED", "BAR_REQUIRED"]
    assert sections["warn"] == ["BAZ_WARN"]


def test_parse_missing_manifest_is_fail_open(tmp_path):
    sections = parse_required_manifest(tmp_path / "absent")
    assert sections == {"required": [], "warn": []}


def test_validate_detects_missing(tmp_path, monkeypatch):
    manifest = _write_manifest(tmp_path)
    monkeypatch.setenv("FOO_REQUIRED", "x")
    monkeypatch.delenv("BAR_REQUIRED", raising=False)
    monkeypatch.delenv("BAZ_WARN", raising=False)
    missing = validate_publish_config(manifest)
    assert missing["required"] == ["BAR_REQUIRED"]
    assert missing["warn"] == ["BAZ_WARN"]


def test_preflight_raises_and_alerts_on_missing_required(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_guards, "REQUIRED_MANIFEST", _write_manifest(tmp_path))
    monkeypatch.delenv("FOO_REQUIRED", raising=False)
    monkeypatch.delenv("BAR_REQUIRED", raising=False)
    monkeypatch.setenv("BAZ_WARN", "ok")
    alerts = []
    with pytest.raises(PreflightError):
        run_preflight_or_abort("daily", alerter=lambda m, l: alerts.append((l, m)))
    # une alerte critique listant les clés manquantes
    assert any(level == "critical" for level, _ in alerts)
    assert any("FOO_REQUIRED" in msg for _, msg in alerts)


def test_preflight_warns_but_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(ops_guards, "REQUIRED_MANIFEST", _write_manifest(tmp_path))
    monkeypatch.setenv("FOO_REQUIRED", "x")
    monkeypatch.setenv("BAR_REQUIRED", "y")
    monkeypatch.delenv("BAZ_WARN", raising=False)
    alerts = []
    run_preflight_or_abort("daily", alerter=lambda m, l: alerts.append((l, m)))  # ne lève pas
    assert any(level == "warning" for level, _ in alerts)


def test_runtime_drift_report(tmp_path):
    src = tmp_path / "src"
    rt = tmp_path / "rt"
    (src).mkdir()
    (rt).mkdir()
    (src / "a.py").write_text("print(1)\n")
    (rt / "a.py").write_text("print(1)\n")          # identique
    (src / "b.py").write_text("x = 1\n")
    (rt / "b.py").write_text("x = 2\n")             # diffère
    (src / "c.py").write_text("only_source = True\n")  # absent du runtime
    (src / "qa-driveco-data").mkdir()
    (src / "qa-driveco-data" / "ignored.py").write_text("ignore\n")  # ignoré

    drift = {d["file"]: d["status"] for d in runtime_drift_report(src, rt)}
    assert drift == {"b.py": "differs", "c.py": "missing_in_runtime"}
