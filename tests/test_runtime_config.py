# tests/test_runtime_config.py
import hashlib
from unittest.mock import MagicMock
from runtime_config import RuntimeConfig, load_runtime_config, _sha256

PROMPT_BASELINE = "Tu es un évaluateur QA…"


def test_sha256_stable():
    assert _sha256("abc") == hashlib.sha256(b"abc").hexdigest()


def test_load_no_overrides_returns_baseline(tmp_path):
    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text(PROMPT_BASELINE)
    rubric_file = tmp_path / "rubric.yaml"
    rubric_file.write_text("criteria: []")

    db = MagicMock()
    db.fetch_active_pipeline_config.return_value = None
    db.fetch_active_rubric.return_value = None
    db.fetch_active_prompt_override.return_value = None

    cfg = load_runtime_config(prompt_file, rubric_file, db)
    assert cfg.effective_prompt == PROMPT_BASELINE
    assert cfg.prompt_source == "file"
    assert cfg.prompt_override_id is None
    assert cfg.pipeline_config_id is None
    assert cfg.rubric_version_id is None
    assert cfg.degraded is False


def test_load_with_active_override_uses_override(tmp_path):
    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text(PROMPT_BASELINE)
    rubric_file = tmp_path / "rubric.yaml"
    rubric_file.write_text("criteria: []")
    baseline_sha = _sha256(PROMPT_BASELINE)

    db = MagicMock()
    db.fetch_active_pipeline_config.return_value = None
    db.fetch_active_rubric.return_value = None
    db.fetch_active_prompt_override.return_value = {
        "id": "ovr-1",
        "override_text": "OVERRIDE TEXT",
        "baseline_sha": baseline_sha,
        "active_until": None,
    }

    cfg = load_runtime_config(prompt_file, rubric_file, db)
    assert cfg.effective_prompt == "OVERRIDE TEXT"
    assert cfg.prompt_source == "override"
    assert cfg.prompt_override_id == "ovr-1"
    assert cfg.degraded is False


def test_drift_detected_when_baseline_sha_mismatch(tmp_path):
    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text(PROMPT_BASELINE)
    rubric_file = tmp_path / "rubric.yaml"
    rubric_file.write_text("criteria: []")

    db = MagicMock()
    db.fetch_active_pipeline_config.return_value = None
    db.fetch_active_rubric.return_value = None
    db.fetch_active_prompt_override.return_value = {
        "id": "ovr-2",
        "override_text": "OVERRIDE",
        "baseline_sha": "stale-sha",
        "active_until": None,
    }

    cfg = load_runtime_config(prompt_file, rubric_file, db)
    assert cfg.degraded is True
    assert cfg.warnings
    assert "drift" in cfg.warnings[0].lower()
    assert cfg.effective_prompt == "OVERRIDE"


def test_expired_override_falls_back(tmp_path):
    from datetime import datetime, timedelta, timezone
    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text(PROMPT_BASELINE)
    rubric_file = tmp_path / "rubric.yaml"
    rubric_file.write_text("criteria: []")
    past = datetime.now(timezone.utc) - timedelta(hours=1)

    db = MagicMock()
    db.fetch_active_pipeline_config.return_value = None
    db.fetch_active_rubric.return_value = None
    db.fetch_active_prompt_override.return_value = {
        "id": "ovr-3",
        "override_text": "OLD",
        "baseline_sha": _sha256(PROMPT_BASELINE),
        "active_until": past.isoformat(),
    }

    cfg = load_runtime_config(prompt_file, rubric_file, db)
    assert cfg.prompt_source == "file"
    assert cfg.effective_prompt == PROMPT_BASELINE


def test_active_rubric_replaces_yaml(tmp_path):
    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text(PROMPT_BASELINE)
    rubric_file = tmp_path / "rubric.yaml"
    rubric_file.write_text("criteria: []")

    db = MagicMock()
    db.fetch_active_pipeline_config.return_value = None
    db.fetch_active_prompt_override.return_value = None
    db.fetch_active_rubric.return_value = {
        "id": "rub-1",
        "version": 7,
        "criteria": [{"code": "tone", "weight": 0.3}],
    }

    cfg = load_runtime_config(prompt_file, rubric_file, db)
    assert cfg.rubric_version_id == "rub-1"
    assert cfg.rubric_version_label == "db:v7"
    assert cfg.rubric_criteria == [{"code": "tone", "weight": 0.3}]


def test_one_shot_overrides_take_priority_over_pipeline_config(tmp_path, monkeypatch):
    """Vérifie qu'un run manuel avec overrides dans llm_runs.params l'emporte sur pipeline_config."""
    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text(PROMPT_BASELINE)
    rubric_file = tmp_path / "rubric.yaml"
    rubric_file.write_text("criteria: []")

    db = MagicMock()
    db.fetch_active_pipeline_config.return_value = {
        "id": "pc-1",
        "phone_line_ids": ["785174"],
        "focus_note": "Focus depuis pipeline_config",
    }
    db.fetch_active_rubric.return_value = None
    db.fetch_active_prompt_override.return_value = None
    long_prompt = "ONE-SHOT PROMPT " * 5  # > 50 chars
    db.fetch_llm_run.return_value = {
        "id": "run-X",
        "params": {
            "phone_line_ids_override": ["1075934"],
            "focus_note_override": "Focus one-shot",
            "prompt_override_text": long_prompt,
        },
    }
    monkeypatch.setenv("PIPELINE_LLM_RUN_ID", "run-X")

    cfg = load_runtime_config(prompt_file, rubric_file, db)

    assert cfg.effective_phone_line_ids == ["1075934"]  # override wins
    assert cfg.effective_focus_note == "Focus one-shot"
    assert cfg.prompt_source == "override_one_shot"
    assert cfg.effective_prompt == long_prompt


def test_no_one_shot_falls_back_to_pipeline_config(tmp_path, monkeypatch):
    """Quand llm_runs.params est vide, fallback sur pipeline_config."""
    prompt_file = tmp_path / "system_prompt.txt"
    prompt_file.write_text(PROMPT_BASELINE)
    rubric_file = tmp_path / "rubric.yaml"
    rubric_file.write_text("criteria: []")

    db = MagicMock()
    db.fetch_active_pipeline_config.return_value = {
        "id": "pc-1",
        "phone_line_ids": ["785174", "1214611"],
        "focus_note": "Focus pipeline_config",
    }
    db.fetch_active_rubric.return_value = None
    db.fetch_active_prompt_override.return_value = None
    db.fetch_llm_run.return_value = {"id": "run-Y", "params": {}}
    monkeypatch.setenv("PIPELINE_LLM_RUN_ID", "run-Y")

    cfg = load_runtime_config(prompt_file, rubric_file, db)

    assert cfg.effective_phone_line_ids == ["785174", "1214611"]
    assert cfg.effective_focus_note == "Focus pipeline_config"
    assert cfg.prompt_source == "file"  # baseline, no override
