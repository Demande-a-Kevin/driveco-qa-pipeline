"""
llm_client.py — Appel à l'API Anthropic (Claude).
Récupère dynamiquement les modèles depuis qa_config en D1.
"""
import json

import anthropic

import d1_client
import config
import qa_prompting
import schemas
import rubric


# Charge les modèles depuis qa_config si disponibles
def _load_models_from_db() -> dict:
    try:
        rows = d1_client.query("SELECT key, value FROM qa_config WHERE key LIKE 'ANALYSIS_MODEL%'")
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


_db_models: dict | None = None


def _get_model(key: str, fallback: str) -> str:
    global _db_models
    if _db_models is None:
        _db_models = _load_models_from_db()
    return _db_models.get(key, fallback)


def get_model_standard() -> str:
    return _get_model("ANALYSIS_MODEL_DEFAULT", config.MODEL_STANDARD)


def get_model_flagged() -> str:
    """Modèle pour les appels flaggés / haut risque (Haiku par défaut)."""
    return _get_model("ANALYSIS_MODEL_FLAGGED", config.MODEL_FLAGGED)


def get_model_reporting() -> str:
    return _get_model("ANALYSIS_MODEL_REPORTING", config.MODEL_REPORTING)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _parse_raw_json(raw: str) -> dict:
    return schemas.parse_json_strict(raw)


def analyze(
    system_prompt: str,
    user_prompt: str | None = None,
    model: str | None = None,
    max_tokens: int = 8192,
    response_model=None,
    max_retries: int = 2,
    messages: list[dict] | None = None,
) -> dict:
    """
    Appelle Claude avec un system + user prompt.
    Retourne le JSON parsé ou raise si la réponse n'est pas du JSON valide.
    """
    if model is None:
        model = get_model_reporting()

    client = _client()
    if messages is None:
        if user_prompt is None:
            raise ValueError("user_prompt ou messages requis")
        messages = [{"role": "user", "content": user_prompt}]
    else:
        messages = [dict(message) for message in messages]
    last_error = None

    for attempt in range(max_retries + 1):
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )

        raw = message.content[0].text.strip()
        usage = getattr(message, "usage", None)
        llm_meta = {
            "model": model,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        try:
            parsed = _parse_raw_json(raw)
            if response_model is not None:
                parsed = response_model.model_validate(parsed).model_dump()
            parsed["_llm_meta"] = llm_meta
            return parsed
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= max_retries:
                raise
            if response_model is None:
                raise
            messages = messages + [
                {
                    "role": "user",
                    "content": qa_prompting.build_retry_message(
                        schemas.validation_error_message(exc),
                        response_model.model_json_schema(),
                        invalid_fields=schemas.validation_error_fields(exc),
                    ),
                }
            ]

    raise ValueError(f"Analyse Anthropic invalide: {last_error}") from last_error


def analyze_batch(batch_calls: list[dict], kb_summary: str, model: str | None = None) -> list[dict]:
    if model is None:
        model = get_model_standard()
    evaluations: list[dict] = []
    for call in batch_calls:
        transcript = str(call.get("transcript") or "").strip()
        if not transcript:
            continue
        extraction = analyze(
            system_prompt=qa_prompting.load_base_system_prompt(),
            messages=qa_prompting.build_extraction_messages(call, kb_summary)[1:],
            model=model,
            max_tokens=2200,
            response_model=schemas.FactualExtract,
        )
        extraction.pop("_llm_meta", None)
        scoring = analyze(
            system_prompt=qa_prompting.load_base_system_prompt(),
            messages=qa_prompting.build_scoring_messages(call, extraction)[1:],
            model=model,
            max_tokens=1800,
            response_model=schemas.CriterionScorecard,
        )
        scoring.pop("_llm_meta", None)
        provisional_score = rubric.compute_weighted_score(schemas.CriterionScorecard.model_validate(scoring).score_map())
        voc_extract = None
        if config.ENABLE_VOC_ANALYSIS:
            voc_extract = analyze(
                system_prompt=qa_prompting.load_voc_system_prompt(),
                messages=qa_prompting.build_voc_messages(call, score_global=provisional_score)[1:],
                model=model,
                max_tokens=1800,
                response_model=schemas.VoCExtract,
            )
            voc_extract.pop("_llm_meta", None)
        evaluation = schemas.build_call_evaluation(
            call=call,
            factual_extract=schemas.FactualExtract.model_validate(extraction),
            scorecard=schemas.CriterionScorecard.model_validate(scoring),
            model_name=model,
            voc_extract=schemas.VoCExtract.model_validate(voc_extract) if voc_extract else None,
        ).model_dump()
        evaluation["_model"] = model
        evaluations.append(evaluation)
    return evaluations
