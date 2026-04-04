"""
llm_client.py — Appel à l'API Anthropic (Claude).
Récupère dynamiquement les modèles depuis qa_config en D1.
"""
import json
import anthropic
import d1_client
import config


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


def analyze(system_prompt: str, user_prompt: str, model: str | None = None, max_tokens: int = 8192) -> dict:
    """
    Appelle Claude avec un system + user prompt.
    Retourne le JSON parsé ou raise si la réponse n'est pas du JSON valide.
    """
    if model is None:
        model = get_model_reporting()

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text.strip()
    usage = getattr(message, "usage", None)
    llm_meta = {
        "model": model,
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }

    # Nettoyer les éventuels blocs markdown ```json ... ```
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Tentative de parse JSON — si tronqué, extraire la partie valide
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed["_llm_meta"] = llm_meta
        return parsed
    except json.JSONDecodeError:
        # Chercher le dernier objet JSON complet dans la réponse
        import re
        # Essayer d'extraire JSON entre { ... }
        match = re.search(r'^\s*\{', raw)
        if match:
            # Trouver le niveau de fermeture le plus loin possible
            depth = 0
            last_valid_end = -1
            in_str = False
            escape = False
            for i, ch in enumerate(raw):
                if escape:
                    escape = False
                    continue
                if ch == '\\' and in_str:
                    escape = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if not in_str:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            last_valid_end = i
            if last_valid_end > 0:
                try:
                    parsed = json.loads(raw[:last_valid_end + 1])
                    if isinstance(parsed, dict):
                        parsed["_llm_meta"] = llm_meta
                    return parsed
                except json.JSONDecodeError:
                    pass
        # Fallback : retourner un dict d'erreur plutôt que planter
        return {
            "summary": "Analyse partielle — réponse LLM tronquée",
            "pickup_rate_comment": "",
            "overflow_comment": "",
            "quality_flags": [],
            "kb_gaps": {"missing": [], "to_revise": []},
            "recommendations": ["Relancer l'analyse — réponse API incomplète"],
            "weekly_trend": "",
            "_parse_error": raw[:200],
            "_llm_meta": llm_meta,
        }
