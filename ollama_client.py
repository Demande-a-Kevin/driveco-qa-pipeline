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

_UCC_EVALUATION_RUBRIC = """Grille d'évaluation QA assistance Driveco/UCC à appliquer pour chaque appel :
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
- retourne immédiatement la réponse finale, sans exposer de raisonnement
- si un élément n'est pas observable, n'invente pas
- si pas de transcript exploitable, laisse les sous-notes soft_skills à null quand nécessaire
- la note_globale soft_skills doit refléter cette grille pondérée quand l'observation est possible
- toute erreur de procédure ou de dépannage doit être confrontée à la KB fournie
- les valeurs customer_call_reason, positives, errors et recommendations doivent être des phrases simples ou labels lisibles en français, jamais des dicts, jamais du pseudo-JSON"""


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


def _is_gemma4_model(model: str) -> bool:
    return str(model or "").strip().lower().startswith("gemma4")


def _chat(model: str, messages: list[dict], max_tokens: int = 2048, timeout: int | None = None,
          json_mode: bool = False) -> str:
    """
    Appel bas niveau vers l'API native Ollama (/api/chat).
    Plus compatible que /v1/chat/completions qui requiert une version récente.
    Retourne le texte brut de la réponse.
    """
    options = {
        "temperature": config.OLLAMA_TEMPERATURE,
        "num_predict": max_tokens,
        "top_p": config.OLLAMA_TOP_P,
        "top_k": config.OLLAMA_TOP_K,
    }
    if config.OLLAMA_NUM_CTX:
        options["num_ctx"] = config.OLLAMA_NUM_CTX

    if _is_gemma4_model(model) and config.OLLAMA_ENABLE_THINKING and messages:
        first_message = messages[0]
        if first_message.get("role") == "system" and not str(first_message.get("content") or "").startswith("<|think|>"):
            first_message["content"] = f"<|think|>\n{first_message.get('content', '')}"

    url = f"{config.OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    if json_mode:
        payload["format"] = "json"
    resp = _SESSION.post(url, json=payload, timeout=timeout or config.OLLAMA_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def _generate(model: str, prompt: str, max_tokens: int = 2048, timeout: int | None = None,
              json_mode: bool = False) -> str:
    options = {
        "temperature": config.OLLAMA_TEMPERATURE,
        "num_predict": max_tokens,
        "top_p": config.OLLAMA_TOP_P,
        "top_k": config.OLLAMA_TOP_K,
    }
    if config.OLLAMA_NUM_CTX:
        options["num_ctx"] = config.OLLAMA_NUM_CTX

    url = f"{config.OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if json_mode:
        payload["format"] = "json"
    resp = _SESSION.post(url, json=payload, timeout=timeout or config.OLLAMA_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _parse_json(raw: str) -> dict:
    """Parse JSON depuis la réponse Ollama — gère les blocs ```json ... ```."""
    text = raw.strip()
    text = re.sub(r"<\|channel\>thought\s*.*?<channel\|>", "", text, flags=re.DOTALL)
    text = re.sub(r"<\|channel\>.*?<channel\|>", "", text, flags=re.DOTALL)
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Cherche le premier objet JSON valide dans la réponse
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

    max_lines = 36 if _is_gemma4_model(config.OLLAMA_MODEL_ANALYSIS) else 24
    return "\n".join(lines[:max_lines])


def _clean_eval_text(value) -> str | None:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    if len(text) < 4 and text.upper() not in {"B2B", "B2C", "UCC", "IVR", "CSAT"}:
        return None
    return text


def _sanitize_call_evaluation(ev: dict) -> dict:
    if not isinstance(ev, dict):
        return {}

    for list_key in ("positives", "errors", "recommendations"):
        cleaned_items = []
        for item in ev.get(list_key) or []:
            cleaned = _clean_eval_text(item)
            if cleaned:
                cleaned_items.append(cleaned)
        ev[list_key] = cleaned_items

    cleaned_reason = _clean_eval_text(ev.get("customer_call_reason"))
    if cleaned_reason:
        ev["customer_call_reason"] = cleaned_reason
    else:
        ev["customer_call_reason"] = None

    soft_skills = ev.get("soft_skills")
    if not isinstance(soft_skills, dict):
        ev["soft_skills"] = {}

    return ev


# ── Pre-screening ─────────────────────────────────────────────────────────────

_SCREENING_PROMPT = """Tu es un outil de triage QA pour un service client téléphonique (bornes recharge VE).
Analyse ces métadonnées d'appel et donne un score de risque qualité de 0 à 10.

Critères de risque élevé :
- Appel non répondu / overflow / abandonné → +3
- Durée < 60s sur un appel répondu (non-résolution probable) → +3
- Tag "escalation" présent → +2
- Appel très long > 15min (situation complexe) → +1
- Rappel du même numéro dans la journée → +2

Règles :
- retourne immédiatement la réponse finale, sans raisonnement
- risk doit être un nombre entre 0 et 10
- reason doit être une phrase courte en français

Réponds UNIQUEMENT avec ce JSON :
{"risk": <0-10>, "reason": "<explication courte en français, 4 à 12 mots>"}"""

_SCREENING_BATCH_PROMPT = """Tu es un outil de triage QA pour un service client téléphonique (bornes recharge VE).
Pour chaque appel, donne :
- un score de risque qualité de 0 à 10
- une raison courte en français

Critères de risque élevé :
- Appel non répondu / overflow / abandonné → +3
- Durée < 60s sur un appel répondu (non-résolution probable) → +3
- Tag "escalation" présent → +2
- Appel très long > 15min (situation complexe) → +1
- Rappel du même numéro dans la journée → +2

Règles :
- retourne immédiatement la réponse finale, sans raisonnement
- chaque risk doit être un nombre entre 0 et 10
- chaque reason doit être une phrase courte en français

Réponds UNIQUEMENT avec ce JSON :
{"results":[{"call_id":"...","risk":0,"reason":"..."}]}"""


def _heuristic_prescreen(call: dict) -> tuple[float, str]:
    score = 0.0
    answered = call.get("answered", "No")
    duration = call.get("duration_in_call") or 0
    tags = call.get("tags") or ""
    missed_reason = call.get("missed_call_reason") or ""
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


def _normalize_risk_value(value, default: float = 5.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().lower()
    if not text:
        return default
    mapping = {
        "low": 2.0,
        "faible": 2.0,
        "medium": 5.0,
        "moyen": 5.0,
        "high": 8.0,
        "élevé": 8.0,
        "eleve": 8.0,
        "critical": 9.0,
        "critique": 9.0,
    }
    if text in mapping:
        return mapping[text]
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return default


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
            max_tokens=192 if _is_gemma4_model(config.OLLAMA_MODEL_SCREENING) else 64,
            timeout=config.OLLAMA_PRESCREEN_TIMEOUT,
            json_mode=True,
        )
        result = _parse_json(raw)
        score = _normalize_risk_value(result.get("risk"), default=5.0)
        reason = _clean_eval_text(result.get("reason")) or "motif non précisé"
        return min(max(score, 0.0), 10.0), reason

    except Exception as e:
        log.debug(f"[ollama pre-screen] fallback heuristique ({e})")
        return _heuristic_prescreen(call)


def pre_screen_batch(calls: list[dict]) -> dict[str, tuple[float, str]]:
    if not calls:
        return {}

    payload_calls = []
    fallback = {}
    for call in calls:
        call_id = str(call.get("call_id_internal") or call.get("call_id") or "").strip()
        if not call_id:
            continue
        fallback[call_id] = _heuristic_prescreen(call)
        payload_calls.append({
            "call_id": call_id,
            "type": call.get("classified_type", ""),
            "answered": call.get("answered", "No"),
            "duration_s": call.get("duration_in_call") or 0,
            "tags": call.get("tags") or None,
            "missed_reason": call.get("missed_call_reason") or None,
        })

    if not payload_calls:
        return {}

    try:
        if _is_gemma4_model(config.OLLAMA_MODEL_SCREENING):
            raw = _generate(
                model=config.OLLAMA_MODEL_SCREENING,
                prompt=f"{_SCREENING_BATCH_PROMPT}\n\nAppels:\n{json.dumps(payload_calls, ensure_ascii=False)}",
                max_tokens=max(512, len(payload_calls) * 128),
                timeout=config.OLLAMA_PRESCREEN_TIMEOUT,
                json_mode=True,
            )
        else:
            raw = _chat(
                model=config.OLLAMA_MODEL_SCREENING,
                messages=[
                    {"role": "system", "content": _SCREENING_BATCH_PROMPT},
                    {"role": "user", "content": json.dumps({"calls": payload_calls}, ensure_ascii=False)},
                ],
                max_tokens=max(160, len(payload_calls) * 28),
                timeout=config.OLLAMA_PRESCREEN_TIMEOUT,
                json_mode=True,
            )
        result = _parse_json(raw)
        rows = result.get("results", [])
        if not isinstance(rows, list):
            return fallback
        merged = dict(fallback)
        for row in rows:
            if not isinstance(row, dict):
                continue
            call_id = str(row.get("call_id") or "").strip()
            if not call_id:
                continue
            heuristic_risk = merged.get(call_id, (5.0, ""))[0]
            risk = max(heuristic_risk, _normalize_risk_value(row.get("risk"), default=heuristic_risk))
            reason = _clean_eval_text(row.get("reason")) or merged.get(call_id, (risk, "motif non précisé"))[1]
            merged[call_id] = (min(max(risk, 0.0), 10.0), reason)
        return merged
    except Exception as e:
        log.debug(f"[ollama pre-screen batch] fallback heuristique ({e})")
        return fallback


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

=== GRILLE D'ÉVALUATION QA ===
{_UCC_EVALUATION_RUBRIC}

=== KNOWLEDGE BASE ===
{kb_summary}

=== APPELS À ÉVALUER ({len(calls_block)}) ===
{json.dumps(calls_block, indent=2, ensure_ascii=False)}

Règles de sortie :
- copie le classified_type/type de l'appel dans "classified_type"
- "customer_call_reason" = raison principale de l'appel, courte et lisible
- "positives" et "errors" = phrases courtes en français, jamais des objets ou fragments JSON
- "alerts" = objets {{"level":"critical|warning|info","message":"...","call_ids":[...]}} seulement si nécessaire
- si le transcript est insuffisant, garde soft_skills.* à null plutôt que d'inventer

Évalue chaque appel. Réponds UNIQUEMENT avec le JSON, champ "call_evaluations" :
{{"call_evaluations": [...]}}"""

    try:
        raw = _chat(
            model=config.OLLAMA_MODEL_ANALYSIS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=6000 if _is_gemma4_model(config.OLLAMA_MODEL_ANALYSIS) else 3000,
            timeout=config.OLLAMA_ANALYSIS_TIMEOUT,
            json_mode=True,
        )
        result = _parse_json(raw)
        evals = result.get("call_evaluations", [])
        if not isinstance(evals, list):
            return []
        # Tag les évaluations comme produites par Ollama
        for idx, ev in enumerate(evals):
            evals[idx] = _sanitize_call_evaluation(ev)
        for ev in evals:
            ev["_model"] = config.OLLAMA_MODEL_ANALYSIS
        return evals

    except Exception as e:
        log.warning(f"[ollama analyze_batch] échec ({e}) — batch sera traité par Claude")
        return []
