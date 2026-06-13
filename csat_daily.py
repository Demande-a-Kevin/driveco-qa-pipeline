"""csat_daily.py — Score CSAT moyen du jour analysé (x/5).

Le cockpit agrège la CSAT, mais c'est dans un autre projet Supabase. Inutile de
dépendre cross-projet : le pipeline lit déjà les sondages Sprig du canal CSAT
(C0B724V5X4L) et `csat_parser.parse_sprig` en extrait le score 1-5 par appel.
On calcule donc le CSAT du jour ici, en réutilisant ces briques.
"""
from __future__ import annotations

import logging
from datetime import datetime

import config
import csat_slack
import csat_parser

log = logging.getLogger("csat_daily")
SPRIG_USER_ID = "U0798UDP7U0"  # même auteur que csat_insight

try:
    from zoneinfo import ZoneInfo
    _PARIS = ZoneInfo("Europe/Paris")
except Exception:  # noqa: BLE001
    _PARIS = None


def _day_start_epoch(day: datetime) -> int:
    if _PARIS is not None:
        return int(datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=_PARIS).timestamp())
    return int(datetime(day.year, day.month, day.day).timestamp())


def daily_csat_for_calls(day: datetime, call_ids: set[str] | None = None) -> dict:
    """CSAT moyen (x/5) des sondages Sprig du jour analysé.

    Lit le canal CSAT depuis le début du jour (heure Paris). Si `call_ids` est
    fourni, ne garde que les sondages rattachés à ces appels (CSAT des appels du
    jour) ; sinon, tous les sondages du jour. Best-effort : ne bloque jamais le run.
    Retourne {"avg": float|None, "n": int}.
    """
    if getattr(config, "DISABLE_CSAT_INSIGHT", False):
        return {"avg": None, "n": 0}
    if not config.SLACK_CSAT_CHANNEL_ID:
        return {"avg": None, "n": 0}
    oldest = str(_day_start_epoch(day))
    try:
        msgs = csat_slack.fetch_new_sprig_posts(
            config.SLACK_CSAT_CHANNEL_ID, oldest, SPRIG_USER_ID, limit=200
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("[csat_daily] fetch Sprig KO: %s", exc)
        return {"avg": None, "n": 0}

    ids = {str(c) for c in (call_ids or set()) if c}
    scores: list[int] = []
    for m in msgs:
        try:
            post = csat_parser.parse_sprig(m)
        except Exception:  # noqa: BLE001
            continue
        if post.score is None:
            continue
        if ids and str(post.call_id) not in ids:
            continue
        scores.append(int(post.score))

    if not scores:
        return {"avg": None, "n": 0}
    return {"avg": round(sum(scores) / len(scores), 2), "n": len(scores)}
