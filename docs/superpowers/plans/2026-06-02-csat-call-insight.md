# CSAT Call Insight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poster automatiquement, en thread sous chaque réponse CSAT Sprig du canal `#sprig-responses-csat-care`, le lien du transcript Aircall et une analyse Gemma de ≤ 55 mots tranchant si la note vient de l'agent ou de la borne/app.

**Architecture:** Un module `csat_insight` ajouté au repo `driveco-qa-pipeline`, lancé par launchd toutes les 3 min. Une passe lit l'historique Slack depuis le dernier ts traité, parse les posts Sprig, récupère le transcript via `call_fetcher.fetch_transcript`, génère un verdict JSON via Ollama/Gemma local, et répond en thread avec le bot Kev1n. État persistant dans un fichier JSON ; pas de base de données.

**Tech Stack:** Python 3.11, `requests` (API Slack/Aircall/Ollama), Ollama local (Gemma), pytest. Réutilise `config`, `call_fetcher`, `ollama_client`, `schemas` du repo.

---

## File Structure

- `config.py` (modify) — 3 vars de config CSAT.
- `ollama_client.py` (modify) — wrapper public `generate_json()` réutilisable.
- `csat_parser.py` (create) — parsing pur d'un message Slack Sprig → `CsatPost`.
- `csat_prompting.py` (create) — prompt Gemma + parsing sortie → `Insight`.
- `csat_slack.py` (create) — I/O Slack : historique, post en thread, détection réponse bot.
- `csat_state.py` (create) — load/save de `.csat_insight_state.json`.
- `csat_insight.py` (create) — orchestration `run_once()` + entrée CLI `__main__`.
- `tests/test_csat_parser.py`, `tests/test_csat_prompting.py`, `tests/test_csat_slack.py`, `tests/test_csat_state.py`, `tests/test_csat_insight.py` (create).
- `setup_launchd.sh` / RUNBOOK / README (modify) — ordonnancement + doc.

Constantes partagées (définies dans `csat_insight.py`, importées par les autres) :
- `SPRIG_USER_ID = "U0798UDP7U0"`
- `KEV1N_BOT_USER_ID` ← `config.SLACK_BOT_USER_ID`

---

## Task 1: Config CSAT

**Files:**
- Modify: `config.py` (section Slack, après `SLACK_VOC_ALERTS_CHANNEL_ID`)

- [ ] **Step 1: Ajouter les variables de config**

Dans `config.py`, juste après la ligne `SLACK_VOC_ALERTS_CHANNEL_ID = ...` :

```python
# ── CSAT Call Insight ─────────────────────────────────────────────────────────
SLACK_CSAT_CHANNEL_ID = os.getenv("SLACK_CSAT_CHANNEL_ID", "C0B724V5X4L")
SLACK_BOT_USER_ID     = os.getenv("SLACK_BOT_USER_ID", "U0AMEHDCDV5")  # bot Kev1n
DISABLE_CSAT_INSIGHT  = os.getenv("DISABLE_CSAT_INSIGHT", "false").strip().lower() in {"1", "true", "yes", "on"}
```

- [ ] **Step 2: Vérifier l'import**

