from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import rubric
import voc_taxonomy


_BASE_DIR = Path(__file__).resolve().parent
_PROMPTS_DIR = _BASE_DIR / "prompts"
_EXAMPLES_DIR = _PROMPTS_DIR / "examples"
_VOC_EXAMPLES_DIR = _EXAMPLES_DIR / "voc"

# Override runtime injecté par analysis_pipeline via set_effective_base_prompt().
# Si None → fallback sur system_prompt.txt (rétrocompat tests / usages directs).
_EFFECTIVE_BASE_PROMPT: str | None = None

# B-γ : focus note one-shot injecté par analysis_pipeline au boot.
_EFFECTIVE_FOCUS_NOTE: Optional[str] = None


def set_effective_base_prompt(text: str | None) -> None:
    """Override le prompt système baseline (utilisé par runtime_config).

    Passer None pour revenir au fichier `system_prompt.txt`.
    """
    global _EFFECTIVE_BASE_PROMPT
    _EFFECTIVE_BASE_PROMPT = text


def set_effective_focus_note(note: Optional[str]) -> None:
    """B-γ : focus note one-shot injecté par analysis_pipeline au boot.

    None ou '' = pas d'override (fallback comportement existant).
    """
    global _EFFECTIVE_FOCUS_NOTE
    _EFFECTIVE_FOCUS_NOTE = note.strip() if note else None


def get_active_focus_note() -> Optional[str]:
    return _EFFECTIVE_FOCUS_NOTE


def load_base_system_prompt() -> str:
    if _EFFECTIVE_BASE_PROMPT is not None:
        return _EFFECTIVE_BASE_PROMPT.strip()
    return (_BASE_DIR / "system_prompt.txt").read_text(encoding="utf-8").strip()


def load_voc_system_prompt() -> str:
    return (_PROMPTS_DIR / "voc_system.txt").read_text(encoding="utf-8").strip()


def load_scoring_examples() -> list[dict]:
    examples = []
    for path in sorted(_EXAMPLES_DIR.glob("qa_*.json")):
        examples.append(json.loads(path.read_text(encoding="utf-8")))
    return examples


def load_voc_examples() -> list[dict]:
    examples = []
    for path in sorted(_VOC_EXAMPLES_DIR.glob("*.json")):
        examples.append(json.loads(path.read_text(encoding="utf-8")))
    return examples


