"""csat_aircall.py — Faits factuels Aircall pour enrichir l'analyse CSAT.

Récupère, pour le call_id rattaché à une CSAT, la durée d'attente avant
décrochage et le fait que l'appel ait été décroché (et l'agent si Aircall le
renseigne). Réutilise `call_fetcher.fetch_call_details` (auth + cache).
"""
from __future__ import annotations

import call_fetcher


def fetch_call_facts(call_id: str) -> dict:
    """Retourne les faits Aircall d'un appel, ou {} si indisponible.

    Clés : answered (bool), time_to_answer_s (int|None), duration_s (int|None),
    direction (str|None), agent_name (str|None).
    """
    try:
        call = call_fetcher.fetch_call_details(call_id)
    except Exception:  # noqa: BLE001 — l'enrichissement ne doit jamais bloquer le post
        call = None
    if not isinstance(call, dict) or not call:
        return {}

    started = call.get("started_at")
    answered = call.get("answered_at")
    time_to_answer_s = None
    if started and answered:
        time_to_answer_s = max(0, int(answered) - int(started))

    user = call.get("user")
    agent_name = user.get("name") if isinstance(user, dict) else None

    return {
        "answered": bool(answered),
        "time_to_answer_s": time_to_answer_s,
        "duration_s": call.get("duration"),
        "direction": call.get("direction"),
        "agent_name": agent_name,
    }


def format_facts_line(facts: dict | None) -> str:
    """Ligne mrkdwn des faits Aircall (partagée CSAT/Sentiment)."""
    if not facts:
        return ""
    bits = []
    if facts.get("answered"):
        tta = facts.get("time_to_answer_s")
        bits.append(f"décroché par un agent{f' après {tta}s' if tta is not None else ''}")
    else:
        bits.append("non décroché")
    dur = facts.get("duration_s")
    if dur:
        bits.append(f"durée {int(dur) // 60}min{int(dur) % 60:02d}s")
    if facts.get("agent_name"):
        bits.append(str(facts["agent_name"]))
    return "⏱ " + " · ".join(bits)