Run: `python -c "import config; print(config.SLACK_CSAT_CHANNEL_ID, config.SLACK_BOT_USER_ID, config.DISABLE_CSAT_INSIGHT)"`
Expected: `C0B724V5X4L U0AMEHDCDV5 False`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat(csat): config canal CSAT + bot user id + flag"
```

---

## Task 2: Parsing des posts Sprig (`csat_parser.py`)

**Files:**
- Create: `csat_parser.py`
- Test: `tests/test_csat_parser.py`

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_csat_parser.py
from csat_parser import parse_sprig, CsatPost

# Message réel observé (texte API mrkdwn, blockquotes en lignes ">")
MSG_WITH_ID = {
    "ts": "1780404011.283339",
    "user": "U0798UDP7U0",
    "text": (
        "<https://app.sprig.com/x/surveys/abc|*CSAT Customer Care - New Version*> "
        "received a new response from <mailto:3825857378@driveco.com|3825857378@driveco.com>.\n"
        "> *Dans quelle mesure notre assistance a-t-elle répondu à vos attentes ?*\n"
        "> 3\n"
        "> \n"
        "> *Qu'est ce qui a le plus influencé votre satisfaction lors de cet appel ?*\n"
        "> L'amabilité et l'écoute de l'agent\n"
        "> \n"
        "> *Quelles améliorations suggéreriez-vous ?*\n"
        "> La borne n°4 est HS et le QR code manque.\n"
    ),
}

MSG_NO_ID = {
    "ts": "1780356924.718089",
    "user": "U0798UDP7U0",
    "text": (
        "<https://app.sprig.com/x/surveys/abc|*CSAT Customer Care - New Version*> "
        "received a new response.\n"
        "> *Dans quelle mesure notre assistance a-t-elle répondu à vos attentes ?*\n"
        "> 1\n"
    ),
}


def test_parse_extracts_call_id_and_score():
    post = parse_sprig(MSG_WITH_ID)
    assert isinstance(post, CsatPost)
    assert post.ts == "1780404011.283339"
    assert post.call_id == "3825857378"
    assert post.score == 3
    assert "écoute de l'agent" in post.influence
    assert "QR code" in post.improvements


def test_parse_without_call_id_returns_none_call_id():
    post = parse_sprig(MSG_NO_ID)
    assert post.call_id is None
    assert post.score == 1


def test_parse_flattens_attachments_text():
    msg = {
        "ts": "1.1",
        "user": "U0798UDP7U0",
        "text": "received a new response from <mailto:123456@driveco.com|123456@driveco.com>.",
        "attachments": [{"text": "> *Dans quelle mesure...*\n> 5"}],
    }
    post = parse_sprig(msg)
    assert post.call_id == "123456"
    assert post.score == 5


def test_parse_missing_score_is_none():
    msg = {"ts": "1.1", "user": "U0798UDP7U0",
           "text": "received a new response from <mailto:999999@driveco.com|x>."}
    post = parse_sprig(msg)
    assert post.call_id == "999999"
    assert post.score is None
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_csat_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'csat_parser'`

- [ ] **Step 3: Implémenter `csat_parser.py`**

```python
"""csat_parser.py — Parsing pur d'un message Slack du bot Sprig en CsatPost."""
from __future__ import annotations
from dataclasses import dataclass
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
    return "\n".join(parts)


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
    sm = re.search(r"[1-5]", raw_score)
    if sm:
        score = int(sm.group(0))

    return CsatPost(
        ts=str(msg.get("ts") or ""),
        call_id=call_id,
        score=score,
        influence=_answer_after(_INFLUENCE_LABEL, lines),
        improvements=_answer_after(_IMPROVE_LABEL, lines),
        raw_text=text,
    )
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/test_csat_parser.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add csat_parser.py tests/test_csat_parser.py
git commit -m "feat(csat): parsing des posts Sprig (call_id, score, contexte)"
```

---

## Task 3: Génération du verdict Gemma (`csat_prompting.py` + wrapper Ollama)

**Files:**
- Modify: `ollama_client.py` (ajout fonction publique `generate_json`)
- Create: `csat_prompting.py`
- Test: `tests/test_csat_prompting.py`

- [ ] **Step 1: Ajouter le wrapper public dans `ollama_client.py`**

À la fin de `ollama_client.py`, ajouter :

```python
def generate_json(prompt: str, max_tokens: int = 300, timeout: int | None = None) -> dict:
    """One-shot JSON local (Gemma). Réutilisé par csat_prompting."""
    raw = _generate(config.OLLAMA_MODEL_ANALYSIS, prompt, max_tokens=max_tokens,
                    timeout=timeout, json_mode=True)
    return _parse_json(raw)
```

- [ ] **Step 2: Écrire les tests qui échouent**