def build_call_payload(call: dict) -> dict:
    payload = {
        "call_id": str(call.get("call_id_internal") or call.get("call_id") or ""),
        "classified_type": call.get("classified_type"),
        "duration_seconds": call.get("duration_in_call") or 0,
        "wait_seconds": call.get("waiting_time") or 0,
        "agent": call.get("user_name") or None,
        "ivr_branch": call.get("ivr_branch") or None,
        "tags": call.get("tags") or None,
        "answered": call.get("answered") or None,
        "transcript": call.get("transcript") or "",
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def build_extraction_messages(call: dict, kb_summary: str) -> list[dict]:
    payload = build_call_payload(call)
    system_prompt = load_base_system_prompt()
    schema_hint = {
        "call_id": "string",
        "classified_type": "string",
        "customer_call_reason": "string|null",
        "transcript_usable": "boolean",
        "kb_compliance": {
            "status": "conforme|partiel|non_conforme",
            "article": "string|null",
            "rationale": "string|null",
        },
        "positives": [{"text": "string", "citation": "string <=160", "kb_reference": "string|null"}],
        "improvement_points": [{"text": "string", "citation": "string <=160", "kb_reference": "string|null"}],
        "alerts": [{"level": "critical|warning|info", "message": "string", "call_ids": ["string"]}],
        "procedural_steps_followed": ["string"],
        "emotional_signals": ["string"],
        "resolution_status": "resolved|escalated|pending|unresolved|callback_scheduled",
        "unanswered_questions": ["string"],
    }
    user_prompt = (
        "Tâche: extraction factuelle uniquement. Pas de scoring.\n"
        "Règles:\n"
        "- Ne juge pas l'agent globalement.\n"
        "- Chaque positive et chaque improvement_point doit avoir une citation exacte du transcript.\n"
        "- customer_call_reason doit être courte et lisible.\n"
        "- resolution_status doit refléter uniquement l'issue explicite de l'appel.\n"
        "- Si le transcript n'est pas exploitable, mets transcript_usable=false et laisse les listes vides si besoin.\n"
        "- unanswered_questions : liste les questions du client auxquelles l'agent n'a PAS su répondre correctement.\n"
        "  Inclure : agent admet ne pas savoir, donne une info vague ou incorrecte, élude la question.\n"
        "  Exclure : questions répondues correctement, chitchat, demandes traitées (rappel programmé, transfert effectué).\n"
        "  Format : 1 phrase en français à la 3e personne, reformulation concise (ex: \"Le client demande si X est compatible avec Y\").\n"
        "  Mets [] si aucune question reste sans réponse.\n"
        "- Réponds uniquement avec un JSON conforme.\n\n"
        f"Rubric context:\n{rubric.build_rubric_prompt_block()}\n\n"
        f"Knowledge base:\n{kb_summary}\n\n"
        f"Call payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"Schema attendu:\n{json.dumps(schema_hint, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_scoring_messages(call: dict, factual_extract: dict) -> list[dict]:
    payload = {
        "call_id": str(call.get("call_id_internal") or call.get("call_id") or ""),
        "classified_type": call.get("classified_type"),
        "duration_seconds": call.get("duration_in_call") or 0,
        "agent": call.get("user_name") or None,
    }
    system_prompt = load_base_system_prompt()
    schema_hint = {
        "accueil": "number|null 0-10",
        "ecoute_active": "number|null 0-10",
        "empathie": "number|null 0-10",
        "gestion_tension": "number|null 0-10",
        "professionnalisme": "number|null 0-10",
        "clarte_communication": "number|null 0-10",
        "orientation_solution": "number|null 0-10",
        "cloture": "number|null 0-10",
        "qualification_investigation": "number|null 0-10",
        "kb_application": "number|null 0-10",
        "observations": "string",
    }
    messages = [{"role": "system", "content": system_prompt}]
    for example in load_scoring_examples():
        messages.append(
            {
                "role": "user",
                "content": (
                    "Exemple calibrage scoring.\n"
                    f"Rubric:\n{rubric.build_rubric_prompt_block()}\n"
                    f"Données:\n{json.dumps(example['request'], ensure_ascii=False, indent=2)}"
                ),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(example["response"], ensure_ascii=False, indent=2),
            }
        )

    messages.append(
        {
            "role": "user",
            "content": (
                "Tâche: scoring uniquement à partir de l'extraction fournie.\n"
                "Règles:\n"
                "- Note chaque critère entre 0 et 10.\n"
                "- Mets null seulement si le critère est réellement inobservable.\n"
                "- N'ajoute aucun champ hors schéma.\n"
                "- La note globale sera calculée côté Python, donc ne la retourne pas.\n"
                "- Réponds uniquement avec un JSON conforme.\n\n"
                f"Rubric:\n{rubric.build_rubric_prompt_block()}\n\n"
                f"Call metadata:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                f"Factual extract:\n{json.dumps(factual_extract, ensure_ascii=False, indent=2)}\n\n"
                f"Schema attendu:\n{json.dumps(schema_hint, ensure_ascii=False, indent=2)}"
            ),
        }
    )
    return messages


def build_voc_messages(call: dict, score_global: float | None = None) -> list[dict]:
    payload = build_call_payload(call)
    if score_global is not None:
        payload["qa_score_global"] = round(float(score_global), 1)
    schema_hint = {
        "topics": [
            {
                "topic_code": "string",
                "product_area": "app|hardware|billing|api|installation|support|other",
                "sentiment": "très_négatif|négatif|neutre|positif|très_positif",
                "severity": "1-5",
                "quote": "string <=240",
                "needs_taxonomy_review": "bool",
            }
        ],
        "entity_perceptions": [
            {
                "entity_code": "string",
                "aspect_code": "string",
                "sentiment": "très_négatif|négatif|neutre|positif|très_positif",
                "quote": "string <=240",
                "needs_taxonomy_review": "bool",
            }
        ],
        "customer_emotions": ["frustration|colère|résignation|soulagement|satisfaction|confusion|inquiétude"],
        "effort_score": "1|2|3|4|5",
        "satisfaction_signal": "positif|neutre|négatif|mixte",
        "churn_risk_signal": "aucun|faible|modéré|élevé",
        "expansion_signal": "boolean",
        "resolution_status": "resolved|escalated|pending|unresolved|callback_scheduled",
        "competitor_mentions": [
            {"competitor_name": "string", "context_quote": "string <=240", "sentiment": "très_négatif|négatif|neutre|positif|très_positif"}
        ],
        "verbatim_quotes": [
            {"quote": "string <=240", "timestamp_s": "int|null", "speaker": "string|null", "topic_code": "string|null", "sentiment": "enum|null"}
        ],
        "best_practice_moments": [
            {"quote": "string <=240", "timestamp_s": "int|null", "speaker": "string|null", "topic_code": "string|null", "sentiment": "enum|null"}
        ],
        "unmet_needs": ["string"],
        "product_ideas": ["string"],
        "taxonomy_version": voc_taxonomy.taxonomy_version(),
        "needs_taxonomy_review": "boolean",
        "validation_warnings": ["string"],
    }
    messages = [{"role": "system", "content": load_voc_system_prompt()}]
    for example in load_voc_examples():
        messages.append(
            {
                "role": "user",
                "content": (
                    "Exemple calibrage VoC.\n"
                    f"Taxonomie:\n{voc_taxonomy.taxonomy_prompt_block()}\n"
                    f"Données:\n{json.dumps(example['request'], ensure_ascii=False, indent=2)}"
                ),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(example["response"], ensure_ascii=False, indent=2),
            }
        )

    messages.append(
        {
            "role": "user",
            "content": (
                "Tâche: extraction VoC uniquement.\n"
                "Règles:\n"
                "- N'évalue pas l'agent.\n"
                "- Chaque topic, entity_perception, competitor mention et verbatim doit contenir une quote retrouvable dans le transcript.\n"
                "- Utilise uniquement la taxonomie fournie. Si besoin, utilise autre_<texte_court> et needs_taxonomy_review=true.\n"
                "- Limite verbatim_quotes à 5.\n"
                "- Identifie systématiquement les product_ideas, unmet_needs et signaux d'expansion quand ils existent.\n"
                "- Si le client exprime un compliment, un remerciement ou un soulagement, satisfaction_signal doit refléter ce positif avec verbatim.\n"
                "- best_practice_moments doit rester vide sauf si l'échange montre clairement une excellence méthodologique de l'agent.\n"
                "- Réponds uniquement avec un JSON conforme.\n\n"
                f"Taxonomie:\n{voc_taxonomy.taxonomy_prompt_block()}\n\n"
                f"Call payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                f"Schema attendu:\n{json.dumps(schema_hint, ensure_ascii=False, indent=2)}"
            ),
        }
    )
    return messages


def build_retry_message(error_text: str, schema: dict, invalid_fields: list[str] | None = None) -> str:
    fields_block = ""
    if invalid_fields:
        fields_block = "Champs en violation:\n" + "\n".join(f"- {field}" for field in invalid_fields[:12]) + "\n\n"
    return (
        "Le JSON précédent est invalide.\n"
        f"Erreurs de validation:\n{error_text}\n\n"
        f"{fields_block}"
        "Contraintes strictes :\n"
        "- citation <= 160 caractères\n"
        "- rationale <= 240 caractères\n"
        "- text <= 240 caractères\n"
        "- si un champ est trop long, tronque-le proprement\n\n"
        "Renvoie uniquement un JSON corrigé, sans commentaire, conforme à ce schéma:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )
