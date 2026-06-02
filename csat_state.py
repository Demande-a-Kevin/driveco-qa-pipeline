"""csat_state.py — Persistance JSON de l'état CSAT Insight."""
from __future__ import annotations
from pathlib import Path
import json

_DEFAULT = {"last_ts": "0", "pending": []}


def load_state(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"last_ts": str(data.get("last_ts", "0")),
                "pending": list(data.get("pending", []))}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_DEFAULT, pending=[])


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
