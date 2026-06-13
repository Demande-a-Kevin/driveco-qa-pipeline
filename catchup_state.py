"""catchup_state.py — État local du rattrapage de couverture QA (chantier 0.6).

Quand le run de nuit coupe au budget, les appels éligibles non analysés sont
marqués `pending` ici. Un run `--mode catchup` (launchd 09:30/14:00) les reprend
plus tard dans la journée et poste en fil du post Slack quotidien.

État volontairement local (fichiers JSON dans REPORT_OUTPUT_DIR), additif et sans
dépendance réseau : la garantie de couverture ne doit pas dépendre de Supabase.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import config

_DIR = config.REPORT_OUTPUT_DIR


def _pending_path(date: datetime) -> Path:
    return _DIR / f".qa_pending_{date.strftime('%Y-%m-%d')}.json"


def _slack_ref_path(date: datetime) -> Path:
    return _DIR / f".slack_daily_ref_{date.strftime('%Y-%m-%d')}.json"


def save_pending(date: datetime, call_ids: list[str]) -> None:
    """Enregistre la liste des appels éligibles NON analysés (budget atteint).
    Liste vide → on retire le fichier (couverture complète)."""
    path = _pending_path(date)
    ids = [str(c) for c in call_ids if c]
    try:
        if not ids:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "date": date.strftime("%Y-%m-%d"),
            "call_ids": ids,
            "created_at": int(time.time()),
        }), encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        print(f"[catchup_state] ⚠️ save_pending KO: {exc}")


def load_pending(date: datetime) -> list[str]:
    path = _pending_path(date)
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(c) for c in (data.get("call_ids") or []) if c]
    except (OSError, json.JSONDecodeError):
        return []


def clear_pending(date: datetime, analyzed_ids: list[str]) -> list[str]:
    """Retire les `analyzed_ids` des pending du jour. Retourne le reliquat restant."""
    remaining = [c for c in load_pending(date) if c not in set(str(i) for i in analyzed_ids)]
    save_pending(date, remaining)
    return remaining


def save_daily_slack_ref(date: datetime, channel: str, ts: str) -> None:
    """Mémorise (channel, ts) du post Slack quotidien pour y répondre en fil."""
    if not ts or not isinstance(ts, str):
        return
    try:
        path = _slack_ref_path(date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"channel": channel, "ts": ts}), encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        print(f"[catchup_state] ⚠️ save_daily_slack_ref KO: {exc}")


def load_daily_slack_ref(date: datetime) -> tuple[str, str] | None:
    path = _slack_ref_path(date)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = data.get("ts")
        if ts:
            return data.get("channel") or config.SLACK_CHANNEL_ID, ts
    except (OSError, json.JSONDecodeError):
        pass
    return None
