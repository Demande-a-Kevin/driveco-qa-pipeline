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
    station: str = ""


def _facts_block(facts: dict | None) -> str:
    if not facts:
        return "Faits Aircall : non disponibles."
    parts = []
    if facts.get("answered"):
        tta = facts.get("time_to_answer_s")
        wait = f" après {tta}s d'attente" if tta is not None else ""
        parts.append(f"appel décroché par un agent{wait}")
    else:
        parts.append("appel NON décroché (personne n'a répondu)")
    dur = facts.get("duration_s")
    if dur:
        parts.append(f"durée {int(dur)}s")
    if facts.get("direction"):
        parts.append(f"sens {facts['direction']}")
    if facts.get("agent_name"):
        parts.append(f"agent {facts['agent_name']}")
    return "Faits Aircall : " + ", ".join(parts) + "."


def build_prompt(transcript: str, score: int | None, influence: str, improvements: str,
                 facts: dict | None = None) -> str:
    score_txt = f"{score}/5" if score is not None else "inconnue"
    return f"""Tu analyses un appel d'assistance Driveco (recharge de véhicules électriques).
Le client a donné une note CSAT de {score_txt}.
Réponses du client au sondage — influence: "{influence}" ; améliorations: "{improvements}".
{_facts_block(facts)}

Transcript de l'appel :
\"\"\"
{transcript}
\"\"\"

Explique en UNE seule fois pourquoi cette note, et de quel côté vient le motif dominant.
Tiens compte des faits Aircall (attente avant décrochage, appel réellement décroché ou non par un agent) s'ils éclairent la note.
Réponds STRICTEMENT en JSON : {{"verdict": "...", "sentiment": "...", "station": "...", "synthese": "..."}}
- "verdict" parmi exactement : "Agent/Assistance", "Borne/App", "Mixte", "Autre".
  Tranche un côté dominant ; n'utilise "Mixte" que si les deux pèsent vraiment à parts égales.
- "sentiment" parmi exactement : "positif", "négatif", "mitigé".
- "station" : la station/borne/lieu de recharge explicitement cité par le client (dans l'appel OU le sondage), ex. "Carrefour Rives-sur-Fure, borne n°4". Chaîne VIDE si non mentionné — n'invente jamais.
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


def _clean_station(value: str) -> str:
    """Station citée par le client : nettoie, tronque, vide si non pertinent."""
    s = " ".join(str(value or "").split())
    if s.lower() in {"", "non mentionné", "non mentionnée", "inconnu", "inconnue", "n/a", "none", "null"}:
        return ""
    return " ".join(s.split()[:12])


def analyze(transcript: str, score: int | None, influence: str, improvements: str,
            facts: dict | None = None) -> Insight:
    data = ollama_client.generate_json(
        build_prompt(transcript, score, influence, improvements, facts),
        timeout=config.OLLAMA_ANALYSIS_TIMEOUT,  # éviter un timeout 60s si le modèle est occupé par le batch QA
    )
    return Insight(
        verdict=_normalize_verdict(data.get("verdict")),
        sentiment=_normalize_sentiment(data.get("sentiment")),
        synthese=_truncate_words(data.get("synthese"), 55),
        station=_clean_station(data.get("station")),
    )
