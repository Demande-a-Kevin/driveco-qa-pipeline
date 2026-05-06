# runtime_config.py
"""Résolution centrale des configs runtime (DB QA-UCC > fichiers Git).

Lit `pipeline_config`, `rubric_versions`, `prompt_overrides` depuis QA-UCC
et merge avec les fichiers `system_prompt.txt` / `rubric.yaml` du runtime.
"""
from __future__ import annotations
import hashlib
import logging
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass
class RuntimeConfig:
    effective_prompt: str
    prompt_source: str  # "file" | "override"
    prompt_override_id: Optional[str] = None
    rubric_criteria: Optional[list[dict]] = None
    rubric_version_id: Optional[str] = None
    rubric_version_label: Optional[str] = None  # "db:v7" | "git:rubric.yaml@<sha>"
    pipeline_config_id: Optional[str] = None
    pipeline_config_payload: Optional[dict] = None
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)


def load_runtime_config(
    prompt_path: Path,
    rubric_path: Path,
    db,
) -> RuntimeConfig:
    """Résout la config effective.

    `db` doit exposer:
      - fetch_active_pipeline_config() -> dict | None
      - fetch_active_rubric() -> dict | None  ({id, version, criteria})
      - fetch_active_prompt_override() -> dict | None
        ({id, override_text, baseline_sha, active_until})
    """
    baseline_text = Path(prompt_path).read_text(encoding="utf-8")
    baseline_sha = _sha256(baseline_text)

    cfg = RuntimeConfig(effective_prompt=baseline_text, prompt_source="file")

    # 1. Pipeline config (I1-I4)
    pcfg = db.fetch_active_pipeline_config()
    if pcfg:
        cfg.pipeline_config_id = pcfg["id"]
        cfg.pipeline_config_payload = pcfg

    # 2. Rubric (I5)
    rubric = db.fetch_active_rubric()
    if rubric:
        cfg.rubric_criteria = rubric["criteria"]
        cfg.rubric_version_id = rubric["id"]
        cfg.rubric_version_label = f"db:v{rubric['version']}"
    else:
        rubric_text = Path(rubric_path).read_text(encoding="utf-8")
        cfg.rubric_criteria = (yaml.safe_load(rubric_text) or {}).get("criteria", [])
        cfg.rubric_version_label = f"git:rubric.yaml@{_sha256(rubric_text)[:8]}"

    # 3. Prompt override (I6, hybride P3)
    override = db.fetch_active_prompt_override()
    if override:
        active_until = _parse_dt(override.get("active_until"))
        now = datetime.now(timezone.utc)
        if active_until is None or active_until > now:
            cfg.prompt_source = "override"
            cfg.effective_prompt = override["override_text"]
            cfg.prompt_override_id = override["id"]
            if override.get("baseline_sha") and override["baseline_sha"] != baseline_sha:
                cfg.degraded = True
                msg = (
                    f"Drift détecté: override basé sur baseline_sha={override['baseline_sha'][:8]} "
                    f"mais runtime a {baseline_sha[:8]}"
                )
                cfg.warnings.append(msg)
                logger.warning(msg)
        # sinon: expiré → on retombe sur baseline (déjà initialisé)

    return cfg