```python
# tests/test_csat_prompting.py
import csat_prompting
from csat_prompting import build_prompt, analyze, Insight


def test_build_prompt_contains_constraints_and_transcript():
    p = build_prompt("Agent: bonjour\nClient: ma borne est HS", score=2,
                     influence="agent sympa", improvements="borne HS")
    assert "55 mots" in p
    assert "borne est HS" in p
    assert "Agent/Assistance" in p and "Borne/App" in p


def test_analyze_parses_model_json(monkeypatch):
    monkeypatch.setattr(
        csat_prompting.ollama_client, "generate_json",
        lambda *a, **k: {"verdict": "Borne/App", "sentiment": "mitigé",
                         "synthese": "Agent à l'écoute mais borne HS."},
    )
    ins = analyze("transcript", score=3, influence="", improvements="")
    assert isinstance(ins, Insight)
    assert ins.verdict == "Borne/App"
    assert ins.sentiment == "mitigé"
    assert "borne HS" in ins.synthese.lower()


def test_analyze_normalizes_unknown_verdict(monkeypatch):
    monkeypatch.setattr(
        csat_prompting.ollama_client, "generate_json",
        lambda *a, **k: {"verdict": "n'importe quoi", "sentiment": "x", "synthese": "..."},
    )
    ins = analyze("t", score=1, influence="", improvements="")
    assert ins.verdict == "Autre"


def test_analyze_truncates_to_55_words(monkeypatch):
    long = " ".join(["mot"] * 100)
    monkeypatch.setattr(
        csat_prompting.ollama_client, "generate_json",
        lambda *a, **k: {"verdict": "Agent/Assistance", "sentiment": "négatif", "synthese": long},
    )
    ins = analyze("t", score=1, influence="", improvements="")
    assert len(ins.synthese.split()) <= 55
```

- [ ] **Step 3: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_csat_prompting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'csat_prompting'`

- [ ] **Step 4: Implémenter `csat_prompting.py`**

```python
"""csat_prompting.py — Prompt Gemma contraint + parsing du verdict CSAT."""
from __future__ import annotations
from dataclasses import dataclass
import ollama_client

VERDICTS = {"Agent/Assistance", "Borne/App", "Mixte", "Autre"}
SENTIMENTS = {"positif", "négatif", "mitigé"}


@dataclass
class Insight:
    verdict: str
    sentiment: str
    synthese: str


def build_prompt(transcript: str, score: int | None, influence: str, improvements: str) -> str:
    score_txt = f"{score}/5" if score is not None else "inconnue"
    return f"""Tu analyses un appel d'assistance Driveco (recharge de véhicules électriques).
Le client a donné une note CSAT de {score_txt}.
Réponses du client au sondage — influence: "{influence}" ; améliorations: "{improvements}".

Transcript de l'appel :
\"\"\"
{transcript}
\"\"\"

Explique en UNE seule fois pourquoi cette note, et de quel côté vient le motif dominant.
Réponds STRICTEMENT en JSON : {{"verdict": "...", "sentiment": "...", "synthese": "..."}}
- "verdict" parmi exactement : "Agent/Assistance", "Borne/App", "Mixte", "Autre".
  Tranche un côté dominant ; n'utilise "Mixte" que si les deux pèsent vraiment à parts égales.
- "sentiment" parmi exactement : "positif", "négatif", "mitigé".
- "synthese" : 55 mots MAXIMUM, une seule explication, en français.
  INTERDIT : liste à puces, note sur 10, recommandation, plan d'action, conseils.
  Si le transcript est trop dégradé pour conclure, dis-le en une phrase sans inventer."""


def _normalize_verdict(value: str) -> str:
    v = str(value or "").strip()
    return v if v in VERDICTS else "Autre"


def _normalize_sentiment(value: str) -> str:
    v = str(value or "").strip().lower()
    return v if v in SENTIMENTS else "mitigé"


def _truncate_words(text: str, max_words: int = 55) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return str(text or "").strip()
    return " ".join(words[:max_words]).rstrip(" .,;") + "…"


def analyze(transcript: str, score: int | None, influence: str, improvements: str) -> Insight:
    data = ollama_client.generate_json(build_prompt(transcript, score, influence, improvements))
    return Insight(
        verdict=_normalize_verdict(data.get("verdict")),
        sentiment=_normalize_sentiment(data.get("sentiment")),
        synthese=_truncate_words(data.get("synthese"), 55),
    )
