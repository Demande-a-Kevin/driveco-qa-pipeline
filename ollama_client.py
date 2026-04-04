"""
ollama_client.py — Appels à Ollama local (Mac mini Kev1n, port 11434).
API compatible OpenAI — même format que llm_client.py mais local, zéro coût.

Deux fonctions principales :
  - pre_screen_call()   : score de risque rapide sur metadata seule (0-10)
  - analyze_batch()     : analyse QA complète d'un batch d'appels (avec/sans transcript)
"""
import json
import logging
import re
import requests
import config

log = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"Content-Type": "application/json"})

_UCC_EVALUATION_RUBRIC = """Grille d'évaluation UCC à appliquer pour chaque appel :
1. Présentation de l'agent et de la marque — poids 0.05
   Attendu : l'agent se présente correctement et cite Driveco au début.
2. Empathie et écoute active — poids 0.15
   Attendu : l'agent reconnaît la gêne du client et adopte un ton compréhensif.
3. Investigation — poids 0.05
   Attendu : l'agent pose les bonnes questions avant d'agir.
4. Compréhension du problème — poids 0.20
   Attendu : la cause principale est correctement identifiée.
5. Étapes de dépannage — poids 0.20
   Attendu : le client est guidé dans les bonnes étapes selon le problème.
6. Solutions alternatives — poids 0.10
   Attendu : une alternative est proposée si la première résolution n'est pas possible.
7. Création du ticket / escalade du dossier — poids 0.05
   Attendu : escalade ou ticket si nécessaire, avec prochaines étapes claires.
8. Clôture de l'échange — poids 0.05
   Attendu : résolution ou next steps confirmées avant la fin.
9. Qualité de la communication — poids 0.05
   Attendu : ton poli, professionnel, accessible.
10. Clarté et exactitude de l'information — poids 0.10
   Attendu : informations justes et vérification que le client a compris.

Règles d'usage :
- utilise cette grille comme base principale pour positives, errors, alerts et soft_skills
- raisonne critère par critère en interne, mais ne renvoie que le JSON demandé
- si un élément n'est pas observable, n'invente pas
- si pas de transcript exploitable, laisse les sous-notes soft_skills à null quand nécessaire
- la note_globale soft_skills doit refléter cette grille pondérée quand l'observation est possible
- toute erreur de procédure ou de dépannage doit être confrontée à la KB fournie"""


def is_available() -> bool:
    """
    Vérifie qu'Ollama tourne ET que l'endpoint de chat répond.
    Silencieux si absent.
    """
    try:
        # 1. Check de base : le serveur est up
        resp = _SESSION.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            return False
        # 2. Vérifie que le modèle est bien chargé
        tags = resp.json()
        models = [m.get("name", "") for m in tags.get("models", [])]
        if not any(config.OLLAMA_MODEL_ANALYSIS in m for m in models):
            log.debug(f"[ollama] Modèle {config.OLLAMA_MODEL_ANALYSIS} absent — {models}")
            return False
        return True
    except Exception:
        return False


