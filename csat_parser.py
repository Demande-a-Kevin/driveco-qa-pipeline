"""csat_parser.py — Parsing pur d'un message Slack du bot Sprig en CsatPost."""
from __future__ import annotations
from dataclasses import dataclass
import html
import re

_CALL_ID_RE = re.compile(r"(\d{6,})@driveco\.com")
_QUESTION_LABEL = "répondu à vos attentes"
_INFLUENCE_LABEL = "influencé votre satisfaction"
_IMPROVE_LABEL = "améliorations"


@dataclass
class CsatPost:
    ts: str
    call_id: str | None
    score: int | None
    influence: str
    improvements: str
    raw_text: str


def _flatten_message_text(msg: dict) -> str:
    parts = [msg.get("text") or ""]
    for att in msg.get("attachments") or []:
        if att.get("text"):
            parts.append(att["text"])
    for block in msg.get("blocks") or []:
        txt = (block.get("text") or {})
        if isinstance(txt, dict) and txt.get("text"):
            parts.append(txt["text"])
    # L'API Slack renvoie le texte avec entités HTML échappées (&gt; pour les
    # blockquotes, &amp;, &lt;). On les décode pour que _quote_lines retrouve les
    # lignes « > … » du sondage Sprig (sinon le score n'est jamais extrait).
    return html.unescape("\n".join(parts))


def _quote_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            out.append(stripped[1:].strip())
    return out


def _answer_after(label: str, lines: list[str]) -> str:
    for i, line in enumerate(lines):
        if label.lower() in line.lower():
            for nxt in lines[i + 1:]:
                if nxt and not nxt.startswith("*"):
                    return nxt
            return ""
    return ""


def parse_sprig(msg: dict) -> CsatPost:
    text = _flatten_message_text(msg)
    m = _CALL_ID_RE.search(text)
    call_id = m.group(1) if m else None

    lines = _quote_lines(text)
    score = None
    raw_score = _answer_after(_QUESTION_LABEL, lines)
    sm = re.fullmatch(r"[1-5]", raw_score.strip())
    if sm:
        score = int(sm.group(0))
    else:
        # Fallback : cherche un score isolé (1-5) dans n'importe quelle ligne de réponse
        for line in lines:
            if not line.startswith("*") and re.fullmatch(r"[1-5]", line.strip()):
                score = int(line.strip())
                break

    return CsatPost(
        ts=str(msg.get("ts") or ""),
        call_id=call_id,
        score=score,
        influence=_answer_after(_INFLUENCE_LABEL, lines),
        improvements=_answer_after(_IMPROVE_LABEL, lines),
        raw_text=text,
    )