```

- [ ] **Step 5: Lancer les tests pour vérifier le succès**

Run: `pytest tests/test_csat_prompting.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add ollama_client.py csat_prompting.py tests/test_csat_prompting.py
git commit -m "feat(csat): prompt Gemma contraint + verdict normalisé (<=55 mots)"
```

---

## Task 4: I/O Slack (`csat_slack.py`)

**Files:**
- Create: `csat_slack.py`
- Test: `tests/test_csat_slack.py`

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_csat_slack.py
import csat_slack


class _Resp:
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


def test_fetch_new_sprig_posts_filters_author_and_oldest(monkeypatch):
    captured = {}
    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _Resp({"ok": True, "messages": [
            {"ts": "3.0", "user": "U0798UDP7U0", "text": "from <mailto:111111@driveco.com|x>"},
            {"ts": "2.0", "user": "UOTHER", "text": "bruit"},
        ]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    msgs = csat_slack.fetch_new_sprig_posts("C0B724V5X4L", oldest="1.0",
                                            sprig_user_id="U0798UDP7U0", token="xoxb-x")
    assert [m["ts"] for m in msgs] == ["3.0"]          # auteur filtré
    assert captured["params"]["oldest"] == "1.0"


def test_fetch_skips_message_equal_to_oldest(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({"ok": True, "messages": [
            {"ts": "1.0", "user": "U0798UDP7U0", "text": "from <mailto:111111@driveco.com|x>"},
        ]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    msgs = csat_slack.fetch_new_sprig_posts("C", oldest="1.0",
                                            sprig_user_id="U0798UDP7U0", token="t")
    assert msgs == []                                   # oldest inclusif -> on exclut l'égal


def test_post_thread_sends_thread_ts(monkeypatch):
    captured = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _Resp({"ok": True})
    monkeypatch.setattr(csat_slack.requests, "post", fake_post)
    ok = csat_slack.post_thread("C", "123.456", "coucou", token="t")
    assert ok is True
    assert captured["json"]["thread_ts"] == "123.456"
    assert captured["json"]["channel"] == "C"


def test_thread_has_bot_reply_true(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({"ok": True, "messages": [
            {"ts": "1.0", "user": "U0798UDP7U0"},
            {"ts": "1.1", "user": "U0AMEHDCDV5"},
        ]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    assert csat_slack.thread_has_bot_reply("C", "1.0", "U0AMEHDCDV5", token="t") is True


def test_thread_has_bot_reply_false(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({"ok": True, "messages": [{"ts": "1.0", "user": "U0798UDP7U0"}]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    assert csat_slack.thread_has_bot_reply("C", "1.0", "U0AMEHDCDV5", token="t") is False
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_csat_slack.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'csat_slack'`

- [ ] **Step 3: Implémenter `csat_slack.py`**

```python
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
    resp = requests.get(
        _HISTORY_URL,
        params={"channel": channel, "oldest": oldest, "limit": limit, "inclusive": "false"},
        headers={"Authorization": f"Bearer {_token(token)}"},
        timeout=15,
    )
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
    resp = requests.get(
        _REPLIES_URL,
        params={"channel": channel, "ts": thread_ts, "limit": 50},
        headers={"Authorization": f"Bearer {_token(token)}"},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        return False
    return any(m.get("user") == bot_user_id for m in data.get("messages", []))


def post_thread(channel: str, thread_ts: str, text: str, token: str | None = None) -> bool:
    resp = requests.post(
        _POST_URL,
        json={"channel": channel, "thread_ts": thread_ts, "text": text,
              "unfurl_links": False},
        headers={"Authorization": f"Bearer {_token(token)}", "Content-Type": "application/json"},
        timeout=15,
    )
    return bool(resp.json().get("ok"))
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/test_csat_slack.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add csat_slack.py tests/test_csat_slack.py
git commit -m "feat(csat): I/O Slack (historique Sprig, post thread, dédup réponse bot)"
```

---

## Task 5: État persistant (`csat_state.py`)

**Files:**
- Create: `csat_state.py`
- Test: `tests/test_csat_state.py`

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_csat_state.py
import csat_state


