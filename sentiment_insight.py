"""sentiment_insight.py — Orchestration Sentiment Call Insight (canal UCC, lancé par launchd)."""
from __future__ import annotations
from pathlib import Path
import logging
import time

import config
from call_fetcher import fetch_transcript
from csat_aircall import fetch_call_facts, format_facts_line
from csat_slack import fetch_new_posts_by_author, thread_has_bot_reply, post_thread
from sentiment_parser import parse_pingouin, SentimentPost
from sentiment_prompting import analyze, SentimentInsight
import csat_state

log = logging.getLogger("sentiment_insight")

PINGOUIN_BOT_ID = "B0B6V282D5Y"
DEFAULT_STATE_PATH = config.BASE_DIR / ".sentiment_insight_state.json"
PENDING_MAX_ATTEMPTS = 20
PENDING_MAX_AGE_S = 3600
_ASSET_BASE = "https://assets.aircall.io/calls"


def _transcript_link(call_id: str) -> str:
    return f"{_ASSET_BASE}/{call_id}/recording/info"


def _duration_txt(facts: dict | None) -> str:
    dur = (facts or {}).get("duration_s")
    if not dur:
        return ""
    return f"{int(dur) // 60}min{int(dur) % 60:02d}s"


def _render(post: SentimentPost, insight: SentimentInsight, facts: dict | None) -> str:
    link = f"<{_transcript_link(post.call_id)}|transcript>"
    scores = post.scores or {}
    final = scores.get("final_score", scores.get("headline_score"))
    head = f"🔎 *Analyse appel* · score final {final} · {link}" if (post.kind == "negative" and final is not None) \
        else f"🔎 *Analyse appel* · {link}"
    lines = [head]
    if post.kind == "unanswered" and (facts or {}).get("answered"):
        d = _duration_txt(facts)
        lines.append(f"ℹ️ marqué « non répondu » mais décroché{f' {d}' if d else ''}")
    else:
        fl = format_facts_line(facts)
        if fl:
            lines.append(fl)
    if insight.verdict:
        verdict_bits = [f"*Verdict : {insight.verdict}*"]
        if insight.moment:
            verdict_bits.append(insight.moment)
        if insight.recoverable:
            verdict_bits.append(f"rattrapé: {insight.recoverable}")
        lines.append(" · ".join(verdict_bits))
    lines.append(insight.synthese)
    return "\n".join(lines)


def _render_link_only(post: SentimentPost) -> str:
    link = f"<{_transcript_link(post.call_id)}|transcript>"
    return (f"🔎 *Analyse appel* · {link}\n"
            f"_Transcript indisponible pour le moment — lien fourni, analyse non générée._")


def _post_from_dict(d: dict) -> SentimentPost:
    return SentimentPost(ts=d["ts"], call_id=d.get("call_id"), kind=d.get("kind", "negative"),
                         scores=d.get("scores"), raw_text=d.get("raw_text", ""))


def _to_pending_dict(post: SentimentPost, first_seen: int, attempts: int) -> dict:
    return {"ts": post.ts, "call_id": post.call_id, "kind": post.kind, "scores": post.scores,
            "first_seen": first_seen, "attempts": attempts}


def _process_post(post: SentimentPost, first_seen: int, attempts: int, now_epoch: int,
                  channel: str, bot_id: str) -> str:
    if not post.call_id:
        return "done"
    if thread_has_bot_reply(channel, post.ts, bot_id):
        return "done"
    transcript = fetch_transcript(post.call_id)
    if post.kind == "negative" and not transcript:
        budget_done = attempts + 1 >= PENDING_MAX_ATTEMPTS or (now_epoch - first_seen) > PENDING_MAX_AGE_S
        if budget_done:
            post_thread(channel, post.ts, _render_link_only(post))
            return "done"
        return "pending"
    facts = fetch_call_facts(post.call_id)
    insight = analyze(post.kind, transcript or "", facts, post.scores)
    post_thread(channel, post.ts, _render(post, insight, facts))
    return "done"


def run_once(now_epoch: int | None = None, state_path: Path | None = None) -> None:
    if config.DISABLE_SENTIMENT_INSIGHT:
        log.info("Sentiment Insight désactivé (DISABLE_SENTIMENT_INSIGHT)")
        return
    now_epoch = int(now_epoch if now_epoch is not None else time.time())
    state_path = Path(state_path or DEFAULT_STATE_PATH)
    channel = config.SLACK_SENTIMENT_CHANNEL_ID
    bot_id = config.SLACK_BOT_USER_ID
    cap = int(config.SENTIMENT_INSIGHT_MAX_PER_RUN)

    state = csat_state.load_state(state_path)
    last_ts = state["last_ts"]

    if last_ts == "0":
        max_ts = "0"
        try:
            for m in fetch_new_posts_by_author(channel, "0", PINGOUIN_BOT_ID):
                if float(m["ts"]) > float(max_ts):
                    max_ts = str(m["ts"])
        except Exception as exc:  # noqa: BLE001
            log.warning("baseline history KO: %s", exc)
        # pin à maintenant si l'historique est plus ancien (évite tout backfill)
        baseline = max_ts if float(max_ts) >= now_epoch else str(now_epoch)
        csat_state.save_state(state_path, {"last_ts": baseline, "pending": []})
        log.info("Baseline initialisée à %s (go-forward only)", baseline)
        return

    try:
        new_msgs = fetch_new_posts_by_author(channel, last_ts, PINGOUIN_BOT_ID)
    except Exception as exc:  # noqa: BLE001
        log.warning("history KO: %s — on retentera", exc)
        new_msgs = []

    new_pending: list[dict] = []
    max_ts = last_ts

    # 1) Pending hérités (négatifs en attente de transcript)
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

    # 2) Nouveaux posts, plafonnés à `cap` ; last_ts avance jusqu'au dernier TRAITÉ
    for m in new_msgs[:cap]:
        post = parse_pingouin(m)
        try:
            status = _process_post(post, now_epoch, 0, now_epoch, channel, bot_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("post %s KO: %s", post.ts, exc)
            status = "pending"
        if status == "pending":
            new_pending.append(_to_pending_dict(post, now_epoch, 1))
        if float(post.ts) > float(max_ts):
            max_ts = post.ts

    csat_state.save_state(state_path, {"last_ts": str(max_ts), "pending": new_pending})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    run_once()
