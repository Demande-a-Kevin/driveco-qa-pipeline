"""csat_prompting.py — Prompt Gemma contraint + parsing du verdict CSAT."""
from __future__ import annotations
from dataclasses import dataclass
import config
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
    data = ollama_client.generate_json(
        build_prompt(transcript, score, influence, improvements),
        timeout=config.OLLAMA_ANALYSIS_TIMEOUT,  # éviter un timeout 60s si le modèle est occupé par le batch QA
    )
    return Insight(
        verdict=_normalize_verdict(data.get("verdict")),
        sentiment=_normalize_sentiment(data.get("sentiment")),
        synthese=_truncate_words(data.get("synthese"), 55),
    )