def test_load_missing_returns_default(tmp_path):
    st = csat_state.load_state(tmp_path / "x.json")
    assert st == {"last_ts": "0", "pending": []}


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    csat_state.save_state(p, {"last_ts": "123.45", "pending": [{"ts": "1.0"}]})
    st = csat_state.load_state(p)
    assert st["last_ts"] == "123.45"
    assert st["pending"] == [{"ts": "1.0"}]


def test_load_corrupt_returns_default(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert csat_state.load_state(p) == {"last_ts": "0", "pending": []}
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_csat_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'csat_state'`

- [ ] **Step 3: Implémenter `csat_state.py`**

```python
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
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/test_csat_state.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add csat_state.py tests/test_csat_state.py
git commit -m "feat(csat): état persistant JSON (last_ts + pending)"
```

---

## Task 6: Orchestration (`csat_insight.py`)

**Files:**
- Create: `csat_insight.py`
- Test: `tests/test_csat_insight.py`

Comportement de `run_once(now_epoch)` :
1. Si `config.DISABLE_CSAT_INSIGHT` → retour immédiat.
2. Charge l'état. Si `last_ts == "0"` → baseline : `last_ts = str(now_epoch)`, save, **retour** (go-forward, pas de backfill au premier run).
3. Récupère les nouveaux posts Sprig (`fetch_new_sprig_posts`), les ajoute aux `pending` reconstruits en `CsatPost`.
4. Pour chaque post à traiter (nouveaux + pending), via `_process_post` :
   - pas de call_id → skip (rien posté).
   - transcript `fetch_transcript` vide/None → reste pending (sauf budget dépassé → fallback lien-seul).
   - déjà répondu en thread → skip.
   - sinon `analyze` + `post_thread`.
5. `last_ts = max(last_ts, plus grand ts vu)` ; reconstruit `pending` ; save.

Budget pending : `attempts >= 20` OU `now - first_seen > 3600`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_csat_insight.py
import csat_insight


def _msg(ts, call_id="3825857378", score_line="> 3"):
    mail = f"from <mailto:{call_id}@driveco.com|x>" if call_id else "received a new response."
    return {"ts": ts, "user": "U0798UDP7U0",
            "text": f"new response {mail}\n> *...répondu à vos attentes ?*\n{score_line}"}


def _wire(monkeypatch, *, history=None, transcript="Agent: bonjour", has_reply=False):
    posted = []
    monkeypatch.setattr(csat_insight, "fetch_new_sprig_posts",
                        lambda *a, **k: list(history or []))
    monkeypatch.setattr(csat_insight, "fetch_transcript", lambda call_id: transcript)
    monkeypatch.setattr(csat_insight, "thread_has_bot_reply", lambda *a, **k: has_reply)
    monkeypatch.setattr(csat_insight, "analyze",
                        lambda *a, **k: csat_insight.Insight("Borne/App", "mitigé", "Borne HS."))
    def fake_post(channel, thread_ts, text, token=None):
        posted.append((thread_ts, text)); return True
    monkeypatch.setattr(csat_insight, "post_thread", fake_post)
    monkeypatch.setattr(csat_insight.config, "DISABLE_CSAT_INSIGHT", False)
    return posted


def test_first_run_sets_baseline_and_posts_nothing(monkeypatch, tmp_path):
    posted = _wire(monkeypatch, history=[_msg("10.0")])
    state_file = tmp_path / "s.json"
    csat_insight.run_once(now_epoch=999, state_path=state_file)
    assert posted == []
    import csat_state
    assert csat_state.load_state(state_file)["last_ts"] == "999"


def test_posts_thread_for_new_csat(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, history=[_msg("10.0", call_id="3825857378")])
    csat_insight.run_once(now_epoch=1000, state_path=state_file)
    assert len(posted) == 1
    thread_ts, text = posted[0]
    assert thread_ts == "10.0"
    assert "Borne/App" in text and "3825857378" in text
    assert csat_state.load_state(state_file)["last_ts"] == "10.0"


def test_no_call_id_skips_without_posting(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, history=[_msg("10.0", call_id=None)])
    csat_insight.run_once(now_epoch=1000, state_path=state_file)
    assert posted == []
    assert csat_state.load_state(state_file)["last_ts"] == "10.0"


def test_transcript_not_ready_goes_pending(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, history=[_msg("10.0")], transcript="")
    csat_insight.run_once(now_epoch=1000, state_path=state_file)
    assert posted == []
    pending = csat_state.load_state(state_file)["pending"]
    assert len(pending) == 1 and pending[0]["call_id"] == "3825857378"


def test_pending_budget_exhausted_posts_link_only(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "10.0", "pending": [
        {"ts": "9.0", "call_id": "3825857378", "score": 3, "influence": "", "improvements": "",
         "first_seen": 0, "attempts": 20}]})
    posted = _wire(monkeypatch, history=[], transcript="")
    csat_insight.run_once(now_epoch=10000, state_path=state_file)
    assert len(posted) == 1
    assert "transcript" in posted[0][1].lower()
    assert csat_state.load_state(state_file)["pending"] == []


def test_already_replied_skips(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, history=[_msg("10.0")], has_reply=True)
    csat_insight.run_once(now_epoch=1000, state_path=state_file)
    assert posted == []
```

- [ ] **Step 2: Lancer les tests pour vérifier l'échec**

Run: `pytest tests/test_csat_insight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'csat_insight'`

- [ ] **Step 3: Implémenter `csat_insight.py`**

```python
"""csat_insight.py — Orchestration d'une passe CSAT Call Insight (lancé par launchd)."""
from __future__ import annotations
from pathlib import Path
import logging
import time

import config
from call_fetcher import fetch_transcript
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


def _render(insight: Insight, call_id: str, score: int | None) -> str:
    score_txt = f"{score}/5" if score is not None else "?/5"
    link = f"<{_transcript_link(call_id)}|transcript>"
    return (f"🔎 *Analyse appel* · CSAT {score_txt} · {link}\n"
            f"*Verdict : {insight.verdict}* ({insight.sentiment})\n"
            f"{insight.synthese}")


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
    insight = analyze(transcript, post.score, post.influence, post.improvements)
    post_thread(channel, post.ts, _render(insight, post.call_id, post.score))
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
        baseline = str(max(float(max_ts), float(now_epoch)))
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
```

- [ ] **Step 4: Lancer les tests pour vérifier le succès**

Run: `pytest tests/test_csat_insight.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lancer toute la nouvelle suite**

Run: `pytest tests/test_csat_parser.py tests/test_csat_prompting.py tests/test_csat_slack.py tests/test_csat_state.py tests/test_csat_insight.py -v`
Expected: PASS (22 tests)

- [ ] **Step 6: Commit**

```bash
git add csat_insight.py tests/test_csat_insight.py
git commit -m "feat(csat): orchestration run_once (baseline, pending, idempotence)"
```

---

## Task 7: Smoke test réel (dry-run) puis ordonnancement launchd

**Files:**
- Modify: `setup_launchd.sh`
- Modify: `RUNBOOK.md`, `README.md`

- [ ] **Step 1: Smoke test manuel en mode sûr**

Forcer le no-post pour vérifier la lecture Slack + Ollama sans rien publier :

Run: `DISABLE_CSAT_INSIGHT=true python csat_insight.py`
Expected: log `CSAT Insight désactivé` (aucune écriture Slack).

Puis tester la baseline (premier run réel, ne poste rien) avec un fichier d'état jetable :

Run: `python -c "import csat_insight, pathlib; csat_insight.run_once(state_path=pathlib.Path('/tmp/csat_smoke.json'))"`
Expected: log `Baseline initialisée…`, fichier `/tmp/csat_smoke.json` créé avec un `last_ts` ≈ maintenant.

> ⚠️ **Prérequis scope Slack** : si `conversations.history` renvoie `missing_scope`, ajouter
> le scope `channels:history` à l'app Slack du bot Kev1n (canal public), réinstaller l'app,
> puis relancer. Le post (`chat:write`) est déjà autorisé.

- [ ] **Step 2: Ajouter le job launchd**

Dans `setup_launchd.sh`, ajouter un agent (calqué sur les jobs existants) :

```bash
# CSAT Call Insight — toutes les 3 minutes
cat > "$HOME/Library/LaunchAgents/com.kev1n.driveco.csat-insight.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.kev1n.driveco.csat-insight</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${REPO_DIR}/csat_insight.py</string>
  </array>
  <key>WorkingDirectory</key><string>${REPO_DIR}</string>
  <key>StartInterval</key><integer>180</integer>
  <key>StandardOutPath</key><string>${LOG_DIR}/csat-insight.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/csat-insight.err.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
PLIST
launchctl unload "$HOME/Library/LaunchAgents/com.kev1n.driveco.csat-insight.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/com.kev1n.driveco.csat-insight.plist"
```

> Adapter `${PYTHON_BIN}`, `${REPO_DIR}`, `${LOG_DIR}` aux variables déjà définies dans
> `setup_launchd.sh`. S'il n'y en a pas, réutiliser la même résolution que les autres jobs
> du script.

- [ ] **Step 3: Documenter (RUNBOOK + README)**

Dans `RUNBOOK.md`, ajouter une section « CSAT Call Insight » : but, label launchd
`com.kev1n.driveco.csat-insight`, intervalle 180 s, logs `csat-insight*.log`, flag
`DISABLE_CSAT_INSIGHT`, état `.csat_insight_state.json` (supprimer le fichier ré-initialise
la baseline = go-forward), prérequis scope `channels:history`.

Dans `README.md`, ajouter une ligne dans la liste des composants : *CSAT Call Insight —
réponse en thread Slack avec transcript + verdict Gemma (agent vs borne/app)*.

- [ ] **Step 4: Commit**

```bash
git add setup_launchd.sh RUNBOOK.md README.md
git commit -m "ops(csat): job launchd 3min + doc RUNBOOK/README"
```

---

## Task 8: Documentation externe (Obsidian / Notion / mémoire)

**Files:**
- Create: note Obsidian vault Kev1n Cockpit
- Notion : page via MCP
- Mémoire : fichier projet

> Ces livrables ne sont pas du code ; pas de test automatisé. À exécuter après validation
> fonctionnelle du job en prod.

- [ ] **Step 1: Note Obsidian**

Créer `~/Documents/Obsidian/10 - Pro/Kev1n Cockpit/CSAT Call Insight (2026-06-02).md`
résumant : objectif, canal `C0B724V5X4L`, déclencheur (polling launchd 3 min), réutilisation
pipeline (`fetch_transcript` + Ollama/Gemma + bot Kev1n), format du post, cas limites,
prérequis scope Slack. Lier la spec et le plan du repo.

- [ ] **Step 2: Page Notion**

Via le connecteur Notion MCP (`notion-create-pages`), créer une page « CSAT Call Insight »
sous l'espace projet pertinent, avec le même contenu condensé que la note Obsidian.

- [ ] **Step 3: Mémoire projet**

Mettre à jour la mémoire : nouveau fichier
`/Users/kev1n/.claude/projects/-Users-kev1n-Desktop-Kev1n-IA/memory/project_csat_call_insight.md`
(type project) + ligne d'index dans `MEMORY.md`. Lier `[[project_driveco_qa_pipeline]]` et
`[[project_cockpit_setup]]`.

- [ ] **Step 4: Pousser la branche / PR**

```bash
git push -u origin feat/csat-call-insight
```

Puis ouvrir une PR (ou merger sur `main` selon préférence), et déclencher un premier run réel
pour poser la baseline.

---

## Self-Review (couverture spec)

- Détection polling launchd → Task 7. ✓
- Module dans le repo existant → toutes les tasks. ✓
- Slack-only (pas de Supabase) → aucune task DB. ✓
- Verdict tranché + libellés → `csat_prompting` (Task 3). ✓
- Toutes CSAT avec call ID, skip sans call ID → Task 6 (`test_no_call_id_skips`). ✓
- Go-forward / baseline → Task 6 (`test_first_run_sets_baseline`). ✓
- Format post ≤ 55 mots + transcript → Task 3 (`_truncate_words`) + Task 6 (`_render`). ✓
- Cas transcript pas prêt + fallback → Task 6 (`pending`, `link_only`). ✓
- Idempotence → Task 6 (`thread_has_bot_reply`). ✓
- Prérequis scope `channels:history` → Task 7. ✓
- Doc Obsidian/Notion/mémoire → Task 8. ✓
```
