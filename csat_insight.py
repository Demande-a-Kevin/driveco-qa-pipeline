"""csat_insight.py — Orchestration d'une passe CSAT Call Insight (lancé par launchd)."""
from __future__ import annotations
from pathlib import Path
import logging
import time

import config
from call_fetcher import fetch_transcript
from csat_aircall import fetch_call_facts
from csat_parser import parse_sprig, CsatPost
from csat_prompting import analyze, Insight
from csat_slack import fetch_new_sprig_posts, thread_has_bot_reply, post_thread
import csat_state

log = logging.getLogger("csat_insight")

SPRIG_USER_ID = "U0798UDP7U0"
DEFAULT_STATE_PATH = config.BASE_DIR / ".csat_insight_state.json"
PENDING_MAX_ATTEMPTS = 20
PENDING_MAX_AGE_S = 3600
_ASSET_BASE = "https://assets.aircall.io/calls"


def _transcript_link(call_id: str) -> str:
    return f"{_ASSET_BASE}/{call_id}/recording/info"


def _facts_line(facts: dict | None) -> str:
    """Ligne de faits Aircall (attente avant décrochage, décroché ou non)."""
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


def _render(insight: Insight, call_id: str, score: int | None, facts: dict | None = None) -> str:
    score_txt = f"{score}/5" if score is not None else "?/5"
    link = f"<{_transcript_link(call_id)}|transcript>"
    lines = [f"🔎 *Analyse appel* · CSAT {score_txt} · {link}"]
    facts_line = _facts_line(facts)
    if facts_line:
        lines.append(facts_line)
    lines.append(f"*Verdict : {insight.verdict}* ({insight.sentiment})")
    lines.append(insight.synthese)
    return "\n".join(lines)


def _render_link_only(call_id: str, score: int | None) -> str:
    score_txt = f"{score}/5" if score is not None else "?/5"
    link = f"<{_transcript_link(call_id)}|transcript>"
    return (f"🔎 *Analyse appel* · CSAT {score_txt} · {link}\n"
            f"_Transcript indisponible pour le moment — lien fourni, analyse non générée._")


def _post_from_dict(d: dict) -> CsatPost:
    return CsatPost(ts=d["ts"], call_id=d.get("call_id"), score=d.get("score"),
                    influence=d.get("influence", ""), improvements=d.get("improvements", ""),
                    raw_text=d.get("raw_text", ""))


def _to_pending_dict(post: CsatPost, first_seen: int, attempts: int) -> dict:
    return {"ts": post.ts, "call_id": post.call_id, "score": post.score,
            "influence": post.influence, "improvements": post.improvements,
            "first_seen": first_seen, "attempts": attempts}


def _process_post(post: CsatPost, first_seen: int, attempts: int, now_epoch: int,
                  channel: str, bot_id: str) -> str:
    """Retourne 'done' (traité/posté/skip) ou 'pending' (à retenter)."""
    if not post.call_id:
        return "done"
    if thread_has_bot_reply(channel, post.ts, bot_id):
        return "done"
    transcript = fetch_transcript(post.call_id)
    if not transcript:
        budget_done = attempts + 1 >= PENDING_MAX_ATTEMPTS or (now_epoch - first_seen) > PENDING_MAX_AGE_S
        if budget_done:
            post_thread(channel, post.ts, _render_link_only(post.call_id, post.score))
            return "done"
        return "pending"
    facts = fetch_call_facts(post.call_id)
    insight = analyze(transcript, post.score, post.influence, post.improvements, facts)
    post_thread(channel, post.ts, _render(insight, post.call_id, post.score, facts))
    return "done"


def run_once(now_epoch: int | None = None, state_path: Path | None = None) -> None:
    if config.DISABLE_CSAT_INSIGHT:
        log.info("CSAT Insight désactivé (DISABLE_CSAT_INSIGHT)")
        return
    now_epoch = int(now_epoch if now_epoch is not None else time.time())
    state_path = Path(state_path or DEFAULT_STATE_PATH)
    channel = config.SLACK_CSAT_CHANNEL_ID
    bot_id = config.SLACK_BOT_USER_ID

    state = csat_state.load_state(state_path)
    last_ts = state["last_ts"]

    if last_ts == "0":
        # Premier run : baseline, pas de backfill.
        max_ts = "0"
        try:
            msgs = fetch_new_sprig_posts(channel, "0", SPRIG_USER_ID)
            for m in msgs:
                if float(m["ts"]) > float(max_ts):
                    max_ts = str(m["ts"])
        except Exception as exc:  # noqa: BLE001
            log.warning("baseline history KO: %s", exc)
        if float(max_ts) >= now_epoch:
            baseline = str(max_ts)
        else:
            baseline = str(now_epoch)
        csat_state.save_state(state_path, {"last_ts": baseline, "pending": []})
        log.info("Baseline initialisée à %s (go-forward only)", baseline)
        return

    # Nouveaux messages
    try:
        new_msgs = fetch_new_sprig_posts(channel, last_ts, SPRIG_USER_ID)
    except Exception as exc:  # noqa: BLE001
        log.warning("history KO: %s — on retentera", exc)
        new_msgs = []

    new_pending: list[dict] = []
    max_ts = last_ts

    # 1) Pending hérités
    for d in state["pending"]:
        post = _post_from_dict(d)
        try:
            status = _process_post(post, d.get("first_seen", now_epoch), d.get("attempts", 0),
                                   now_epoch, channel, bot_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("pending %s KO: %s", post.ts, exc)
            status = "pending"
        if status == "pending":
            new_pending.append(_to_pending_dict(post, d.get("first_seen", now_epoch),
                                                d.get("attempts", 0) + 1))

    # 2) Nouveaux posts
    for m in new_msgs:
        post = parse_sprig(m)
        if float(post.ts) > float(max_ts):
            max_ts = post.ts
        try:
            status = _process_post(post, now_epoch, 0, now_epoch, channel, bot_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("post %s KO: %s", post.ts, exc)
            status = "pending"
        if status == "pending":
            new_pending.append(_to_pending_dict(post, now_epoch, 1))

    csat_state.save_state(state_path, {"last_ts": str(max_ts), "pending": new_pending})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    run_once()
