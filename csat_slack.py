"""csat_slack.py — Accès Slack pour CSAT Insight : historique, post en thread, dédup."""
from __future__ import annotations
import requests
import config

_HISTORY_URL = "https://slack.com/api/conversations.history"
_REPLIES_URL = "https://slack.com/api/conversations.replies"
_POST_URL = "https://slack.com/api/chat.postMessage"


def _token(token: str | None) -> str:
    return token or config.SLACK_BOT_TOKEN


def fetch_new_sprig_posts(channel: str, oldest: str, sprig_user_id: str,
                          token: str | None = None, limit: int = 30) -> list[dict]:
    """Messages du bot Sprig avec ts > oldest (oldest exclu), ordre chronologique."""
    try:
        resp = requests.get(
            _HISTORY_URL,
            params={"channel": channel, "oldest": oldest, "limit": limit, "inclusive": "false"},
            headers={"Authorization": f"Bearer {_token(token)}"},
            timeout=15,
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("conversations.history: network error") from exc
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"conversations.history: {data.get('error')}")
    msgs = [
        m for m in data.get("messages", [])
        if m.get("user") == sprig_user_id and str(m.get("ts")) != str(oldest)
    ]
    msgs.sort(key=lambda m: float(m["ts"]))
    return msgs


def thread_has_bot_reply(channel: str, thread_ts: str, bot_user_id: str,
                         token: str | None = None) -> bool:
    try:
        resp = requests.get(
            _REPLIES_URL,
            params={"channel": channel, "ts": thread_ts, "limit": 50},
            headers={"Authorization": f"Bearer {_token(token)}"},
            timeout=15,
        )
    except requests.exceptions.RequestException:
        return False
    data = resp.json()
    if not data.get("ok"):
        return False
    return any(m.get("user") == bot_user_id for m in data.get("messages", []))


def post_thread(channel: str, thread_ts: str, text: str, token: str | None = None) -> bool:
    try:
        resp = requests.post(
            _POST_URL,
            json={"channel": channel, "thread_ts": thread_ts, "text": text,
                  "unfurl_links": False},
            headers={"Authorization": f"Bearer {_token(token)}", "Content-Type": "application/json"},
            timeout=15,
        )
    except requests.exceptions.RequestException:
        return False
    return bool(resp.json().get("ok"))
