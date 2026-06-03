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
