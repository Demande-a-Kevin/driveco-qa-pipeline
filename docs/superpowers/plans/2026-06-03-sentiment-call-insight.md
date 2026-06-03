# Sentiment Call Insight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Répondre automatiquement en thread, sous chaque post du bot Captain Pingouin du canal `#ucc-sentiment-analysis-ai`, avec une analyse Gemma de 4-5 lignes (verdict + moment + rattrapable pour les négatifs ; analyse adaptative pour les « non répondus »).

**Architecture:** Module parallèle `sentiment_insight` dans `driveco-qa-pipeline`, lancé par launchd (180s), calqué sur `csat_insight`. Réutilise `call_fetcher.fetch_transcript`, `csat_aircall.fetch_call_facts`, `csat_state`, et une lecture Slack généralisée (filtre auteur par `user` OU `bot_id`). Go-forward only, cap anti-saturation Ollama par passe.

**Tech Stack:** Python 3.11, `requests`, Ollama/Gemma local, pytest. Réutilise les briques CSAT existantes.

---

## File Structure

- `config.py` (modify) — 3 vars sentiment.
- `csat_slack.py` (modify) — `fetch_new_posts_by_author` (filtre `user` OU `bot_id`) ; `fetch_new_sprig_posts` délègue.
- `csat_aircall.py` (modify) — `format_facts_line(facts)` (formatteur partagé, additif).
- `sentiment_parser.py` (create) — `parse_pingouin(msg) -> SentimentPost`.
- `sentiment_prompting.py` (create) — `analyze(kind, transcript, facts, scores) -> SentimentInsight` + `build_prompt`.
- `sentiment_insight.py` (create) — orchestration `run_once` + rendu + CLI.
- `tests/test_sentiment_parser.py`, `tests/test_sentiment_prompting.py`, `tests/test_sentiment_insight.py`, `tests/test_csat_slack.py` (modify) (create/modify).
- `setup_launchd.sh`, `RUNBOOK.md`, `README.md` (modify).

Constante partagée : `PINGOUIN_BOT_ID = "B0B6V282D5Y"` (dans `sentiment_insight.py`).

---

## Task 1: Config sentiment

**Files:**
- Modify: `config.py` (après le bloc CSAT Call Insight)

- [ ] **Step 1: Ajouter les variables**

Dans `config.py`, juste après la ligne `DISABLE_CSAT_INSIGHT = ...` :

```python
# ── Sentiment Call Insight (canal UCC sentiment) ──────────────────────────────
SLACK_SENTIMENT_CHANNEL_ID = os.getenv("SLACK_SENTIMENT_CHANNEL_ID", "C0B7PA2EZQ8")
DISABLE_SENTIMENT_INSIGHT  = os.getenv("DISABLE_SENTIMENT_INSIGHT", "false").strip().lower() in {"1", "true", "yes", "on"}
SENTIMENT_INSIGHT_MAX_PER_RUN = int(os.getenv("SENTIMENT_INSIGHT_MAX_PER_RUN", "5"))
```

- [ ] **Step 2: Vérifier l'import**

Run: `python -c "import config; print(config.SLACK_SENTIMENT_CHANNEL_ID, config.DISABLE_SENTIMENT_INSIGHT, config.SENTIMENT_INSIGHT_MAX_PER_RUN)"`
Expected: `C0B7PA2EZQ8 False 5`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat(sentiment): config canal UCC + flag + cap par passe"
```

---

## Task 2: Lecture Slack généralisée (filtre user OU bot_id)

**Files:**
- Modify: `csat_slack.py`
- Modify: `tests/test_csat_slack.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `tests/test_csat_slack.py` :

