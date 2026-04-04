"""
analysis_pipeline.py — Orchestrateur principal du pipeline QA Driveco.

Routing LLM :
  Ollama (local, llama3.1:8b) → pre-screening + batch analyse des appels à risque moyen
  Claude Haiku                → daily consolidation + re-évaluation des appels très problématiques
  Claude Sonnet               → rapport hebdomadaire (consolidation + tendances)

Usage :
  python analysis_pipeline.py --mode daily [--date 2026-03-24]
  python analysis_pipeline.py --mode weekly [--date 2026-03-24]
  python analysis_pipeline.py --mode test   # test de connectivité
"""
import os
import json
import argparse
import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

def _write_bootstrap_log() -> None:
    """Trace le tout début du script pour distinguer un blocage avant/après imports internes."""
    try:
        log_dir = Path(__file__).parent / "qa-driveco-data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "bootstrap.log").open("a", encoding="utf-8") as fh:
            fh.write(
                f"{datetime.now().isoformat()} [bootstrap] pid={os.getpid()} script_start analysis_pipeline.py\n"
            )
    except Exception:
        pass

_write_bootstrap_log()

import call_fetcher
import call_classifier
import metrics_builder
import notion_kb_fetcher
import llm_client
import ollama_client
import report_formatter
import notifier
import d1_client
import config

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Charge le system prompt depuis le fichier texte
SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")

# Tailles de batch
BATCH_SIZE      = config.ANALYSIS_BATCH_SIZE_TX   # 5 — batch avec transcripts
BATCH_SIZE_META = config.ANALYSIS_BATCH_SIZE       # 10 — batch metadata only (Haiku)
OLLAMA_BATCH_SIZE = 5  # Batch Ollama plus petit pour éviter les timeouts
KB_EXCERPT_MAX_CHARS = 5000
KB_EXCERPT_MAX_PAGES = 4
CLAUDE_BATCH_MAX_TOKENS = 900
CLAUDE_HIGH_RISK_MAX_TOKENS = 1200
CLAUDE_CONSOLIDATION_MAX_TOKENS = 900
ENABLE_CLAUDE_LOW_RISK_FALLBACK = False
ENABLE_CLAUDE_MEDIUM_RISK_FALLBACK = False
ENABLE_CLAUDE_GLOBAL_FALLBACK = False


# ── Filtrage et sélection des appels ─────────────────────────────────────────

def select_calls_for_analysis(calls: list[dict], coverage_pct: float = None) -> list[dict]:
    """
    Sélectionne coverage_pct% des appels UCC pour analyse LLM.
    Stratégie : escalades > abandons > courts > longs.
    Exclut les appels répondus de moins de 60s (menus IVR, erreurs, raccroché immédiat).
    """
    if coverage_pct is None:
        coverage_pct = config.ANALYSIS_COVERAGE_PCT

    # Filtre durée : on exclut les appels répondus < 60s (trop courts pour être analysables)
    eligible = [c for c in calls
                if not (c.get("answered") == "Yes" and (c.get("duration_in_call") or 0) < 60)]
    n_excluded = len(calls) - len(eligible)
    if n_excluded:
        log.info(f"  Filtre durée < 60s : {n_excluded} appels exclus ({len(eligible)} éligibles)")

    target_n = max(1, int(len(eligible) * coverage_pct))

    escalations = [c for c in eligible if "escalation" in (c.get("tags") or "").lower()]
    abandoned   = [c for c in eligible if c.get("answered") == "No"]
    short       = [c for c in eligible
                   if c.get("answered") == "Yes"
                   and (c.get("duration_in_call") or 0) < 90
                   and c not in escalations]
    long_calls  = sorted(
        [c for c in eligible if c.get("answered") == "Yes" and c not in escalations and c not in short],
        key=lambda x: x.get("duration_in_call") or 0,
        reverse=True,
    )

    ordered = escalations + abandoned + short + long_calls
    seen, unique = set(), []
    for c in ordered:
        cid = c.get("call_id_internal") or c.get("call_id")
        if cid not in seen:
            seen.add(cid)
            unique.append(c)

    selected = unique[:target_n]
    log.info(f"  Sélection analyse : {len(selected)}/{len(eligible)} appels ({coverage_pct*100:.0f}%) "
             f"[escalades={len(escalations)} abandons={len(abandoned)} courts={len(short)} longs={len(long_calls)}]")
    return selected


def score_call_problematic(ev: dict) -> int:
    """Score de sévérité d'un appel évalué — plus c'est haut, plus c'est problématique."""
    if not isinstance(ev, dict):
        return 0
    score = 0
    for alert in _iter_issue_items(ev.get("alerts")):
        if isinstance(alert, dict):
            score += 3 if alert.get("level") == "critical" else 1
        elif _normalize_issue_text(alert):
            score += 1
    score += len(ev.get("errors", [])) * 2
    if ev.get("kb_compliance") == "non_conforme":
        score += 2
    elif ev.get("kb_compliance") == "partiel":
        score += 1
    ss = ev.get("soft_skills") or {}
    note = ss.get("note_globale")
    if note is not None:
        try:
            score += max(0, int((5 - float(note)) * 0.8))
        except (TypeError, ValueError):
            pass
    return score