def _chat(model: str, messages: list[dict], max_tokens: int = 2048, timeout: int | None = None) -> str:
    """
    Appel bas niveau vers l'API native Ollama (/api/chat).
    Plus compatible que /v1/chat/completions qui requiert une version récente.
    Retourne le texte brut de la réponse.
    """
    url = f"{config.OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.1,    # Déterministe — on veut du JSON fiable
            "num_predict": max_tokens,
        },
    }
    resp = _SESSION.post(url, json=payload, timeout=timeout or config.OLLAMA_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def _parse_json(raw: str) -> dict:
    """Parse JSON depuis la réponse Ollama — gère les blocs ```json ... ```."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Cherche le premier objet JSON valide dans la réponse
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        log.warning(f"[ollama] Réponse non-JSON : {raw[:200]}")
        return {}


def _prepare_transcript_for_ollama(transcript: str) -> str:
    """
    Réduit le bruit de diarisation avant envoi au modèle.
    Garde en priorité les tours de parole substantiels et compacts.
    """
    lines = []
    for raw_line in str(transcript or "").splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        match = re.match(r"^\[(Agent|Client)\]\s*(.*)$", line)
        if not match:
            continue
        label, content = match.groups()
        content = content.strip()
        if not content:
            continue
        word_count = len(content.split())
        if len(content) < 15 and word_count < 3:
            continue
        lines.append(f"[{label}] {content}")

    if len(lines) < 8:
        lines = [" ".join(line.strip().split()) for line in str(transcript or "").splitlines() if line.strip()]

    return "\n".join(lines[:24])


# ── Pre-screening ─────────────────────────────────────────────────────────────

_SCREENING_PROMPT = """Tu es un outil de triage QA pour un service client téléphonique (bornes recharge VE).
Analyse ces métadonnées d'appel et donne un score de risque qualité de 0 à 10.

Critères de risque élevé :
- Appel non répondu / overflow / abandonné → +3
- Durée < 60s sur un appel répondu (non-résolution probable) → +3
- Tag "escalation" présent → +2
- Appel très long > 15min (situation complexe) → +1
- Rappel du même numéro dans la journée → +2

Réponds UNIQUEMENT avec ce JSON :
{"risk": <0-10>, "reason": "<une phrase max>"}"""


def pre_screen_call(call: dict) -> tuple[float, str]:
    """
    Score de risque qualité pour un appel (metadata only, pas de transcript).
    Retourne (score float 0-10, raison str).
    Fallback sur scoring heuristique si Ollama indisponible.
    """
    call_type    = call.get("classified_type", "")
    answered     = call.get("answered", "No")
    duration     = call.get("duration_in_call") or 0
    tags         = call.get("tags") or ""
    missed_reason = call.get("missed_call_reason") or ""

    # Fallback heuristique — utilisé si Ollama est hors ligne
    def _heuristic_score() -> tuple[float, str]:
        score = 0.0
        if answered == "No":
            score += 3.0
        elif duration < 60:
            score += 3.0
        elif duration > 900:
            score += 1.0
        if "escalation" in tags.lower():
            score += 2.0
        if missed_reason == "timeout":
            score += 2.0
        return min(score, 10.0), "score heuristique (Ollama indisponible)"

    try:
        metadata_block = {
            "type": call_type,
            "answered": answered,
            "duration_s": duration,
            "tags": tags or None,
            "missed_reason": missed_reason or None,
        }
        metadata_block = {k: v for k, v in metadata_block.items() if v is not None}
        user_msg = f"Appel : {json.dumps(metadata_block, ensure_ascii=False)}"

        raw = _chat(
            model=config.OLLAMA_MODEL_SCREENING,
            messages=[
                {"role": "system", "content": _SCREENING_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=64,
            timeout=15,  # Timeout court pour le pre-screening
        )
        result = _parse_json(raw)
        score = float(result.get("risk", 5.0))
        reason = result.get("reason", "")
        return min(max(score, 0.0), 10.0), reason

    except Exception as e:
        log.debug(f"[ollama pre-screen] fallback heuristique ({e})")
        return _heuristic_score()


# ── Analyse batch ─────────────────────────────────────────────────────────────

def analyze_batch(system_prompt: str, batch_calls: list[dict],
                  kb_summary: str, date_str: str,
                  batch_num: int = 1, total_batches: int = 1) -> list[dict]:
    """
    Analyse QA d'un batch d'appels via Ollama.
    Retourne une liste de call_evaluations (même format que llm_client.analyze).
    Retourne [] si Ollama indisponible — le pipeline continue avec Claude.
    """
    if not batch_calls:
        return []

    calls_block = []
    for c in batch_calls:
        entry = {
            "call_id": c.get("call_id_internal") or c.get("call_id"),
            "type": c.get("classified_type"),
            "duration_s": c.get("duration_in_call"),
            "wait_s": c.get("waiting_time"),
            "agent": c.get("user_name"),
        }
        entry = {k: v for k, v in entry.items() if v is not None and v != ""}
        if c.get("answered") == "No":
            entry["missed"] = c.get("missed_call_reason") or "abandoned"
        if c.get("tags"):
            entry["tags"] = c["tags"]
        transcript = _prepare_transcript_for_ollama(c.get("transcript") or "")
        transcript = transcript[:config.OLLAMA_TRANSCRIPT_MAX_CHARS]
        if transcript:
            entry["transcript"] = transcript
        calls_block.append(entry)

    user_prompt = f"""MODE : BATCH OLLAMA {batch_num}/{total_batches}
DATE : {date_str}

=== GRILLE D'ÉVALUATION UCC ===
{_UCC_EVALUATION_RUBRIC}

=== KNOWLEDGE BASE ===
{kb_summary}

=== APPELS À ÉVALUER ({len(calls_block)}) ===
{json.dumps(calls_block, indent=2, ensure_ascii=False)}

Évalue chaque appel. Réponds UNIQUEMENT avec le JSON, champ "call_evaluations" :
{{"call_evaluations": [...]}}"""

    try:
        raw = _chat(
            model=config.OLLAMA_MODEL_ANALYSIS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=3000,
            timeout=config.OLLAMA_ANALYSIS_TIMEOUT,
        )
        result = _parse_json(raw)
        evals = result.get("call_evaluations", [])
        if not isinstance(evals, list):
            return []
        # Tag les évaluations comme produites par Ollama
        for ev in evals:
            ev["_model"] = config.OLLAMA_MODEL_ANALYSIS
        return evals

    except Exception as e:
        log.warning(f"[ollama analyze_batch] échec ({e}) — batch sera traité par Claude")
        return []