```python
def test_fetch_by_author_matches_bot_id(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({"ok": True, "messages": [
            {"ts": "3.0", "bot_id": "B0B6V282D5Y", "text": "x"},
            {"ts": "2.5", "user": "UOTHER", "text": "bruit"},
        ]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    msgs = csat_slack.fetch_new_posts_by_author("C", oldest="1.0",
                                                author_id="B0B6V282D5Y", token="t")
    assert [m["ts"] for m in msgs] == ["3.0"]


def test_fetch_by_author_matches_user(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({"ok": True, "messages": [
            {"ts": "3.0", "user": "U0798UDP7U0", "text": "x"}]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    msgs = csat_slack.fetch_new_posts_by_author("C", oldest="1.0",
                                                author_id="U0798UDP7U0", token="t")
    assert [m["ts"] for m in msgs] == ["3.0"]
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python -m pytest tests/test_csat_slack.py -k by_author -v`
Expected: FAIL — `AttributeError: module 'csat_slack' has no attribute 'fetch_new_posts_by_author'`

- [ ] **Step 3: Implémenter dans `csat_slack.py`**

Remplacer la fonction `fetch_new_sprig_posts` par la version généralisée + un alias :

```python
def fetch_new_posts_by_author(channel: str, oldest: str, author_id: str,
                              token: str | None = None, limit: int = 100) -> list[dict]:
    """Messages d'un auteur (user OU bot_id) avec ts > oldest, ordre chronologique."""
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
        if (m.get("user") == author_id or m.get("bot_id") == author_id)
        and str(m.get("ts")) != str(oldest)
    ]
    msgs.sort(key=lambda m: float(m["ts"]))
    return msgs


def fetch_new_sprig_posts(channel: str, oldest: str, sprig_user_id: str,
                          token: str | None = None, limit: int = 30) -> list[dict]:
    """Compat CSAT : délègue au filtre générique par auteur."""
    return fetch_new_posts_by_author(channel, oldest, sprig_user_id, token=token, limit=limit)
```

- [ ] **Step 4: Lancer toute la suite csat_slack**

Run: `python -m pytest tests/test_csat_slack.py -v`
Expected: PASS (tous, anciens + 2 nouveaux)

- [ ] **Step 5: Commit**

```bash
git add csat_slack.py tests/test_csat_slack.py
git commit -m "feat(sentiment): lecture Slack filtrée par user OU bot_id (réutilisable)"
```

---

## Task 3: Formatteur de faits partagé

**Files:**
- Modify: `csat_aircall.py`
- Modify: `tests/test_csat_aircall.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `tests/test_csat_aircall.py` :

```python
def test_format_facts_line_answered():
    line = csat_aircall.format_facts_line(
        {"answered": True, "time_to_answer_s": 38, "duration_s": 288})
    assert line.startswith("⏱")
    assert "décroché" in line and "38s" in line and "4min48s" in line


