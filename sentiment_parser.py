"""sentiment_parser.py — Parsing pur d'un message du bot Captain Pingouin."""
from __future__ import annotations
from dataclasses import dataclass
import html
import json
import re

_CALL_ID_RE = re.compile(r"assets\.aircall\.io/calls/(\d+)/recording")


@dataclass
class SentimentPost:
    ts: str
    call_id: str | None
    kind: str            # 'negative' | 'unanswered'
    scores: dict | None
    raw_text: str


def _flatten(msg: dict) -> str:
    parts = [msg.get("text") or ""]
    for att in msg.get("attachments") or []:
        if att.get("text"):
            parts.append(att["text"])
    for block in msg.get("blocks") or []:
        txt = block.get("text") or {}
        if isinstance(txt, dict) and txt.get("text"):
            parts.append(txt["text"])
    return html.unescape("\n".join(parts))


def _parse_scores(text: str) -> dict:
    scores: dict = {}
    json_ok = False
    for m in re.finditer(r"\{[^{}]+\}", text, re.DOTALL):
        try:
            scores = json.loads(m.group(0))
            json_ok = True
            break
        except (ValueError, TypeError):
            continue
    headline = re.search(r"Score\s*\[-1 to \+1\]\s*:\s*(-?\d+(?:\.\d+)?)", text)
    if headline and json_ok:
        scores.setdefault("headline_score", float(headline.group(1)))
    return scores


def parse_pingouin(msg: dict) -> SentimentPost:
    text = _flatten(msg)
    m = _CALL_ID_RE.search(text)
    call_id = m.group(1) if m else None
    if "call not answered" in text.lower():
        kind, scores = "unanswered", None
    else:
        kind, scores = "negative", _parse_scores(text)
    return SentimentPost(ts=str(msg.get("ts") or ""), call_id=call_id,
                         kind=kind, scores=scores, raw_text=text)