def get_top_problematic(evaluations: list[dict], n: int = None) -> list[dict]:
    """Retourne les N appels les plus problématiques triés par score décroissant."""
    if n is None:
        n = config.TOP_PROBLEMATIC_CALLS
    scored = [(ev, score_call_problematic(ev)) for ev in evaluations if score_call_problematic(ev) > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [ev for ev, _ in scored[:n]]


def sanitize_call_evaluations(evaluations, context: str = "unknown") -> list[dict]:
    """
    Conserve uniquement les évaluations exploitables.
    Certains retours LLM partiels peuvent injecter des chaînes ou structures invalides.
    """
    cleaned: list[dict] = []
    dropped = 0
    for item in evaluations or []:
        if isinstance(item, dict):
            cleaned.append(item)
        else:
            dropped += 1
    if dropped:
        log.warning(f"  [sanitizer] {dropped} évaluation(s) invalide(s) ignorée(s) ({context})")
    return cleaned


def init_llm_usage_stats() -> dict:
    return {
        "anthropic_calls": 0,
        "anthropic_input_tokens": 0,
        "anthropic_output_tokens": 0,
        "contexts": {},
    }


def track_llm_usage(stats: dict, result: dict, context: str) -> None:
    if not stats or not isinstance(result, dict):
        return
    meta = result.get("_llm_meta") or {}
    stats["anthropic_calls"] += 1
    input_tokens = meta.get("input_tokens")
    output_tokens = meta.get("output_tokens")
    if isinstance(input_tokens, int) and input_tokens > 0:
        stats["anthropic_input_tokens"] += input_tokens
    if isinstance(output_tokens, int) and output_tokens > 0:
        stats["anthropic_output_tokens"] += output_tokens
    context_row = stats["contexts"].setdefault(
        context,
        {"calls": 0, "input_tokens": 0, "output_tokens": 0},
    )
    context_row["calls"] += 1
    if isinstance(input_tokens, int) and input_tokens > 0:
        context_row["input_tokens"] += input_tokens
    if isinstance(output_tokens, int) and output_tokens > 0:
        context_row["output_tokens"] += output_tokens


def safe_llm_analyze(system_prompt: str, user_prompt: str, model: str, max_tokens: int, context: str,
                     usage_stats: dict | None = None) -> dict:
    """
    Wrapper défensif autour de llm_client.analyze pour ne pas bloquer tout le pipeline
    si Anthropic refuse une requête ou si un fallback externe échoue.
    """
    try:
        result = llm_client.analyze(system_prompt, user_prompt, model=model, max_tokens=max_tokens)
        track_llm_usage(usage_stats, result, context)
        return result
    except Exception as exc:
        log.warning(f"  [llm-fallback] Échec {context} ({model}) : {exc}")
        return {}


def _normalize_issue_text(value) -> str:
    """Humanise un item d'erreur/alerte pour éviter les dicts bruts dans les prompts et rapports."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("description", "message", "issue", "title", "observed_gap", "missing_section"):
            candidate = value.get(key)
            if candidate:
                return _normalize_issue_text(candidate)
        if value.get("error_code"):
            return str(value["error_code"]).strip()
    if isinstance(value, list):
        parts = [_normalize_issue_text(item) for item in value]
        return " | ".join([part for part in parts if part])
    text = str(value).strip()
    return " ".join(text.split())


def _iter_issue_items(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def build_consolidation_summary(metrics: dict, evaluations: list[dict], top_problematic: list[dict]) -> dict:
    """
    Résume les évaluations individuelles en structure compacte.
    Objectif : réduire fortement les tokens d'entrée envoyés à Claude en consolidation.
    """
    kb_counter = Counter()
    type_counter = Counter()
    model_counter = Counter()
    error_counter = Counter()
    alert_counter = Counter()
    positive_counter = Counter()
    customer_reason_counter = Counter()
    error_examples: dict[str, list[str]] = {}
    alert_examples: dict[str, list[str]] = {}
    soft_notes = []
    transcript_usable = 0

    for ev in evaluations:
        call_id = ev.get("call_id")
        classified_type = ev.get("classified_type") or "unknown"
        kb_status = ev.get("kb_compliance") or "unknown"
        model_used = ev.get("_model") or "claude"

        kb_counter[kb_status] += 1
        type_counter[classified_type] += 1
        model_counter[model_used] += 1

        soft_note = (ev.get("soft_skills") or {}).get("note_globale")
        if soft_note is not None:
            try:
                soft_notes.append(float(soft_note))
                transcript_usable += 1
            except (TypeError, ValueError):
                pass

        customer_reason = _normalize_issue_text(ev.get("customer_call_reason"))
        if customer_reason:
            customer_reason_counter[customer_reason] += 1

        for item in _iter_issue_items(ev.get("errors")):
            text = _normalize_issue_text(item)
            if not text:
                continue
            error_counter[text] += 1
            if call_id:
                examples = error_examples.setdefault(text, [])
                if call_id not in examples and len(examples) < 3:
                    examples.append(call_id)

        for item in _iter_issue_items(ev.get("alerts")):
            if isinstance(item, dict):
                text = _normalize_issue_text(item.get("message"))
            else:
                text = _normalize_issue_text(item)
            if not text:
                continue
            alert_counter[text] += 1
            if call_id:
                examples = alert_examples.setdefault(text, [])
                if call_id not in examples and len(examples) < 3:
                    examples.append(call_id)

        for item in _iter_issue_items(ev.get("positives")):
            text = _normalize_issue_text(item)
            if text:
                positive_counter[text] += 1

    top_problematic_compact = []
    for ev in top_problematic[:8]:
        top_problematic_compact.append({
            "call_id": ev.get("call_id"),
            "type": ev.get("classified_type"),
            "score_problematic": score_call_problematic(ev),
            "kb_compliance": ev.get("kb_compliance"),
            "top_error": _normalize_issue_text((_iter_issue_items(ev.get("errors")) or [None])[0]),
            "top_alert": _normalize_issue_text(
                ((_iter_issue_items(ev.get("alerts")) or [None])[0] or {}).get("message")
                if isinstance((_iter_issue_items(ev.get("alerts")) or [None])[0], dict)
                else (_iter_issue_items(ev.get("alerts")) or [None])[0]
            ),
            "soft_skills_note": (ev.get("soft_skills") or {}).get("note_globale"),
        })

    def _counter_to_rows(counter: Counter, examples: dict[str, list[str]] | None = None, limit: int = 12) -> list[dict]:
        rows = []
        for text, count in counter.most_common(limit):
            row = {"label": text, "count": count}
            if examples is not None and text in examples:
                row["example_call_ids"] = examples[text]
            rows.append(row)
        return rows

    return {
        "analysis_volume": {
            "evaluated_calls": len(evaluations),
            "transcript_usable_calls": transcript_usable,
            "transcript_usable_rate_pct": round((transcript_usable / len(evaluations) * 100), 1) if evaluations else 0.0,
        },
        "kpis": metrics,
        "classified_type_distribution": dict(type_counter),
        "kb_compliance_distribution": dict(kb_counter),
        "models_used": dict(model_counter),
        "soft_skills_average_note": round(sum(soft_notes) / len(soft_notes), 1) if soft_notes else None,
        "top_errors": _counter_to_rows(error_counter, error_examples),
        "top_alerts": _counter_to_rows(alert_counter, alert_examples, limit=8),
        "top_positive_signals": _counter_to_rows(positive_counter, limit=8),
        "top_customer_reasons": _counter_to_rows(customer_reason_counter, limit=8),
        "top_problematic_calls": top_problematic_compact,
    }


def _build_fallback_kb_gaps(summary: dict) -> tuple[dict, list[str]]:
    top_reasons = summary.get("top_customer_reasons", []) or []
    top_errors = summary.get("top_errors", []) or []

    missing = []
    to_revise = []
    recommendations = []

    for item in top_reasons[:2]:
        label = _normalize_issue_text(item.get("label"))
        count = int(item.get("count") or 0)
        if not label:
            continue
        missing.append({
            "title": f"Guide à renforcer : {label}",
            "description": f"Sujet revenu {count} fois dans les transcripts analysés ; ajouter un mode opératoire simple et actionnable.",
        })
        recommendations.append(f"KB : renforcer un guide opérationnel sur '{label}'.")

    for item in top_errors[:2]:
        label = _normalize_issue_text(item.get("label"))
        count = int(item.get("count") or 0)
        if not label:
            continue
        to_revise.append({
            "article": "Procédures assistance Driveco",
            "observed_gap": f"{label} — vu {count} fois dans l'échantillon QA ; clarifier les étapes et les points de contrôle.",
        })
        recommendations.append(f"KB : réviser la procédure liée à '{label}'.")

    kb_gaps = {
        "missing": missing[:2],
        "incomplete": [],
        "to_revise": to_revise[:2],
    }
    return kb_gaps, recommendations[:4]


def build_fallback_consolidation(metrics: dict, summary: dict) -> dict:
    """
    Consolidation de secours si Claude renvoie un JSON incomplet.
    On privilégie un résultat imparfait mais exploitable plutôt qu'un rapport vide.
    """
    volume = summary.get("analysis_volume", {})
    evaluated_calls = max(1, int(volume.get("evaluated_calls") or 0))
    transcript_usable_calls = int(volume.get("transcript_usable_calls") or 0)
    kb_dist = summary.get("kb_compliance_distribution", {})
    top_errors = summary.get("top_errors", [])
    top_alerts = summary.get("top_alerts", [])
    top_positive = summary.get("top_positive_signals", [])
    avg_soft_note = summary.get("soft_skills_average_note")
    fallback_kb_gaps, kb_recommendations = _build_fallback_kb_gaps(summary)

    conformes = int(kb_dist.get("conforme") or 0)
    partiels = int(kb_dist.get("partiel") or 0)
    non_conformes = int(kb_dist.get("non_conforme") or 0)
    kb_score = ((conformes + 0.5 * partiels) / evaluated_calls) * 10
    soft_score = float(avg_soft_note) if avg_soft_note is not None else 5.5
    abandon_penalty = min(3.0, float(metrics.get("abandon_rate_pct", 0)) / 15.0)
    non_conformity_penalty = min(3.0, (non_conformes / evaluated_calls) * 5.0)
    score_low_confidence = transcript_usable_calls <= 0 or avg_soft_note is None
    if score_low_confidence:
        ucc_quality_score = None
        ucc_score_justification = (
            "n/a — score QA non fiable sur ce run : aucun transcript exploitable ou matière soft skills insuffisante."
        )
    else:
        ucc_quality_score = round(
            max(0.0, min(10.0, (0.45 * kb_score) + (0.55 * soft_score) - abandon_penalty - non_conformity_penalty)),
            1,
        )
        ucc_score_justification = (
            f"Score de secours basé sur KB ({conformes} conformes / {partiels} partiels / {non_conformes} non conformes) "
            f"et soft skills moyennes ({soft_score}/10)."
        )

    fallback_alerts = list(metrics.get("alerts", []))
    for item in top_alerts[:3]:
        label = item.get("label")
        if not label:
            continue
        fallback_alerts.append({
            "level": "warning",
            "message": f"{label} — {item.get('count', 0)} occurrence(s) dans l'échantillon QA",
            "call_ids": item.get("example_call_ids", []),
        })

    return {
        "kpis": metrics,
        "scores": {
            "ucc_quality_score": ucc_quality_score,
            "driveco_care_score": None,
            "ucc_score_justification": ucc_score_justification,
            "driveco_score_justification": "n/a — consolidation de secours sans volumétrie dédiée Driveco Care",
        },
        "top_issues": [
            {
                "issue": item.get("label"),
                "occurrences": item.get("count", 0),
                "example_call_ids": item.get("example_call_ids", []),
            }
            for item in top_errors[:5]
            if item.get("label")
        ],
        "good_practices": [item.get("label") for item in top_positive[:4] if item.get("label")],
        "alerts": fallback_alerts,
        "kb_gaps": fallback_kb_gaps,
        "recommendations": [
            f"Priorité coaching : {top_errors[0]['label']}" for _ in [0] if top_errors and top_errors[0].get("label")
        ] + kb_recommendations + [
            "Vérifier la stabilité du JSON de consolidation API pour éviter les rapports dégradés."
        ],
        "weekly_trend": None,
    }


# ── Pre-screening Ollama ──────────────────────────────────────────────────────

def run_prescreening(calls: list[dict]) -> dict[str, tuple[float, str]]:
    """
    Pre-screening de tous les appels via Ollama (ou heuristique si Ollama indisponible).
    Retourne {call_id: (risk_score, reason)} pour chaque appel.
    """
    scores = {}
    ollama_up = ollama_client.is_available()
    if not ollama_up:
        log.info("  [prescreening] Ollama non disponible — scoring heuristique pour tous les appels")

    for call in calls:
        cid = call.get("call_id_internal") or call.get("call_id")
        risk, reason = ollama_client.pre_screen_call(call)
        scores[cid] = (risk, reason)
        call["_risk_score"] = risk  # Annote le call pour usage ultérieur

    n_high   = sum(1 for r, _ in scores.values() if r >= config.HAIKU_REEVAL_THRESHOLD)
    n_medium = sum(1 for r, _ in scores.values() if config.OLLAMA_RISK_THRESHOLD <= r < config.HAIKU_REEVAL_THRESHOLD)
    n_low    = sum(1 for r, _ in scores.values() if r < config.OLLAMA_RISK_THRESHOLD)
    log.info(f"  [prescreening] Résultats : {n_low} faible / {n_medium} moyen / {n_high} élevé "
             f"(seuils : {config.OLLAMA_RISK_THRESHOLD:.1f} / {config.HAIKU_REEVAL_THRESHOLD:.1f})")

    return scores


# ── Builders de prompts ───────────────────────────────────────────────────────

def _build_call_entry(call: dict, transcript_max_chars: int = 900) -> dict:
    """Construit le dict compact d'un appel pour le prompt LLM."""
    entry = {
        "call_id": call.get("call_id_internal") or call.get("call_id"),
        "type": call.get("classified_type"),
        "duration_s": call.get("duration_in_call"),
        "wait_s": call.get("waiting_time"),
        "agent": call.get("user_name"),
        "ivr": call.get("ivr_branch"),
    }
    entry = {k: v for k, v in entry.items() if v is not None and v != ""}
    if call.get("answered") == "No":
        entry["missed"] = call.get("missed_call_reason") or "abandoned"
    if call.get("tags"):
        entry["tags"] = call["tags"]
    t = (call.get("transcript") or "")[:transcript_max_chars]
    if t:
        entry["transcript"] = t
    return entry


def build_batch_prompt(date: datetime, batch_calls: list[dict], kb_summary: str,
                       batch_num: int, total_batches: int) -> str:
    """Prompt pour évaluer un batch de N appels (avec transcripts et soft skills)."""
    calls_block = [_build_call_entry(c) for c in batch_calls]
    return f"""MODE : BATCH {batch_num}/{total_batches}
DATE : {date.strftime('%d/%m/%Y')}

=== KNOWLEDGE BASE ===
{kb_summary}

=== APPELS À ÉVALUER ({len(calls_block)}) ===
{json.dumps(calls_block, indent=2, ensure_ascii=False)}

Évalue chaque appel individuellement :
- kb_article_applicable, kb_compliance (conforme|partiel|non_conforme)
- customer_call_reason : raison principale de l'appel en 3 à 8 mots maximum, basée sur le transcript uniquement ; null si non déterminable sans transcript
- positives : ce que l'agent a bien fait
- errors : erreurs de procédure ou omissions
- alerts : si problème grave (transfert sans brief, etc.)
- soft_skills : politesse/empathie/professionnalisme/clarte/gestion_tension (0-10, null si pas de transcript)

Réponds UNIQUEMENT avec le JSON, champ "call_evaluations" uniquement :
{{"call_evaluations": [...]}}
"""


def get_batch_kb_excerpt(batch_calls: list[dict]) -> str:
    """Construit l'extrait KB pertinent pour un batch d'appels."""
    excerpt = notion_kb_fetcher.build_relevant_kb_excerpt(
        batch_calls,
        max_chars=KB_EXCERPT_MAX_CHARS,
        max_pages=KB_EXCERPT_MAX_PAGES,
    )
    log.info(
        f"  [kb] batch {len(batch_calls)} appels -> extrait {len(excerpt)} chars"
    )
    return excerpt


def build_consolidation_prompt(date: datetime, metrics: dict, all_evaluations: list[dict],
                                kb_summary: str, mode: str = "daily") -> str:
    """Prompt de consolidation : génère scores globaux, top_issues, recommandations et kb_gaps."""
    top_problematic = get_top_problematic(all_evaluations)
    consolidation_summary = build_consolidation_summary(metrics, all_evaluations, top_problematic)
    kb_block = kb_summary[:900] if kb_summary else "(Aucun résumé KB disponible)"

    return f"""MODE : CONSOLIDATION {mode.upper()}
DATE : {date.strftime('%d/%m/%Y')}

=== KPIs CALCULÉS ===
{json.dumps(metrics, indent=2, ensure_ascii=False)}

=== KNOWLEDGE BASE ===
{kb_block}

=== SYNTHÈSE COMPACTE DES ÉVALUATIONS ({len(all_evaluations)} appels) ===
{json.dumps(consolidation_summary, indent=2, ensure_ascii=False)}

À partir de ces données, produis :
- scores : ucc_quality_score (0-10) et driveco_care_score (0-10) avec justification.
  Règle : si le volume analysé d'un périmètre est > 0, donne un score numérique, pas null.
  Si le volume est réellement nul, tu peux mettre null pour ce périmètre.
- top_issues : 5 problèmes clients les plus fréquents
- good_practices : 3-5 bonnes pratiques observées
- alerts : alertes globales (niveau critical/warning/info)
- kb_gaps : articles manquants, incomplets ou à réviser
- recommendations : 5-8 recommandations opérationnelles prioritaires

Réponds UNIQUEMENT avec le JSON (sans call_evaluations) :
{{"report_date":"{date.strftime('%Y-%m-%d')}","report_type":"{mode}","kpis":{{...}},"scores":{{...}},"top_issues":[...],"good_practices":[...],"alerts":[...],"kb_gaps":{{...}},"recommendations":[...],"weekly_trend":null}}
"""


# ── Analyse LLM par batch avec routing Ollama/Haiku ──────────────────────────

def run_batched_llm_analysis(date: datetime, metrics: dict, calls_to_analyze: list[dict],
                              kb_summary: str, consolidation_model: str,
                              mode: str = "daily") -> dict:
    """
    Analyse calls_to_analyze via routing Ollama → Haiku :

    1. Pre-screening Ollama (risk 0-10) sur tous les appels sélectionnés
    2. Appels risque faible (<= OLLAMA_RISK_THRESHOLD) : analyse Ollama batch
    3. Appels risque élevé (>= HAIKU_REEVAL_THRESHOLD) : analyse Haiku batch
    4. Appels risque moyen : Ollama si dispo, sinon Haiku
    5. Consolidation finale : consolidation_model (Haiku pour daily, Sonnet pour weekly),
       désactivable par config pour rester en local-only.
    """
    # ── Étape 1 : Pre-screening ───────────────────────────────────────────────
    log.info(f"  [routing] Pre-screening {len(calls_to_analyze)} appels via Ollama...")
    run_prescreening(calls_to_analyze)

    ollama_up = ollama_client.is_available()

    # Partition selon risk score
    low_risk    = [c for c in calls_to_analyze if c.get("_risk_score", 5) < config.OLLAMA_RISK_THRESHOLD]
    medium_risk = [c for c in calls_to_analyze
                   if config.OLLAMA_RISK_THRESHOLD <= c.get("_risk_score", 5) < config.HAIKU_REEVAL_THRESHOLD]
    high_risk   = [c for c in calls_to_analyze if c.get("_risk_score", 5) >= config.HAIKU_REEVAL_THRESHOLD]

    log.info(f"  [routing] Faible={len(low_risk)} Moyen={len(medium_risk)} Élevé={len(high_risk)}")

    all_evaluations: list[dict] = []
    llm_usage = init_llm_usage_stats()

    # ── Étape 2 : Appels à faible risque → Ollama (batch=5, timeout=240s) ────
    if low_risk:
        if ollama_up:
            log.info(f"  [Ollama] Analyse {len(low_risk)} appels risque faible (batches de {OLLAMA_BATCH_SIZE})...")
            batch_n = (len(low_risk) + OLLAMA_BATCH_SIZE - 1) // OLLAMA_BATCH_SIZE
            for i in range(0, len(low_risk), OLLAMA_BATCH_SIZE):
                batch = low_risk[i:i + OLLAMA_BATCH_SIZE]
                batch_kb_summary = get_batch_kb_excerpt(batch)
                evals = ollama_client.analyze_batch(
                    SYSTEM_PROMPT, batch, batch_kb_summary,
                    date.strftime("%d/%m/%Y"),
                    batch_num=i // OLLAMA_BATCH_SIZE + 1,
                    total_batches=batch_n,
                )
                if evals:
                    all_evaluations.extend(evals)
                    log.info(f"    → {len(evals)} évaluations Ollama (risque faible)")
                else:
                    if ENABLE_CLAUDE_LOW_RISK_FALLBACK:
                        log.info(f"    Ollama échoué → fallback Claude activé pour ce batch ({len(batch)} appels)")
                        prompt = build_batch_prompt(date, batch, batch_kb_summary, i // OLLAMA_BATCH_SIZE + 1, batch_n)
                        result = safe_llm_analyze(
                            SYSTEM_PROMPT, prompt,
                            model=llm_client.get_model_standard(), max_tokens=CLAUDE_BATCH_MAX_TOKENS,
                            context="low_risk_fallback_batch",
                            usage_stats=llm_usage,
                        )
                        all_evaluations.extend(
                            sanitize_call_evaluations(result.get("call_evaluations", []), context="low_risk_fallback")
                        )
                    else:
                        log.info(f"    Ollama échoué → batch faible ignoré pour limiter le coût token ({len(batch)} appels)")
        else:
            log.info(f"  [routing] Ollama indisponible → appels faible risque ignorés pour limiter le coût ({len(low_risk)})")

    # ── Étape 3 : Appels à risque moyen → Ollama (batch=5, timeout=240s) ─────
    if medium_risk:
        if ollama_up:
            log.info(f"  [Ollama] Analyse {len(medium_risk)} appels risque moyen (batches de {OLLAMA_BATCH_SIZE})...")
            batch_n = (len(medium_risk) + OLLAMA_BATCH_SIZE - 1) // OLLAMA_BATCH_SIZE
            for i in range(0, len(medium_risk), OLLAMA_BATCH_SIZE):
                batch = medium_risk[i:i + OLLAMA_BATCH_SIZE]
                batch_kb_summary = get_batch_kb_excerpt(batch)
                evals = ollama_client.analyze_batch(
                    SYSTEM_PROMPT, batch, batch_kb_summary,
                    date.strftime("%d/%m/%Y"),
                    batch_num=i // OLLAMA_BATCH_SIZE + 1,
                    total_batches=batch_n,
                )
                if evals:
                    all_evaluations.extend(evals)
                    log.info(f"    → {len(evals)} évaluations Ollama (risque moyen)")
                else:
                    if ENABLE_CLAUDE_MEDIUM_RISK_FALLBACK:
                        log.info(f"    Ollama échoué → fallback Claude activé pour ce batch ({len(batch)} appels)")
                        prompt = build_batch_prompt(date, batch, batch_kb_summary, i // OLLAMA_BATCH_SIZE + 1, batch_n)
                        result = safe_llm_analyze(
                            SYSTEM_PROMPT, prompt,
                            model=llm_client.get_model_standard(), max_tokens=CLAUDE_BATCH_MAX_TOKENS,
                            context="medium_risk_fallback_batch",
                            usage_stats=llm_usage,
                        )
                        all_evaluations.extend(
                            sanitize_call_evaluations(result.get("call_evaluations", []), context="medium_risk_fallback")
                        )
                    else:
                        log.info(f"    Ollama échoué → batch moyen ignoré pour limiter le coût token ({len(batch)} appels)")
        else:
            log.info(f"  [routing] Ollama indisponible → appels risque moyen ignorés pour limiter le coût ({len(medium_risk)})")

    # ── Étape 4 : Appels à haut risque → toujours Haiku ─────────────────────
    if high_risk:
        log.info(f"  [Haiku] Re-évaluation {len(high_risk)} appels haut risque (>= {config.HAIKU_REEVAL_THRESHOLD})...")
        batch_size = BATCH_SIZE if any(c.get("transcript") for c in high_risk) else BATCH_SIZE_META
        batch_n = (len(high_risk) + batch_size - 1) // batch_size
        for i in range(0, len(high_risk), batch_size):
            if i > 0:
                log.info(f"  [rate-limit] Pause 20s avant batch suivant...")
                time.sleep(20)
            batch = high_risk[i:i + batch_size]
            log.info(f"  Batch Haiku (haut risque) {i // batch_size + 1}/{batch_n} — {len(batch)} appels...")
            batch_kb_summary = get_batch_kb_excerpt(batch)
            prompt = build_batch_prompt(date, batch, batch_kb_summary, i // batch_size + 1, batch_n)
            result = safe_llm_analyze(
                SYSTEM_PROMPT, prompt,
                model=llm_client.get_model_flagged(), max_tokens=CLAUDE_HIGH_RISK_MAX_TOKENS,
                context="high_risk_haiku_batch",
                usage_stats=llm_usage,
            )
            evals = sanitize_call_evaluations(result.get("call_evaluations", []), context="high_risk_haiku")
            all_evaluations.extend(evals)
            log.info(f"    → {len(evals)} évaluations Haiku (haut risque)")

    # ── Étape 5 : Fallback Haiku garanti si 0 évaluations ────────────────────
    # Si Ollama a échoué sur tous les batches, on analyse au minimum un
    # échantillon via Haiku pour que le rapport soit utilisable.
    if not all_evaluations and calls_to_analyze:
        if ENABLE_CLAUDE_GLOBAL_FALLBACK:
            log.warning(f"  [fallback] 0 évaluation locale — fallback Claude global activé ({len(calls_to_analyze)} appels)")
            batch_n = (len(calls_to_analyze) + BATCH_SIZE - 1) // BATCH_SIZE
            for i in range(0, len(calls_to_analyze), BATCH_SIZE):
                if i > 0:
                    log.info(f"  [rate-limit] Pause 20s avant batch suivant...")
                    time.sleep(20)
                batch = calls_to_analyze[i:i + BATCH_SIZE]
                batch_kb_summary = get_batch_kb_excerpt(batch)
                prompt = build_batch_prompt(date, batch, batch_kb_summary, i // BATCH_SIZE + 1, batch_n)
                result = safe_llm_analyze(
                    SYSTEM_PROMPT, prompt,
                    model=llm_client.get_model_standard(), max_tokens=CLAUDE_BATCH_MAX_TOKENS,
                    context="global_fallback_batch",
                    usage_stats=llm_usage,
                )
                evals = sanitize_call_evaluations(result.get("call_evaluations", []), context="global_fallback")
                all_evaluations.extend(evals)
                log.info(f"    → {len(evals)} évaluations Claude (fallback)")
        else:
            log.warning("  [fallback] 0 évaluation retenue — fallback global désactivé pour limiter le coût token")

    # ── Étape 6 : Top problématiques + consolidation ──────────────────────────
    all_evaluations = sanitize_call_evaluations(all_evaluations, context="pre_consolidation")
    top_problematic = get_top_problematic(all_evaluations)
    consolidation_summary = build_consolidation_summary(metrics, all_evaluations, top_problematic)
    log.info(f"  Top {len(top_problematic)} appels problématiques identifiés")
    fallback = build_fallback_consolidation(metrics, consolidation_summary)
    if not config.ENABLE_ANTHROPIC_CONSOLIDATION:
        log.info("  [consolidation] Anthropic désactivé par config — fallback de consolidation utilisé")
        consolidated = fallback
    else:
        log.info(f"  [consolidation] {len(all_evaluations)} évaluations → {consolidation_model}...")
        consol_prompt = build_consolidation_prompt(date, metrics, all_evaluations, kb_summary, mode)
        consolidated = safe_llm_analyze(
            SYSTEM_PROMPT, consol_prompt,
            model=consolidation_model, max_tokens=CLAUDE_CONSOLIDATION_MAX_TOKENS,
            context="consolidation",
            usage_stats=llm_usage,
        )
    if not consolidated.get("scores") or not consolidated.get("top_issues"):
        log.warning("  [consolidation] Réponse incomplète — fallback de consolidation activé")
        consolidated = {
            **fallback,
            **{k: v for k, v in consolidated.items() if v},
            "scores": consolidated.get("scores") or fallback["scores"],
            "top_issues": consolidated.get("top_issues") or fallback["top_issues"],
            "good_practices": consolidated.get("good_practices") or fallback["good_practices"],
            "alerts": consolidated.get("alerts") or fallback["alerts"],
            "kb_gaps": consolidated.get("kb_gaps") or fallback["kb_gaps"],
            "recommendations": consolidated.get("recommendations") or fallback["recommendations"],
            "weekly_trend": consolidated.get("weekly_trend") or fallback["weekly_trend"],
        }

    # Modèles utilisés
    ollama_count = sum(1 for ev in all_evaluations if ev.get("_model"))
    log.info(f"  Évaluations : {ollama_count} Ollama / {len(all_evaluations) - ollama_count} Claude / 1 consolidation {consolidation_model}")
    log.info(
        "  [llm-usage] Anthropic calls=%s input_tokens=%s output_tokens=%s",
        llm_usage["anthropic_calls"],
        llm_usage["anthropic_input_tokens"],
        llm_usage["anthropic_output_tokens"],
    )

    return {
        "report_date": date.strftime("%Y-%m-%d"),
        "report_type": mode,
        "kpis": consolidated.get("kpis", metrics),
        "scores": consolidated.get("scores", {}),
        "call_evaluations": all_evaluations,
        "top_problematic_calls": top_problematic,
        "top_issues": consolidated.get("top_issues", []),
        "good_practices": consolidated.get("good_practices", []),
        "alerts": consolidated.get("alerts", []),
        "kb_gaps": consolidated.get("kb_gaps", {"missing": [], "incomplete": [], "to_revise": []}),
        "recommendations": consolidated.get("recommendations", []),
        "weekly_trend": consolidated.get("weekly_trend"),
        "llm_usage": llm_usage,
    }


# ── Sauvegarde résultats en D1 ────────────────────────────────────────────────

def save_analysis_to_d1(call_evaluations: list[dict]):
    """Persiste les évaluations individuelles dans qa_analysis."""
    for ev in call_evaluations:
        call_id = ev.get("call_id_internal") or ev.get("call_id")
        if not call_id:
            continue
        try:
            d1_client.execute(
                """
                INSERT INTO qa_analysis
                  (call_id_internal, call_id, score_global,
                   points_positifs, points_amelioration, flags, flags_count,
                   resume, model_used, analysis_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_id_internal) DO UPDATE SET
                  score_global = excluded.score_global,
                  points_positifs = excluded.points_positifs,
                  points_amelioration = excluded.points_amelioration,
                  flags = excluded.flags,
                  flags_count = excluded.flags_count,
                  resume = excluded.resume,
                  model_used = excluded.model_used,
                  analysed_at = strftime('%s','now')
                """,
                [
                    call_id,
                    ev.get("call_id"),
                    ev.get("score_global"),
                    json.dumps(ev.get("positives", []), ensure_ascii=False),
                    json.dumps(ev.get("errors", []), ensure_ascii=False),
                    json.dumps(ev.get("alerts", []), ensure_ascii=False),
                    len(ev.get("alerts", [])),
                    ev.get("kb_compliance"),
                    ev.get("_model") or llm_client.get_model_reporting(),
                    "v2",
                ],
            )
        except Exception as e:
            log.warning(f"Impossible de sauvegarder l'analyse call {call_id} en D1 : {e}")


# ── Modes d'exécution ─────────────────────────────────────────────────────────

def run_daily(target_date: datetime):
    log.info(f"=== ANALYSE QUOTIDIENNE — {target_date.strftime('%d/%m/%Y')} ===")

    # Récupération + classification de TOUS les appels du jour
    calls = call_fetcher.fetch_calls_for_date(target_date)
    log.info(f"  {len(calls)} appels récupérés")
    calls = call_classifier.classify_all(calls)

    # Métriques globales sur TOUS les appels (avant filtre UCC)
    metrics = metrics_builder.compute_metrics(calls)
    log.info(f"  KPIs globaux : décroché={metrics.get('pickup_rate_pct')}% overflow={metrics.get('overflow_rate_pct')}%")

    # Alertes immédiates (pic, repeat callers)
    for alert in metrics.get("alerts", []):
        if alert.get("level") == "critical":
            notifier.send_alert(alert["message"], level="critical")

    # Filtre UCC : on n'analyse QA que les appels pertinents (ucc_handled + ucc_transfer_handled + warm_transfer)
    ucc_calls = call_classifier.filter_ucc_calls(calls)
    log.info(f"  Appels UCC scope QA : {len(ucc_calls)}/{len(calls)}")

    if not ucc_calls:
        log.warning("  Aucun appel UCC pour ce jour — rapport minimal généré")
        analysis = {"kpis": metrics, "scores": {}, "call_evaluations": [], "top_problematic_calls": [],
                    "top_issues": [], "good_practices": [], "alerts": metrics.get("alerts", []),
                    "kb_gaps": {"missing": [], "incomplete": [], "to_revise": []}, "recommendations": []}
        report_md = report_formatter.format_daily_report(target_date, metrics, analysis)
        notifier.save_report(report_md, target_date, mode="daily")
        notifier.send_slack_notification(analysis, mode="daily", date=target_date,
                                         calls=calls, ucc_calls=ucc_calls)
        return

    # Sélection 75% des appels UCC (stratifiée)
    calls_to_analyze = select_calls_for_analysis(ucc_calls, config.ANALYSIS_COVERAGE_PCT)
    eligible_ucc_count = len([c for c in ucc_calls if not (c.get("answered") == "Yes" and (c.get("duration_in_call") or 0) < 60)])

    # Enrichissement transcripts pour les appels prioritaires
    calls_to_analyze = call_fetcher.enrich_with_transcripts(
        calls_to_analyze, max_with_transcript=config.MAX_TRANSCRIPT_CALLS
    )

    kb_summary = notion_kb_fetcher.get_kb_summary_for_prompt()

    # Analyse avec routing Ollama → Haiku, consolidation Haiku
    analysis = run_batched_llm_analysis(
        target_date, metrics, calls_to_analyze, kb_summary,
        consolidation_model=llm_client.get_model_standard(),  # Haiku
        mode="daily",
    )

    transcripts_count = sum(1 for c in calls_to_analyze if c.get("transcript"))
    analysis["analysis_meta"] = {
        "eligible_calls": eligible_ucc_count,
        "analyzed_calls": len(calls_to_analyze),
        "target_coverage_pct": round(config.ANALYSIS_COVERAGE_PCT * 100, 1),
        "actual_coverage_pct": round((len(calls_to_analyze) / max(1, eligible_ucc_count) * 100), 1),
        "transcript_calls": transcripts_count,
        "transcript_rate_pct": round((transcripts_count / max(1, len(calls_to_analyze)) * 100), 1),
        "llm_usage": analysis.get("llm_usage", {}),
    }

    save_analysis_to_d1(analysis.get("call_evaluations", []))

    report_md = report_formatter.format_daily_report(target_date, metrics, analysis)
    notifier.save_report(report_md, target_date, mode="daily")
    notifier.send_slack_notification(analysis, mode="daily", date=target_date,
                                     calls=calls, ucc_calls=ucc_calls)
    log.info("  ✅ Analyse quotidienne terminée.")


def run_weekly(end_date: datetime):
    # Force end_date au dimanche de la semaine concernée (weekday 6 = dimanche)
    # Si end_date est déjà un dimanche, pas de changement.
    # Si end_date est un lundi (weekday 0), on recule au dimanche précédent (weekday -1).
    days_since_sunday = (end_date.weekday() + 1) % 7  # 0 si dimanche, 1 si lundi, etc.
    end_date = end_date - timedelta(days=days_since_sunday)
    start_date = end_date - timedelta(days=6)  # Toujours lundi
    log.info(f"=== ANALYSE HEBDOMADAIRE — {start_date.strftime('%d/%m')} → {end_date.strftime('%d/%m/%Y')} (Lun→Dim) ===")

    # Agrégation des 7 jours
    all_calls = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        day_calls = call_fetcher.fetch_calls_for_date(day)
        for c in day_calls:
            c["day"] = day.strftime("%Y-%m-%d")
        all_calls.extend(day_calls)

    log.info(f"  {len(all_calls)} appels agrégés sur 7 jours")
    all_calls = call_classifier.classify_all(all_calls)
    metrics = metrics_builder.compute_metrics(all_calls)

    # Métriques par jour pour le rapport hebdo
    daily_metrics = {}
    for i in range(7):
        day = start_date + timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        day_calls = [c for c in all_calls if c.get("day") == day_str]
        daily_metrics[day_str] = metrics_builder.compute_metrics(day_calls) if day_calls else {}
    metrics["daily_breakdown"] = daily_metrics

    # Filtre UCC pour l'analyse QA
    ucc_calls = call_classifier.filter_ucc_calls(all_calls)
    log.info(f"  Appels UCC scope QA : {len(ucc_calls)}/{len(all_calls)}")

    # 60% de couverture pour l'hebdo (volume 7j peut être important)
    calls_to_analyze = select_calls_for_analysis(ucc_calls, coverage_pct=0.60)
    eligible_ucc_count = len([c for c in ucc_calls if not (c.get("answered") == "Yes" and (c.get("duration_in_call") or 0) < 60)])
    calls_to_analyze = call_fetcher.enrich_with_transcripts(
        calls_to_analyze, max_with_transcript=30
    )

    kb_summary = notion_kb_fetcher.get_kb_summary_for_prompt()

    # Analyse avec routing Ollama → Haiku, consolidation Sonnet (meilleure qualité pour hebdo)
    analysis = run_batched_llm_analysis(
        end_date, metrics, calls_to_analyze, kb_summary,
        consolidation_model=llm_client.get_model_reporting(),  # Sonnet
        mode="weekly",
    )

    transcripts_count = sum(1 for c in calls_to_analyze if c.get("transcript"))
    analysis["analysis_meta"] = {
        "eligible_calls": eligible_ucc_count,
        "analyzed_calls": len(calls_to_analyze),
        "target_coverage_pct": 60.0,
        "actual_coverage_pct": round((len(calls_to_analyze) / max(1, eligible_ucc_count) * 100), 1),
        "transcript_calls": transcripts_count,
        "transcript_rate_pct": round((transcripts_count / max(1, len(calls_to_analyze)) * 100), 1),
        "llm_usage": analysis.get("llm_usage", {}),
    }

    report_md = report_formatter.format_weekly_report(start_date, end_date, metrics, analysis)
    notifier.save_report(report_md, end_date, mode="weekly")
    notifier.send_slack_notification(analysis, mode="weekly", date=end_date,
                                     calls=all_calls, ucc_calls=ucc_calls)
    log.info("  ✅ Analyse hebdomadaire terminée.")


def run_test():
    """Test de connectivité vers tous les services."""
    print("\n=== TEST DE CONNECTIVITÉ ===\n")

    # D1
    try:
        ok = d1_client.health_check()
        calls_today = d1_client.fetch_call_history(
            int(__import__('datetime').datetime.now().replace(hour=0,minute=0,second=0).timestamp()),
            int(__import__('datetime').datetime.now().timestamp())
        )
        status = "opérationnel" if ok else "réponse inattendue"
        print(f"✅ D1 / Worker Cloudflare — {status} ({len(calls_today)} appels aujourd'hui)")
    except Exception as e:
        print(f"❌ D1 Cloudflare — {e}")

    # Ollama
    try:
        if ollama_client.is_available():
            # Test rapide de pre-screening
            dummy_call = {"call_type": "inbound", "answered": "No", "duration_in_call": 0, "missed_call_reason": "timeout"}
            risk, reason = ollama_client.pre_screen_call(dummy_call)
            print(f"✅ Ollama local — disponible, pre-screening OK (test: risk={risk:.1f} '{reason}')")
        else:
            print("⚠️  Ollama local — non disponible (le pipeline fonctionnera en mode Haiku-only)")
    except Exception as e:
        print(f"❌ Ollama — {e}")

    # Notion KB
    try:
        articles = notion_kb_fetcher.fetch_kb_index(force_refresh=True)
        print(f"✅ Notion KB — {len(articles)} articles indexés")
    except Exception as e:
        print(f"❌ Notion KB — {e}")

    # Notion Reports
    try:
        import requests as _req
        resp = _req.get(
            f"https://api.notion.com/v1/blocks/{config.NOTION_REPORTS_PAGE_ID}/children",
            headers={"Authorization": f"Bearer {config.NOTION_API_KEY}", "Notion-Version": "2022-06-28"},
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"✅ Notion Reports page — accessible (ID: {config.NOTION_REPORTS_PAGE_ID})")
        else:
            print(f"❌ Notion Reports page — {resp.status_code}")
    except Exception as e:
        print(f"❌ Notion Reports — {e}")

    # LLM
    try:
        print(f"✅ LLM config — standard:{llm_client.get_model_standard()} "
              f"/ flagged:{llm_client.get_model_flagged()} "
              f"/ reporting:{llm_client.get_model_reporting()}")
    except Exception as e:
        print(f"❌ LLM config — {e}")

    # Slack
    try:
        import requests as _req
        r = _req.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {config.SLACK_BOT_TOKEN}"},
            timeout=10,
        )
        data = r.json()
        if data.get("ok"):
            print(f"✅ Slack — connecté en tant que {data.get('user')} ({data.get('team')})")
        else:
            print(f"❌ Slack — {data.get('error', 'unknown')}")
    except Exception as e:
        print(f"❌ Slack — {e}")

    # Appels J-1
    try:
        yesterday = datetime.now() - timedelta(days=1)
        calls = call_fetcher.fetch_calls_for_date(yesterday)
        classified = call_classifier.classify_all(calls)
        ucc = call_classifier.filter_ucc_calls(classified)
        print(f"✅ Appels J-1 ({yesterday.strftime('%d/%m/%Y')}) — {len(calls)} total / {len(ucc)} UCC scope QA")
    except Exception as e:
        print(f"❌ Appels J-1 — {e}")

    print("\n=== FIN DU TEST ===\n")


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline QA Driveco")
    parser.add_argument("--mode", choices=["daily", "weekly", "test"], default="test")
    parser.add_argument("--date", default=None,
                        help="Date cible YYYY-MM-DD (défaut : hier pour daily, lundi dernier pour weekly)")
    args = parser.parse_args()

    if args.mode == "test":
        run_test()
    else:
        if args.date:
            target = datetime.strptime(args.date, "%Y-%m-%d")
        else:
            target = datetime.now() - timedelta(days=1)

        # Garde-fou : refuser les dates antérieures à ANALYSIS_MIN_DATE
        if target.date() < config.ANALYSIS_MIN_DATE:
            log.error(f"❌ Date {target.strftime('%Y-%m-%d')} antérieure à la limite autorisée "
                      f"({config.ANALYSIS_MIN_DATE}). Abandon.")
            raise SystemExit(1)

        if args.mode == "daily":
            run_daily(target)
        elif args.mode == "weekly":
            run_weekly(target)