def test_format_facts_line_empty():
    assert csat_aircall.format_facts_line({}) == ""
    assert csat_aircall.format_facts_line(None) == ""
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python -m pytest tests/test_csat_aircall.py -k format_facts -v`
Expected: FAIL — `AttributeError: module 'csat_aircall' has no attribute 'format_facts_line'`

- [ ] **Step 3: Implémenter dans `csat_aircall.py`**

Ajouter à la fin :

```python
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
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python -m pytest tests/test_csat_aircall.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add csat_aircall.py tests/test_csat_aircall.py
git commit -m "feat(sentiment): format_facts_line partagé dans csat_aircall"
```

---

## Task 4: Parsing des posts Pingouin (`sentiment_parser.py`)

**Files:**
- Create: `sentiment_parser.py`
- Test: `tests/test_sentiment_parser.py`

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_sentiment_parser.py
from sentiment_parser import parse_pingouin, SentimentPost

NEG = {"ts": "1.0", "bot_id": "B0B6V282D5Y", "text": (
    "Access link : <https://assets.aircall.io/calls/3827871596/recording/info>\n"
    "Score [-1 to +1]  :  -0.6  (confidance : 95%)\n--------------\n"
    '{\n  "overall_score": -0.88,\n  "initial_score": -0.45,\n'
    '  "peak_negative_score": -1,\n  "final_score": -0.6,\n'
    '  "label": "negative_unresolved",\n  "confidence": 0.95\n}')}

UNANS = {"ts": "2.0", "bot_id": "B0B6V282D5Y", "text": (
    "[Call not answered]\n"
    "Access link : <https://assets.aircall.io/calls/3827393590/recording/info>")}


def test_parse_negative_extracts_callid_and_scores():
    p = parse_pingouin(NEG)
    assert isinstance(p, SentimentPost)
    assert p.call_id == "3827871596"
    assert p.kind == "negative"
    assert p.scores["final_score"] == -0.6
    assert p.scores["peak_negative_score"] == -1
    assert p.scores["label"] == "negative_unresolved"


def test_parse_unanswered():
    p = parse_pingouin(UNANS)
    assert p.call_id == "3827393590"
    assert p.kind == "unanswered"
    assert p.scores is None


def test_parse_handles_html_escaped_link():
    msg = {"ts": "3.0", "bot_id": "B0B6V282D5Y",
           "text": "Access link : &lt;https://assets.aircall.io/calls/999999/recording/info&gt;\n"
                   "Score [-1 to +1] : -0.7 (confidance : 80%)\n{ \"final_score\": -0.7 }"}
    p = parse_pingouin(msg)
    assert p.call_id == "999999"
    assert p.kind == "negative"
    assert p.scores["final_score"] == -0.7


def test_parse_negative_with_broken_json_keeps_callid():
    msg = {"ts": "4.0", "bot_id": "B0B6V282D5Y",
           "text": "Access link : <https://assets.aircall.io/calls/111111/recording/info>\n"
                   "Score [-1 to +1] : -0.9 (confidance : 90%)\n{ pas du json"}
    p = parse_pingouin(msg)
    assert p.call_id == "111111"
    assert p.kind == "negative"
    assert p.scores == {} or p.scores is None
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python -m pytest tests/test_sentiment_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sentiment_parser'`

- [ ] **Step 3: Implémenter `sentiment_parser.py`**

```python
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
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            scores = json.loads(m.group(0))
        except (ValueError, TypeError):
            scores = {}
    headline = re.search(r"Score\s*\[-1 to \+1\]\s*:\s*(-?\d+(?:\.\d+)?)", text)
    if headline:
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
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python -m pytest tests/test_sentiment_parser.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add sentiment_parser.py tests/test_sentiment_parser.py
git commit -m "feat(sentiment): parsing des posts Pingouin (call_id, kind, trajectoire JSON)"
```

---

## Task 5: Analyse Gemma adaptative (`sentiment_prompting.py`)

**Files:**
- Create: `sentiment_prompting.py`
- Test: `tests/test_sentiment_prompting.py`

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_sentiment_prompting.py
import sentiment_prompting
from sentiment_prompting import analyze, build_prompt, SentimentInsight


def test_build_prompt_negative_includes_trajectory():
    p = build_prompt("negative", "Agent: bonjour\nClient: ça marche pas",
                     {"answered": True, "time_to_answer_s": 54, "duration_s": 838},
                     {"initial_score": -0.45, "peak_negative_score": -1, "final_score": -0.6})
    assert "final" in p.lower()
    assert "Borne/App" in p and "rattrap" in p.lower()
    assert "ça marche pas" in p


def test_analyze_negative_normalizes(monkeypatch):
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json",
                        lambda *a, **k: {"verdict": "Borne/App", "moment": "échec paiement ~8min",
                                         "recoverable": "non", "synthese": "Borne HS, paiement KO."})
    ins = analyze("negative", "transcript", {}, {"final_score": -0.6})
    assert isinstance(ins, SentimentInsight)
    assert ins.verdict == "Borne/App"
    assert ins.recoverable == "non"
    assert "paiement" in ins.moment


