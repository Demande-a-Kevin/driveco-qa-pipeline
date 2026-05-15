"""obsidian_reporter.py — publie les rapports QA dans la vault Obsidian.

Pour chaque run, écrit un fichier `.md` dans
    <OBSIDIAN_VAULT_DIR>/<OBSIDIAN_REPORTS_SUBDIR>/<scope>/<date>__<mode>__<id>.md

avec frontmatter YAML (run_id, mode, date, status, etc.) + le corps Markdown
produit par `report_formatter.render_run(run)`.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import config
import report_formatter

log = logging.getLogger(__name__)

# Sous-dossier où ranger les rapports QA dans la vault.
# Fallback raisonnable si pas dans config.
DEFAULT_REPORTS_SUBDIR = "Pro - Driveco/Driveco x UCC QA"


def _reports_root() -> Path:
    vault = Path(str(getattr(config, "OBSIDIAN_VAULT_DIR", "") or ""))
    if not str(vault):
        raise RuntimeError("OBSIDIAN_VAULT_DIR non configuré (config.py)")
    subdir = getattr(config, "OBSIDIAN_REPORTS_SUBDIR", DEFAULT_REPORTS_SUBDIR)
    return vault / subdir


def _scope_folder(mode: str) -> str:
    if mode == "daily":
        return "Daily"
    if mode == "weekly":
        return "Weekly"
    if mode == "single_call":
        return "Single calls"
    return "Misc"


def _sanitize_filename(s: str) -> str:
    s = re.sub(r"[^\w\-.]+", "_", s).strip("_")
    return s[:200] if len(s) > 200 else s


def publish_run(run: dict[str, Any]) -> Path:
    """Écrit un .md dans la vault Obsidian pour ce run.

    `run` doit être un dict avec au minimum : id, mode, started_at, ended_at, status.
    Réutilise `report_formatter.render_run(run)` pour le corps Markdown.

    Retourne le `Path` du fichier écrit.
    """
    md_body = report_formatter.render_run(run)

    started = run.get("started_at") or datetime.utcnow().isoformat()
    date_str = str(started)[:10]
    mode = run.get("mode") or "misc"
    scope_folder = _scope_folder(mode)
    run_id = str(run.get("id", "unknown"))

    out_dir = _reports_root() / scope_folder
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = _sanitize_filename(f"{date_str}__{mode}__{run_id}") + ".md"
    out_path = out_dir / filename

    frontmatter = (
        "---\n"
        f'run_id: "{run_id}"\n'
        f'mode: "{mode}"\n'
        f'started_at: "{started}"\n'
        f'ended_at: "{run.get("ended_at") or ""}"\n'
        f'status: "{run.get("status", "")}"\n'
        f'calls_count: {run.get("calls_count") or 0}\n'
        f'errors_count: {run.get("errors_count") or 0}\n'
        'source: "cockpit-republish"\n'
        f'published_at: "{datetime.utcnow().isoformat()}"\n'
        "tags: [qa, driveco-ucc]\n"
        "---\n\n"
    )

    out_path.write_text(frontmatter + md_body, encoding="utf-8")
    log.info("Obsidian republish: wrote %s", out_path)
    return out_path


# Wrapper compatible avec report_republish.py qui appelle <module>.republish_run(run)
def republish_run(run: dict[str, Any]) -> Path:
    return publish_run(run)
