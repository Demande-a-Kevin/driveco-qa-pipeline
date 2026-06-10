"""
ollama_client.py — Appels à Ollama local (Mac mini Kev1n, port 11434).
API compatible OpenAI — même format que llm_client.py mais local, zéro coût.

Deux fonctions principales :
  - pre_screen_call()   : score de risque rapide sur metadata seule (0-10)
  - analyze_batch()     : analyse QA stricte d'un batch d'appels (extraction -> scoring)
"""
import hashlib
import json
import logging
import re
import requests

import config
import qa_prompting
import schemas
import rubric

log = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"Content-Type": "application/json"})


# ── Cache idempotent des analyses QA ─────────────────────────────────────────
# Hash (transcript + modèle + flag VoC + version prompt) → payload.
# Volontairement indépendant du kb_summary : le kb_excerpt dépend de la
# composition du batch (daily vs weekly regroupent différemment les mêmes
# appels), donc inclure le kb dans la clé ferait systématiquement miss le
# cache sur le weekly. On accepte que les évaluations cachées reflètent le
# contexte KB au moment du daily ; bump LLM_ANALYSIS_CACHE_VERSION quand la
# KB ou les prompts changent significativement pour invalider en douceur.

def _cache_key(call: dict, kb_summary: str | None = None) -> str:
    payload = {
        "transcript": call.get("transcript") or "",
        "model": config.OLLAMA_MODEL_ANALYSIS,
        "voc": bool(config.ENABLE_VOC_ANALYSIS),
        "version": getattr(config, "LLM_ANALYSIS_CACHE_VERSION", "v1"),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _cache_get(key: str) -> dict | None:
    if not getattr(config, "LLM_CACHE_ENABLED", False):
        return None
    path = config.LLM_CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.debug(f"[llm_cache] lecture KO {path.name}: {exc}")
        return None


def _cache_put(key: str, payload: dict) -> None:
    if not getattr(config, "LLM_CACHE_ENABLED", False) or not isinstance(payload, dict):
        return
    try:
        path = config.LLM_CACHE_DIR / f"{key}.json"
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except OSError as exc:
        log.debug(f"[llm_cache] écriture KO: {exc}")


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
    # Les sorties JSON sont plus stables avec une génération déterministe.
    temperature = 0.0 if json_mode else config.OLLAMA_TEMPERATURE
    options = {
        "temperature": temperature,
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
    temperature = 0.0 if json_mode else config.OLLAMA_TEMPERATURE
    options = {
        "temperature": temperature,
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
    """Parse JSON strict depuis la réponse Ollama — cleanup fences + json_repair via schemas."""
    text = re.sub(r"<\|channel\>thought\s*.*?<channel\|>", "", str(raw or ""), flags=re.DOTALL)
    text = re.sub(r"<\|channel\>.*?<channel\|>", "", text, flags=re.DOTALL)
    return schemas.parse_json_strict(text)


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


def _response_schema(model_class) -> dict:
    return model_class.model_json_schema()


def _ensure_batch_stats(stats: dict | None) -> dict | None:
    if stats is None:
        return None
    stats.setdefault("calls_total", 0)
    stats.setdefault("calls_succeeded", 0)
    stats.setdefault("calls_failed", 0)
    stats.setdefault("calls_auto_truncated", 0)
    stats.setdefault("auto_truncated_fields", 0)
    stats.setdefault("retry_successes", 0)
    stats.setdefault("retries_used", 0)
    stats.setdefault("one_shot_successes", 0)
    stats.setdefault("one_shot_fallbacks", 0)
    stats.setdefault("one_shot_voc_repairs", 0)
    stats.setdefault("legacy_analysis_calls", 0)
    stats.setdefault("failure_reasons", {})
    return stats


def _summarize_error(exc: Exception) -> str:
    if isinstance(exc, ValueError) and "Expecting" in str(exc):
        return "json_invalid"
    fields = schemas.validation_error_fields(exc)
    if fields:
        return ", ".join(fields[:3])
    text = str(exc).strip()
    return text[:160] if text else exc.__class__.__name__


def _validated_chat(messages: list[dict], model_class, max_tokens: int, timeout: int,
                    stats: dict | None = None, max_attempts: int = 3) -> object:
    attempt_messages = [dict(message) for message in messages]
    last_error = None
    for attempt in range(max_attempts):
        raw = _chat(
            model=config.OLLAMA_MODEL_ANALYSIS,
            messages=attempt_messages,
            max_tokens=max_tokens,
            timeout=timeout,
            json_mode=True,
        )
        try:
            payload = _parse_json(raw)
            if attempt > 0 and stats is not None:
                stats["retry_successes"] += 1
                stats["retries_used"] += attempt
            return model_class.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= max_attempts - 1:
                break
            attempt_messages = attempt_messages + [
                {
                    "role": "user",
                    "content": qa_prompting.build_retry_message(
                        schemas.validation_error_message(exc),
                        _response_schema(model_class),
                        invalid_fields=schemas.validation_error_fields(exc),
                    ),
                }
            ]
    raise ValueError(f"validation Ollama échouée: {last_error}") from last_error


def _model_to_dict(model_object) -> dict:
    return model_object.model_dump()


def _call_id_for_log(call: dict) -> str:
    return str(call.get("call_id_internal") or call.get("call_id") or "")


def _payload_from_evaluation(evaluation: schemas.CallEvaluation) -> dict:
    payload = evaluation.model_dump()
    payload["_model"] = config.OLLAMA_MODEL_ANALYSIS
    return payload


def _repair_missing_voc(call: dict, scorecard: schemas.CriterionScorecard, stats: dict | None = None) -> schemas.VoCExtract:
    if stats is not None:
        stats["one_shot_voc_repairs"] = stats.get("one_shot_voc_repairs", 0) + 1
    provisional_score = rubric.compute_weighted_score(scorecard.score_map())
    log.warning(
        "[ollama one-shot] VoC manquante -> réparation VoC dédiée call_id=%s",
        _call_id_for_log(call),
    )
    return _validated_chat(
        qa_prompting.build_voc_messages(call, score_global=provisional_score),
        schemas.VoCExtract,
        max_tokens=1800,
        timeout=config.OLLAMA_ANALYSIS_TIMEOUT,
        stats=stats,
    )


def _analyze_single_call_one_shot(call: dict, kb_summary: str, stats: dict | None = None) -> dict:
    analysis = _validated_chat(
        qa_prompting.build_one_shot_messages(call, kb_summary, enable_voc=config.ENABLE_VOC_ANALYSIS),
        schemas.OneShotCallAnalysis,
        max_tokens=config.OLLAMA_ONE_SHOT_MAX_TOKENS,
        timeout=config.OLLAMA_ONE_SHOT_TIMEOUT,
        stats=stats,
        max_attempts=max(1, config.OLLAMA_ONE_SHOT_MAX_ATTEMPTS),
    )
    voc_extract = analysis.voc_extract if config.ENABLE_VOC_ANALYSIS else None
    if config.ENABLE_VOC_ANALYSIS and analysis.voc_extract is None:
        voc_extract = _repair_missing_voc(call, analysis.scorecard, stats=stats)
    evaluation = schemas.build_call_evaluation(
        call=call,
        factual_extract=analysis.factual_extract,
        scorecard=analysis.scorecard,
        model_name=config.OLLAMA_MODEL_ANALYSIS,
        voc_extract=voc_extract,
    )
    if stats is not None:
        stats["one_shot_successes"] += 1
    return _payload_from_evaluation(evaluation)


def _analyze_single_call_legacy(call: dict, kb_summary: str, stats: dict | None = None) -> dict | None:
    if stats is not None:
        stats["legacy_analysis_calls"] += 1
    extraction = _validated_chat(
        qa_prompting.build_extraction_messages(call, kb_summary),
        schemas.FactualExtract,
        max_tokens=2200,
        timeout=config.OLLAMA_ANALYSIS_TIMEOUT,
        stats=stats,
    )
    scoring = _validated_chat(
        qa_prompting.build_scoring_messages(call, _model_to_dict(extraction)),
        schemas.CriterionScorecard,
        max_tokens=1800,
        timeout=config.OLLAMA_ANALYSIS_TIMEOUT,
        stats=stats,
    )
    provisional_score = rubric.compute_weighted_score(scoring.score_map())
    voc_extract = None
    if config.ENABLE_VOC_ANALYSIS:
        voc_extract = _validated_chat(
            qa_prompting.build_voc_messages(call, score_global=provisional_score),
            schemas.VoCExtract,
            max_tokens=1800,
            timeout=config.OLLAMA_ANALYSIS_TIMEOUT,
            stats=stats,
        )
    evaluation = schemas.build_call_evaluation(
        call=call,
        factual_extract=extraction,
        scorecard=scoring,
        model_name=config.OLLAMA_MODEL_ANALYSIS,
        voc_extract=voc_extract,
    )
    return _payload_from_evaluation(evaluation)


def _analyze_single_call(call: dict, kb_summary: str, stats: dict | None = None) -> dict | None:
    if not call.get("transcript"):
        return None
    stats = _ensure_batch_stats(stats)
    cache_key = _cache_key(call, kb_summary)
    cached = _cache_get(cache_key)
    if cached is not None:
        if stats is not None:
            stats["cache_hits"] = stats.get("cache_hits", 0) + 1
        log.info("[ollama cache] hit call_id=%s", _call_id_for_log(call))
        return cached
    if config.OLLAMA_ANALYSIS_ONE_SHOT:
        try:
            payload = _analyze_single_call_one_shot(call, kb_summary, stats=stats)
        except Exception as exc:  # noqa: BLE001
            if stats is not None:
                stats["one_shot_fallbacks"] += 1
            if not getattr(config, "OLLAMA_LEGACY_FALLBACK_ON_ONE_SHOT_FAILURE", False):
                raise
            log.warning(
                "[ollama one-shot] fallback legacy call_id=%s (%s)",
                _call_id_for_log(call),
                exc,
            )
            payload = _analyze_single_call_legacy(call, kb_summary, stats=stats)
    else:
        payload = _analyze_single_call_legacy(call, kb_summary, stats=stats)
    _cache_put(cache_key, payload)
    return payload


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


def heuristic_prescreen_call(call: dict) -> tuple[float, str]:
    return _heuristic_prescreen(call)


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
                  batch_num: int = 1, total_batches: int = 1,
                  stats: dict | None = None) -> list[dict]:
    """
    Analyse QA d'un batch d'appels via Ollama.
    Retourne une liste de call_evaluations (même format que llm_client.analyze).
    Retourne [] si Ollama indisponible — le pipeline continue avec Claude.
    """
    if not batch_calls:
        return []

    batch_stats = _ensure_batch_stats(stats)
    evaluations: list[dict] = []
    for call in batch_calls:
        if batch_stats is not None:
            batch_stats["calls_total"] += 1
        prepared_call = dict(call)
        transcript = _prepare_transcript_for_ollama(call.get("transcript") or "")
        prepared_call["transcript"] = transcript[:config.OLLAMA_TRANSCRIPT_MAX_CHARS]
        if not prepared_call.get("transcript"):
            log.info(f"[ollama analyze_batch] appel {prepared_call.get('call_id_internal') or prepared_call.get('call_id')} ignoré: transcript insuffisant")
            continue
        clip_before = schemas.clip_stats_snapshot()
        try:
            evaluation = _analyze_single_call(prepared_call, kb_summary, stats=batch_stats)
            if evaluation:
                evaluations.append(evaluation)
                if batch_stats is not None:
                    batch_stats["calls_succeeded"] += 1
                    clipped_fields = schemas.clip_stats_snapshot() - clip_before
                    if clipped_fields > 0:
                        batch_stats["calls_auto_truncated"] += 1
                        batch_stats["auto_truncated_fields"] += clipped_fields
        except Exception as exc:  # noqa: BLE001
            if batch_stats is not None:
                batch_stats["calls_failed"] += 1
                reason = _summarize_error(exc)
                batch_stats["failure_reasons"][reason] = batch_stats["failure_reasons"].get(reason, 0) + 1
            log.warning(
                "[ollama analyze_batch] échec call_id=%s (%s)",
                prepared_call.get("call_id_internal") or prepared_call.get("call_id"),
                exc,
            )
    return evaluations


def generate_json(prompt: str, max_tokens: int = 300, timeout: int | None = None) -> dict:
    """One-shot JSON local (Gemma). Réutilisé par csat_prompting / sentiment_prompting."""
    raw = _generate(config.OLLAMA_MODEL_ANALYSIS, prompt, max_tokens=max_tokens,
                    timeout=timeout, json_mode=True)
    return _parse_json(raw)