def test_analyze_negative_unknown_verdict_recoverable(monkeypatch):
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json",
                        lambda *a, **k: {"verdict": "xxx", "moment": "m", "recoverable": "yyy",
                                         "synthese": "s"})
    ins = analyze("negative", "t", {}, None)
    assert ins.verdict == "Autre"
    assert ins.recoverable == ""


def test_analyze_unanswered_without_transcript_is_deterministic(monkeypatch):
    called = {"llm": False}
    def boom(*a, **k):
        called["llm"] = True
        return {}
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json", boom)
    ins = analyze("unanswered", "", {"answered": False, "direction": "inbound"}, None)
    assert called["llm"] is False          # aucun appel LLM
    assert ins.verdict == ""               # pas de verdict
    assert ins.synthese                     # une explication factuelle existe


def test_analyze_synthese_truncated(monkeypatch):
    long = " ".join(["mot"] * 100)
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json",
                        lambda *a, **k: {"verdict": "Agent/Assistance", "moment": "m",
                                         "recoverable": "oui", "synthese": long})
    ins = analyze("negative", "t", {}, None)
    assert len(ins.synthese.split()) <= 50
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python -m pytest tests/test_sentiment_prompting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sentiment_prompting'`

- [ ] **Step 3: Implémenter `sentiment_prompting.py`**

```python
"""sentiment_prompting.py — Prompt Gemma adaptatif + verdict pour les appels UCC."""
from __future__ import annotations
from dataclasses import dataclass
import config
import csat_aircall
import ollama_client

VERDICTS = {"Agent/Assistance", "Borne/App", "Mixte", "Autre"}
RECOVERABLE = {"oui", "non", "partiel"}


@dataclass
class SentimentInsight:
    verdict: str       # '' si déterministe (non répondu sans transcript)
    moment: str
    recoverable: str   # 'oui'|'non'|'partiel'|''
    synthese: str


def _trajectory_txt(scores: dict | None) -> str:
    if not scores:
        return "non disponible"
    keys = ("initial_score", "peak_negative_score", "final_score", "label", "confidence")
    parts = [f"{k}={scores[k]}" for k in keys if k in scores]
    return ", ".join(parts) or "non disponible"


def build_prompt(kind: str, transcript: str, facts: dict | None, scores: dict | None) -> str:
    cadre = (
        "Cet appel a été marqué « non répondu » par un bot, mais une conversation existe : "
        "explique ce qui s'est réellement passé."
        if kind == "unanswered" else
        "Cet appel a reçu un score de sentiment négatif : explique pourquoi."
    )
    return f"""Tu analyses un appel d'assistance Driveco (recharge de véhicules électriques).
{cadre}
Trajectoire de sentiment (bot) : {_trajectory_txt(scores)}.
{csat_aircall.format_facts_line(facts) or "Faits Aircall : non disponibles."}

Transcript de l'appel :
\"\"\"
{transcript}
\"\"\"

Réponds STRICTEMENT en JSON : {{"verdict": "...", "moment": "...", "recoverable": "...", "synthese": "..."}}
- "verdict" parmi exactement : "Agent/Assistance", "Borne/App", "Mixte", "Autre" (le côté dominant du motif).
- "moment" : courte phrase sur ce qui a fait basculer (ex. "échec paiement répété ~8min"). <= 12 mots.
- "recoverable" parmi exactement : "oui", "non", "partiel" (la situation a-t-elle été rattrapée ?).
- "synthese" : 50 mots MAXIMUM, 2-3 lignes, en français. Pas de liste, pas de note /10, pas de reco.
  Si le transcript est trop dégradé pour conclure, dis-le sans inventer."""


def _norm_verdict(v: str) -> str:
    v = str(v or "").strip()
    return v if v in VERDICTS else "Autre"


def _norm_recoverable(v: str) -> str:
    v = str(v or "").strip().lower()
    return v if v in RECOVERABLE else ""


def _truncate(text: str, max_words: int = 50) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return str(text or "").strip()
    return " ".join(words[:max_words]).rstrip(" .,;") + "…"


def _deterministic_unanswered(facts: dict | None) -> SentimentInsight:
    facts = facts or {}
    if facts.get("answered"):
        s = "Marqué « non répondu » mais Aircall indique un décrochage ; aucun transcript exploitable pour détailler."
    else:
        direction = facts.get("direction") or "inconnu"
        tta = facts.get("time_to_answer_s")
        attente = f", attente {tta}s" if tta is not None else ""
        s = f"Aucun décrochage côté Aircall (sens {direction}{attente}). Appel non abouti."
    return SentimentInsight(verdict="", moment="", recoverable="", synthese=s)


def analyze(kind: str, transcript: str, facts: dict | None, scores: dict | None) -> SentimentInsight:
    if kind == "unanswered" and not transcript:
        return _deterministic_unanswered(facts)
    data = ollama_client.generate_json(
        build_prompt(kind, transcript, facts, scores),
        timeout=config.OLLAMA_ANALYSIS_TIMEOUT,
    )
    return SentimentInsight(
        verdict=_norm_verdict(data.get("verdict")),
        moment=_truncate(data.get("moment"), 14),
        recoverable=_norm_recoverable(data.get("recoverable")),
        synthese=_truncate(data.get("synthese"), 50),
    )
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python -m pytest tests/test_sentiment_prompting.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add sentiment_prompting.py tests/test_sentiment_prompting.py
git commit -m "feat(sentiment): analyse Gemma adaptative (négatif LLM / non-répondu déterministe)"
```

---

## Task 6: Orchestration (`sentiment_insight.py`)

**Files:**
- Create: `sentiment_insight.py`
- Test: `tests/test_sentiment_insight.py`

Comportement de `run_once(now_epoch, state_path)` (calqué sur `csat_insight`) :
1. `DISABLE_SENTIMENT_INSIGHT` → return.
2. État via `csat_state` ; `last_ts == "0"` → baseline = now, save, return (go-forward).
3. `posts = fetch_new_posts_by_author(channel, last_ts, PINGOUIN_BOT_ID)` (triés croissant).
4. Traiter d'abord les `pending`, puis **au plus `cap`** nouveaux posts ; `last_ts` avance jusqu'au **dernier traité** (les non-traités restent pour la passe suivante).
5. `_process_post` : pas de call_id → done(skip) ; déjà répondu → done(skip) ;
   `transcript = fetch_transcript`, `facts = fetch_call_facts` ;
   si `kind=='negative'` et pas de transcript → budget pending (20/1h) puis lien-seul ;
   sinon `analyze(kind, transcript, facts, scores)` + `post_thread(render(...))`.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
# tests/test_sentiment_insight.py
import sentiment_insight
import csat_state


def _neg(ts, call_id="3827871596"):
    return {"ts": ts, "bot_id": "B0B6V282D5Y",
            "text": (f"Access link : <https://assets.aircall.io/calls/{call_id}/recording/info>\n"
                     "Score [-1 to +1] : -0.6 (confidance : 95%)\n{ \"final_score\": -0.6 }")}


def _unans(ts, call_id="3827393590"):
    return {"ts": ts, "bot_id": "B0B6V282D5Y",
            "text": f"[Call not answered]\nAccess link : <https://assets.aircall.io/calls/{call_id}/recording/info>"}


def _wire(monkeypatch, *, posts=None, transcript="Agent: bonjour", facts=None, has_reply=False):
    posted = []
    monkeypatch.setattr(sentiment_insight, "fetch_new_posts_by_author",
                        lambda *a, **k: list(posts or []))
    monkeypatch.setattr(sentiment_insight, "fetch_transcript", lambda cid: transcript)
    monkeypatch.setattr(sentiment_insight, "fetch_call_facts",
                        lambda cid: (facts if facts is not None else {"answered": True, "duration_s": 288, "time_to_answer_s": 38}))
    monkeypatch.setattr(sentiment_insight, "thread_has_bot_reply", lambda *a, **k: has_reply)
    monkeypatch.setattr(sentiment_insight, "analyze",
                        lambda *a, **k: sentiment_insight.SentimentInsight("Borne/App", "échec paiement", "non", "Borne HS."))
    def fake_post(channel, thread_ts, text, token=None):
        posted.append((thread_ts, text)); return True
    monkeypatch.setattr(sentiment_insight, "post_thread", fake_post)
    monkeypatch.setattr(sentiment_insight.config, "DISABLE_SENTIMENT_INSIGHT", False)
    monkeypatch.setattr(sentiment_insight.config, "SENTIMENT_INSIGHT_MAX_PER_RUN", 5)
    return posted


