import pytest
from pathlib import Path
import obsidian_reporter


def test_publish_run_writes_md(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "OBSIDIAN_VAULT_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(config, "OBSIDIAN_REPORTS_SUBDIR", "QA", raising=False)

    import report_formatter
    monkeypatch.setattr(report_formatter, "render_run", lambda r: "# Run report\n\nBody.")

    run = {
        "id": "daily:2026-05-15:20260515T100000Z",
        "mode": "daily",
        "started_at": "2026-05-15T10:00:00+00:00",
        "ended_at": "2026-05-15T10:05:00+00:00",
        "status": "success",
        "calls_count": 42,
        "errors_count": 0,
    }
    out = obsidian_reporter.publish_run(run)

    assert out.exists()
    assert out.parent.name == "Daily"
    text = out.read_text()
    assert "run_id:" in text
    assert "# Run report" in text


def test_publish_run_sanitizes_filename(tmp_path, monkeypatch):
    import config
    import report_formatter
    monkeypatch.setattr(config, "OBSIDIAN_VAULT_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(config, "OBSIDIAN_REPORTS_SUBDIR", "QA", raising=False)
    monkeypatch.setattr(report_formatter, "render_run", lambda r: "body")

    run = {
        "id": "weekly:has/slashes:and spaces",
        "mode": "weekly",
        "started_at": "2026-05-15T10:00:00+00:00",
        "status": "success",
    }
    out = obsidian_reporter.publish_run(run)
    assert "/" not in out.name
    assert out.parent.name == "Weekly"