def test_first_run_baseline_posts_nothing(monkeypatch, tmp_path):
    posted = _wire(monkeypatch, posts=[_neg("10.0")])
    sf = tmp_path / "s.json"
    sentiment_insight.run_once(now_epoch=999, state_path=sf)
    assert posted == []
    assert csat_state.load_state(sf)["last_ts"] == "999"


def test_posts_negative_with_verdict_and_score(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, posts=[_neg("10.0", "3827871596")])
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert len(posted) == 1
    ts, text = posted[0]
    assert ts == "10.0"
    assert "Borne/App" in text and "3827871596" in text and "-0.6" in text


def test_unanswered_but_answered_adds_mismatch_note(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, posts=[_unans("10.0")],
                   facts={"answered": True, "duration_s": 273, "time_to_answer_s": 114})
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert "non répondu" in posted[0][1].lower() and "décroché" in posted[0][1].lower()


def test_cap_limits_posts_per_run_and_advances_to_last_processed(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    posts = [_neg(f"{10 + i}.0") for i in range(8)]   # 8 nouveaux
    posted = _wire(monkeypatch, posts=posts)
    monkeypatch.setattr(sentiment_insight.config, "SENTIMENT_INSIGHT_MAX_PER_RUN", 3)
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert len(posted) == 3                                  # cap respecté
    assert csat_state.load_state(sf)["last_ts"] == "12.0"    # dernier traité (10,11,12)


def test_no_call_id_skips(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    bad = {"ts": "10.0", "bot_id": "B0B6V282D5Y", "text": "[Call not answered] (lien manquant)"}
    posted = _wire(monkeypatch, posts=[bad])
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert posted == []
    assert csat_state.load_state(sf)["last_ts"] == "10.0"


def test_already_replied_skips(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, posts=[_neg("10.0")], has_reply=True)
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert posted == []
```

- [ ] **Step 2: Lancer pour vérifier l'échec**

Run: `python -m pytest tests/test_sentiment_insight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sentiment_insight'`

- [ ] **Step 3: Implémenter `sentiment_insight.py`**

```python
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
    facts = fetch_call_facts(post.call_id)
    if post.kind == "negative" and not transcript:
        budget_done = attempts + 1 >= PENDING_MAX_ATTEMPTS or (now_epoch - first_seen) > PENDING_MAX_AGE_S
        if budget_done:
            post_thread(channel, post.ts, _render_link_only(post))
            return "done"
        return "pending"
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
```

- [ ] **Step 4: Lancer pour vérifier le succès**

Run: `python -m pytest tests/test_sentiment_insight.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lancer toute la nouvelle suite sentiment + slack + aircall**

Run: `python -m pytest tests/test_sentiment_parser.py tests/test_sentiment_prompting.py tests/test_sentiment_insight.py tests/test_csat_slack.py tests/test_csat_aircall.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sentiment_insight.py tests/test_sentiment_insight.py
git commit -m "feat(sentiment): orchestration run_once (baseline, cap, pending, idempotence, mismatch)"
```

---

## Task 7: Smoke test + ordonnancement launchd + docs

**Files:**
- Modify: `setup_launchd.sh`, `RUNBOOK.md`, `README.md`

- [ ] **Step 1: Smoke test sûr (lecture seule, ne poste rien)**

Run: `DISABLE_SENTIMENT_INSIGHT=true python sentiment_insight.py`
Expected: log `Sentiment Insight désactivé`.

Baseline jetable (lit Slack, ne poste rien) :
Run: `python -c "import sentiment_insight, pathlib; sentiment_insight.run_once(state_path=pathlib.Path('/tmp/sent_smoke.json'))"`
Expected: log `Baseline initialisée…`, `/tmp/sent_smoke.json` créé. Puis supprimer le fichier.

- [ ] **Step 2: Ajouter le job launchd dans `setup_launchd.sh`**

Sur le modèle EXACT du job `com.kev1n.driveco.csat-insight` déjà présent (mêmes variables `$PYTHON_BIN`, `$RUNTIME_DIR`, `$LOG_DIR`) :
- Label var `SENTIMENT_INSIGHT_LABEL="com.kev1n.driveco.sentiment-insight"` + `SENTIMENT_INSIGHT_PLIST=...`.
- Bloc plist lançant `${RUNTIME_DIR}/sentiment_insight.py`, `StartInterval` 180, logs `sentiment-insight.log` / `.err.log`, `RunAtLoad` false, `AbandonProcessGroup` true.
- Ajouter le label à la boucle `bootout`, un `launchctl bootstrap`, et la ligne d'écho récap (`sentiment-insight : toutes les 180s`).

- [ ] **Step 3: Documenter**

`RUNBOOK.md` : section « Sentiment Call Insight » (but, label `com.kev1n.driveco.sentiment-insight`, 180s, logs `sentiment-insight*.log`, flag `DISABLE_SENTIMENT_INSIGHT`, cap `SENTIMENT_INSIGHT_MAX_PER_RUN`, état `.sentiment_insight_state.json`, go-forward).
`README.md` : une ligne dans les composants.

- [ ] **Step 4: Commit**

```bash
git add setup_launchd.sh RUNBOOK.md README.md
git commit -m "ops(sentiment): job launchd 180s + doc RUNBOOK/README"
```

---

## Task 8: Documentation externe (Obsidian / Notion / mémoire)

> Pas de code ; après validation fonctionnelle.

- [ ] **Step 1: Note Obsidian** dans `~/Documents/Obsidian/10 - Pro/Kev1n Cockpit/` (objectif, canal, 2 types, format, cap, go-forward, lien spec/plan).
- [ ] **Step 2: Page Notion** sous « Tour de Contrôle — Workspace » via le connecteur Notion.
- [ ] **Step 3: Mémoire** : `project_sentiment_call_insight.md` (type project) + ligne d'index `MEMORY.md`, liens `[[project_csat_call_insight]]`, `[[project_driveco_qa_pipeline]]`.
- [ ] **Step 4: Pousser la branche / PR** (`git push -u origin feat/sentiment-insight` puis PR), et go-live délibéré (`sync_launchd_runtime.sh && setup_launchd.sh`) sur arbre propre.

---

## Self-Review (couverture spec)

- Canal Pingouin `C0B7PA2EZQ8`, filtre `bot_id` → Task 2 + Task 6. ✓
- 2 types (negative/unanswered), call_id depuis lien + `html.unescape` → Task 4. ✓
- Négatif : verdict + moment + rattrapable, trajectoire au prompt → Task 5. ✓
- Non-répondu adaptatif (transcript→LLM ; sinon déterministe) → Task 5 (`_deterministic_unanswered`, `analyze`). ✓
- Signalement incohérence « non répondu mais décroché » → Task 6 (`_render`) + test. ✓
- Tout traité, cap anti-saturation, go-forward → Task 1 + Task 6 (`cap`, baseline). ✓
- Réutilisation transcript/faits/état/slack, `format_facts_line` partagé → Tasks 2,3,5,6. ✓
- launchd + docs + doc externe → Tasks 7,8. ✓
- v2 hors scope (dédoublonnage, repeat-caller) → non implémenté. ✓
