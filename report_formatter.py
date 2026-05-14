"""
report_formatter.py — Formate les résultats JSON du LLM en rapports Markdown.
"""
from datetime import datetime
import re
try:
    from zoneinfo import ZoneInfo
    _PARIS = ZoneInfo("Europe/Paris")
except ImportError:
    import pytz
    _PARIS = pytz.timezone("Europe/Paris")
import config
import persistence

_AIRCALL_BASE = "https://assets.aircall.io/calls"
_ISSUE_TYPE_LABELS = {
    "manque_d_empathie": "Manque d'empathie",
    "mauvaise_qualification_b2b_b2c": "Mauvaise qualification B2B/B2C",
    "manque_de_connaissance_du_client_sur_les_conditions_d_heure_gratuite": "Manque de clarté sur les conditions d'heure gratuite",
}


def _aircall_link_md(call_id) -> str:
    """Retourne un lien Markdown Aircall pour un call_id."""
    if not call_id or str(call_id) in ("?", ""):
        return str(call_id or "?")
    return f"[{call_id}]({_AIRCALL_BASE}/{call_id}/recording/info)"


def _format_call_reason_line(item: dict) -> str:
    label = item.get("label") or item.get("reason_code") or "Raison non classée"
    count = int(item.get("count") or 0)
    subreasons = []
    for subreason in item.get("subreasons") or []:
        sub_label = subreason.get("label")
        sub_count = int(subreason.get("count") or 0)
        if sub_label and sub_count:
            subreasons.append(f"{sub_label}: {sub_count}")
    detail = f" ({', '.join(subreasons[:4])})" if subreasons else ""
    return f"- {label} — {count} appel(s){detail}"


def _icon(value, key: str) -> str:
    if value is None:
        return "⚪"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "⚪"
    t = config.KPI_THRESHOLDS.get(key, {"green": 80, "yellow": 60, "higher_is_better": True})
    if t["higher_is_better"]:
        return "🟢" if value >= t["green"] else "🟡" if value >= t["yellow"] else "🔴"
    else:
        return "🟢" if value <= t["green"] else "🟡" if value <= t["yellow"] else "🔴"


def _score_icon(score) -> str:
    try:
        s = float(score)
        return "🟢" if s >= 8 else "🟡" if s >= 6 else "🔴"
    except (TypeError, ValueError):
        return "⚪"


def _score_text(score) -> str:
    try:
        return f"{float(score):.1f}/10"
    except (TypeError, ValueError):
        return "n/a"


def _normalize_issue_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        issue_type = value.get("type")
        if issue_type:
            return _humanize_issue_label(issue_type)
        for key in ("description", "message", "issue", "title", "observed_gap", "missing_section"):
            candidate = value.get(key)
            if candidate:
                return _normalize_issue_text(candidate)
        if value.get("error_code"):
            return str(value["error_code"]).strip()
    if isinstance(value, list):
        parts = [_normalize_issue_text(item) for item in value]
        return " | ".join([part for part in parts if part])
    text = " ".join(str(value).strip().split())
    for pattern in (
        r"[\"']?(?:commentaire|message|description|observed_gap|issue|title)[\"']?\s*:\s*[\"']([^\"']+)",
        r"[\"']?(?:type)[\"']?\s*:\s*[\"']([^\"']+)",
        r"[\"']?(?:critere|critère)[\"']?\s*:\s*[\"']([^\"']+)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            text = match.group(1).strip()
            break
    if len(text) < 4 and text.upper() not in {"B2B", "B2C", "UCC", "IVR", "CSAT"}:
        return ""
    return _humanize_issue_label(text)


def _humanize_issue_label(value) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    normalized_key = "".join(ch.lower() if ch.isalnum() else "_" for ch in text)
    normalized_key = "_".join(part for part in normalized_key.split("_") if part)
    if normalized_key in _ISSUE_TYPE_LABELS:
        return _ISSUE_TYPE_LABELS[normalized_key]
    cleaned = text.strip("{}[]()'\"")
    if cleaned.startswith("type:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    cleaned = cleaned.replace("_", " ")
    if cleaned.isupper():
        cleaned = cleaned.title()
    cleaned = cleaned.replace("B2b", "B2B").replace("B2c", "B2C").replace("Ivr", "IVR").replace("Ucc", "UCC")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def _normalize_kb_items(items, section: str) -> list[str]:
    lines = []
    for item in items or []:
        text = ""
        if isinstance(item, dict):
            if section == "missing":
                title = _normalize_issue_text(item.get("title"))
                desc = _normalize_issue_text(item.get("description"))
                text = f"{title} : {desc}" if title and desc else title or desc
            elif section == "incomplete":
                article = _normalize_issue_text(item.get("article"))
                missing_section = _normalize_issue_text(item.get("missing_section"))
                text = f"{article} : {missing_section}" if article and missing_section else article or missing_section
            elif section == "to_revise":
                article = _normalize_issue_text(item.get("article"))
                gap = _normalize_issue_text(item.get("observed_gap"))
                text = f"{article} : {gap}" if article and gap else article or gap
            if not text:
                text = _normalize_issue_text(item)
        else:
            text = _normalize_issue_text(item)
        if text:
            lines.append(text)
    return lines


def _append_voc_section(lines: list[str], analysis: dict) -> None:
    summary = analysis.get("voc_summary") or {}
    call_reasons = summary.get("call_reasons") or []
    top_topics = summary.get("top_topics") or []
    verbatims = summary.get("verbatims") or []
    weak_signals = summary.get("weak_signals") or []
    competitors = summary.get("competitors") or []
    opportunities = summary.get("opportunities") or []
    best_practices = summary.get("best_practices") or []
    positive_satisfaction = summary.get("positive_satisfaction") or {}
    if not (call_reasons or top_topics or verbatims or weak_signals or competitors or opportunities or best_practices):
        return

    lines += ["## Raisons d'appel", ""]
    if call_reasons:
        lines.append("### Raisons principales")
        for item in call_reasons[:8]:
            lines.append(_format_call_reason_line(item))
        lines.append("")
    if top_topics:
        lines.append("### Topics détectés")
        for item in top_topics[:5]:
            lines.append(f"- {item.get('label', item.get('topic_code'))} — {item.get('count', 0)} mention(s)")
        lines.append("")
    if weak_signals:
        lines.append("### Signaux faibles")
        for item in weak_signals[:5]:
            lines.append(f"- {item.get('topic_code')} — {item.get('count', 0)} mention(s)")
        lines.append("")
    if verbatims:
        lines.append("### Verbatims saillants")
        for item in verbatims[:5]:
            topic = item.get("topic_code") or "autre"
            lines.append(f"- « {item.get('quote')} » *(appel {item.get('call_id', '?')} — {topic})*")
        lines.append("")
    if competitors:
        lines.append("### Concurrents cités")
        for item in competitors[:5]:
            sample = item.get("sample_quote") or "contexte non disponible"
            lines.append(f"- {item.get('competitor_name')} — {item.get('count', 0)} mention(s) — « {sample} »")
        lines.append("")
    if opportunities:
        lines.append("### 💡 Opportunités détectées")
        for item in opportunities[:5]:
            lines.append(f"- {item.get('description')} — {item.get('count', 0)} occurrence(s)")
        lines.append("")
    if best_practices:
        lines.append("### ✨ Bonnes pratiques agents")
        for item in best_practices[:3]:
            lines.append(f"- Agent anonymisé — « {item.get('quote')} »")
        lines.append("")
    if positive_satisfaction.get("count"):
        lines.append("### 🌱 Satisfaction positive")
        lines.append(f"- {positive_satisfaction.get('count', 0)} appel(s) avec signal positif")
        if positive_satisfaction.get("sample_quote"):
            lines.append(f"- Verbatim : « {positive_satisfaction.get('sample_quote')} »")
        lines.append("")
    if competitors:
        lines.append("### 👀 Concurrents cités")
        names = ", ".join(item.get("competitor_name", "?") for item in competitors[:5])
        lines.append(f"- {sum(int(item.get('count', 0) or 0) for item in competitors)} mention(s) — {names}")
        lines.append("")


def _dedupe_texts(items: list[dict]) -> list[dict]:
    seen = set()
    output = []
    for item in items:
        normalized = re.sub(r"\s+", " ", str(item.get("description") or "").strip().lower())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(item)
    return output


def build_actionable_items(analysis: dict) -> list[dict]:
    items = []
    for ev in analysis.get("top_problematic_calls", []) or []:
        description = _normalize_issue_text((ev.get("errors") or [""])[0]) or "appel problématique"
        items.append(
            {
                "source": "top_problematic_calls",
                "tag": "coaching",
                "description": description,
                "call_id": ev.get("call_id"),
                "priority": "high",
                "agent": ev.get("agent") or ev.get("user_name"),
                "score_global": ev.get("score_global"),
            }
        )
    kb = analysis.get("kb_gaps", {}) or {}
    for section in ("missing", "incomplete", "to_revise"):
        for item in _normalize_kb_items(kb.get(section, []), section):
            items.append(
                {
                    "source": "kb_gaps",
                    "tag": "kb",
                    "description": item,
                    "call_id": None,
                    "priority": "high" if section == "missing" else "medium",
                }
            )
    for item in (analysis.get("voc_summary") or {}).get("opportunities", []) or []:
        items.append(
            {
                "source": "voc",
                "tag": "produit",
                "description": item.get("description"),
                "call_id": None,
                "priority": "medium",
            }
        )
    for item in (analysis.get("voc_summary") or {}).get("competitors", []) or []:
        items.append(
            {
                "source": "voc",
                "tag": "concurrence",
                "description": f"{item.get('competitor_name')} — {item.get('count', 0)} mention(s)",
                "call_id": None,
                "priority": "medium",
            }
        )
    for item in analysis.get("anomalies", []) or []:
        items.append(
            {
                "source": "anomaly",
                "tag": "cx",
                "description": f"{item.get('metric')} anormal sur {item.get('scope')}",
                "call_id": None,
                "representative_call_ids": list(item.get("representative_call_ids") or [])[:3],
                "priority": "critical",
            }
        )
    return _dedupe_texts(items)


def format_daily_report(date: datetime, metrics: dict, analysis: dict) -> str:
    kpis   = analysis.get("kpis", metrics)
    scores = analysis.get("scores", {})
    run_health = analysis.get("run_health") or {}

    ucc_score     = scores.get("ucc_quality_score", "N/A")
    drv_score     = scores.get("driveco_care_score", "N/A")
    ucc_just      = scores.get("ucc_score_justification", "")
    drv_just      = scores.get("driveco_score_justification", "")

    lines = []
    actionable_items = analysis.get("actionable_items") or build_actionable_items(analysis)
    analysis["actionable_items"] = actionable_items
    coaching_items = [item for item in actionable_items if item.get("tag") == "coaching"]
    kb_items = [item for item in actionable_items if item.get("tag") == "kb"]
    anomaly_items = [item for item in actionable_items if item.get("priority") == "critical" and item.get("source") == "anomaly"]
    if run_health.get("degraded"):
        lines += [f"# ⚠️ RUN DÉGRADÉ — couverture {run_health.get('retention_rate_pct', 0)}%", ""]

    lines += [
        f"# Analyse Appels — {date.strftime('%d/%m/%Y')}",
        "",
        "## Résumé",
        f"**UCC** {_score_icon(ucc_score)} {_score_text(ucc_score)} — {ucc_just}",
        f"**Driveco Care** {_score_icon(drv_score)} {_score_text(drv_score)} — {drv_just}",
        "",
        "## KPIs",
        "| Métrique | Valeur | Statut |",
        "|---|---|---|",
        f"| Appels présentés | {kpis.get('calls_presented', 0)} | — |",
        f"| Taux décroché UCC | {kpis.get('pickup_rate_pct', 0)}% | {_icon(kpis.get('pickup_rate_pct', 0), 'pickup_rate')} |",
        f"| Taux overflow Aircall | {kpis.get('overflow_rate_pct', 0)}% | {_icon(kpis.get('overflow_rate_pct', 0), 'overflow_rate')} |",
        f"| Taux abandon | {kpis.get('abandon_rate_pct', 0)}% | {_icon(kpis.get('abandon_rate_pct', 0), 'abandon_rate')} |",
        f"| Conformité KB | {kpis.get('kb_compliance_rate_pct', 0)}% | {_icon(kpis.get('kb_compliance_rate_pct', 0), 'kb_compliance_rate')} |",
        f"| Durée moy. | {kpis.get('avg_duration_seconds', 0)}s | — |",
        f"| Attente moy. | {kpis.get('avg_wait_time_seconds', 0)}s | — |",
        "",
    ]

    transfer_total = kpis.get("transfer_line_total_count", 0)
    if transfer_total:
        lines += [
            "## Transferts UCC → Driveco Care",
            f"- Appels arrivés sur la ligne 1214611 : {transfer_total}",
            f"- Décrochés côté Driveco : {kpis.get('transfer_line_answered_count', 0)}",
            f"- Manqués côté Driveco : {kpis.get('transfer_line_missed_count', 0)}",
            "- Lecture : ce bloc reflète la ligne transfert, pas un rapprochement 1:1 garanti avec un timeout UCC",
            "",
        ]

    peak_windows = kpis.get("peak_windows", []) or []
    if peak_windows:
        lines += ["## Pics d'appels"]
        for window in peak_windows[:3]:
            lines.append(f"- {window.get('label', '?')} : {window.get('count', 0)} appel(s)")
        lines.append("")

    long_threshold = config.LONG_CALL_THRESHOLD_SECONDS
    long_calls = kpis.get("long_ucc_calls_top", []) or []
    if long_calls:
        lines += [f"## Appels longs UCC (≥ {long_threshold // 60} min)"]
        lines.append(f"- Total appels UCC ≥ {long_threshold // 60} min : {kpis.get('long_ucc_calls_count', len(long_calls))}")
        for item in long_calls[:5]:
            cid = item.get("call_id") or "?"
            link = _aircall_link_md(cid)
            duration = int(item.get("duration_seconds") or 0)
            started_at = item.get("call_started_at")
            try:
                started_label = datetime.fromtimestamp(int(started_at), tz=_PARIS).strftime("%d/%m %H:%M")
            except (TypeError, ValueError, OSError):
                started_label = "date/heure indisponible"
            lines.append(f"- {link} — {started_label} — {duration // 60}min{duration % 60:02d}s")
        lines.append("")

    top_prob = analysis.get("top_problematic_calls", [])
    if top_prob:
        lines += ["## 🚨 Appels les plus problématiques", ""]
        shown = 0
        for ev in top_prob:
            desc = _normalize_issue_text((ev.get("errors") or [""])[0]) or "appel problématique"
            if not any(item for item in coaching_items if item.get("description") == desc):
                continue
            cid    = ev.get("call_id", "?")
            agent  = ev.get("agent") or ev.get("user_name") or "N/A"
            dur    = ev.get("duration_seconds") or ev.get("duration_in_call") or "?"
            kb_c   = ev.get("kb_compliance", "?")
            errors = ev.get("errors", [])
            alts   = ev.get("alerts", [])
            ss     = (ev.get("soft_skills") or {}).get("note_globale")
            ss_str = f" | Soft skills : {ss}/10" if ss is not None else ""
            tags   = ev.get("tags") or ev.get("classified_type") or ""
            tags_str = f" — *{tags}*" if tags else ""
            # Contexte pour appels longs (>15 min)
            try:
                dur_int = int(dur)
                if dur_int > 900:
                    long_str = f" ⏳ appel long ({dur_int//60}min{dur_int%60:02d}s{tags_str})"
                else:
                    long_str = f" ({dur_int}s)"
            except (TypeError, ValueError):
                long_str = f" ({dur}s)"
            link = _aircall_link_md(cid)
            lines.append(f"### Appel {link} — {agent}{long_str}")
            lines.append(f"KB : `{kb_c}`{ss_str}")
            for err in errors[:3]:
                lines.append(f"- ❌ {_normalize_issue_text(err)}")
            for alt in alts[:2]:
                icon = "🔴" if alt.get("level") == "critical" else "⚠️"
                lines.append(f"- {icon} {alt.get('message', '')}")
            lines.append("")
            shown += 1
            if shown >= 5:
                break

    good = analysis.get("good_practices", [])
    if good:
        lines += ["## Bonnes pratiques observées"]
        lines += [f"- {p}" for p in good]
        lines.append("")

    evals = analysis.get("call_evaluations", [])
    errors = []
    for ev in evals:
        cid_link = _aircall_link_md(ev.get("call_id", "?"))
        for err in ev.get("errors", []):
            errors.append(f"- {_normalize_issue_text(err)} *(Appel {cid_link} — KB: {ev.get('kb_article_applicable', '?')} — {ev.get('kb_compliance', '?')})*")
    if errors:
        lines += ["## Erreurs / Oublis identifiés"] + errors + [""]

    # Soft skills — uniquement si au moins un appel a des données
    soft_evals = [(ev.get("call_id", "?"), ev.get("soft_skills")) for ev in evals if ev.get("soft_skills")]
    soft_evals = [(cid, ss) for cid, ss in soft_evals if ss and ss.get("note_globale") is not None]
    if soft_evals:
        lines += ["## Soft Skills Agents"]
        lines.append("| Appel | Accueil | Écoute | Empathie | Tension | Pro. | Clarté | Solution | Clôture | **Note** |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for cid, ss in soft_evals:
            def _s(k): return str(ss.get(k)) if ss.get(k) is not None else "—"
            lines.append(
                f"| {cid} "
                f"| {_s('accueil')} "
                f"| {_s('ecoute_active')} "
                f"| {_s('empathie')} "
                f"| {_s('gestion_tension')} "
                f"| {_s('professionnalisme')} "
                f"| {_s('clarte_communication')} "
                f"| {_s('orientation_solution')} "
                f"| {_s('cloture')} "
                f"| **{_s('note_globale')}** |"
            )
        obs_lines = [f"- Appel {cid} : {ss['observations']}"
                     for cid, ss in soft_evals if (ss.get("observations") or "").strip()]
        if obs_lines:
            lines.append("")
            lines.append("**Observations :**")
            lines.extend(obs_lines)
        lines.append("")

    if anomaly_items:
        lines += ["## ⚠️ Alertes", ""]
        for item in anomaly_items[:5]:
            lines.append(f"- 🔴 {item.get('description')}")
        lines.append("")

    if kb_items:
        lines += ["## 📚 KB", ""]
        for item in kb_items[:5]:
            lines.append(f"- [ ] {item.get('description')}")
        lines.append("")

    focus_items = [item for item in coaching_items if item.get("description") not in {x.get("description") for x in coaching_items[:5]}]
    if focus_items:
        lines += ["## Focus coaching du jour", ""]
        for item in focus_items[:3]:
            lines.append(f"- {item.get('description')}")
        lines.append("")

    _append_voc_section(lines, analysis)

    lines += [
        "",
        "---",
        "*⚠️ Note couverture : les appels de la ligne 1214611 (DRIVECO - UCC Transfer) "
        "ne sont pas capturés dans Aircall/D1. Les overflows directs UCC→Driveco "
        "(~85 appels sur la période analysée) sont absents de cette analyse.*",
    ]

    return "\n".join(lines)


def format_weekly_report(start: datetime, end: datetime, metrics: dict, analysis: dict) -> str:
    kpis   = analysis.get("kpis", metrics)
    scores = analysis.get("scores", {})
    week_label = f"Semaine du {start.strftime('%d/%m')} au {end.strftime('%d/%m/%Y')}"
    trend_rows = persistence.fetch_view_rows("v_kpi_trend_daily", columns="date,total_calls,pickup_rate,abandon_rate,avg_soft_score,fcr_rate", scope="global")
    topic_rows = persistence.fetch_view_rows("v_voc_topics_trend_28d", columns="day,topic_code,mentions,avg_sentiment", limit=10)
    opportunity_rows = persistence.fetch_view_rows("v_voc_opportunities_ranked", columns="description,frequency,opportunity_score", limit=5)
    competitor_rows = persistence.fetch_view_rows("v_voc_competitors_watch", columns="week_start,competitor_name,mentions", limit=5)
    agent_rows = persistence.fetch_view_rows("v_agent_scorecard_30d", columns="agent_name,avg_soft_score,total_calls,kb_compliance_rate", limit=10)
    kb_gap_rows = persistence.fetch_view_rows("v_kb_gaps_active", columns="topic,frequency,status", limit=5)

    def _wow(metric_key: str) -> str:
        values = [row.get(metric_key) for row in trend_rows if row.get(metric_key) is not None][:14]
        if len(values) < 14:
            return "n/a"
        current = sum(float(v) for v in values[:7]) / 7
        previous = sum(float(v) for v in values[7:14]) / 7
        delta = round(current - previous, 1)
        sign = "+" if delta > 0 else ""
        return f"{sign}{delta}"

    cx_health = None
    try:
        pickup = float(kpis.get("pickup_rate_pct") or 0)
        abandon = float(kpis.get("abandon_rate_pct") or 0)
        ucc = float(scores.get("ucc_quality_score") or 0)
        drv = float(scores.get("driveco_care_score") or 0)
        fcr = float((analysis.get("snapshot_metrics") or {}).get("fcr_rate_pct") or 0)
        cx_health = round((pickup * 0.2) + ((100 - abandon) * 0.2) + (ucc * 5 * 0.2) + (drv * 5 * 0.2) + (fcr * 0.2), 1)
    except (TypeError, ValueError):
        cx_health = None

    lines = [f"# Bilan Hebdomadaire — {week_label}", ""]
    lines += ["## Exec summary"]
    lines.append(f"- Volume semaine : {kpis.get('calls_presented', 0)} appels")
    lines.append(f"- Pickup : {kpis.get('pickup_rate_pct', 0)}% | Abandon : {kpis.get('abandon_rate_pct', 0)}%")
    lines.append(f"- Score UCC : {_score_text(scores.get('ucc_quality_score'))} | Score Driveco : {_score_text(scores.get('driveco_care_score'))}")
    lines.append(f"- CX health composite score : {cx_health if cx_health is not None else 'n/a'}")
    lines.append("")

    lines += ["## Δ WoW sur 6 KPIs"]
    lines.append(f"- Volume : {_wow('total_calls')}")
    lines.append(f"- Pickup : {_wow('pickup_rate')}")
    lines.append(f"- Abandon : {_wow('abandon_rate')}")
    lines.append(f"- Score UCC : {_wow('avg_soft_score')}")
    lines.append(f"- Score Driveco : {_score_text(scores.get('driveco_care_score'))}")
    lines.append(f"- FCR : {_wow('fcr_rate')}")
    lines.append("")

    if topic_rows:
        lines += ["## Topics en mouvement"]
        for row in topic_rows[:5]:
            lines.append(f"- {row.get('topic_code')} — {row.get('mentions')} mention(s), sentiment {row.get('avg_sentiment')}")
        lines.append("")

    weak_signals = (analysis.get("voc_summary") or {}).get("weak_signals") or []
    if weak_signals:
        lines += ["## Nouveaux signaux faibles / clos"]
        for row in weak_signals[:5]:
            lines.append(f"- {row.get('topic_code')} — {row.get('count', 0)} mention(s)")
        lines.append("")

    if agent_rows:
        lines += ["## Agent leaderboard"]
        for row in agent_rows[:5]:
            lines.append(f"- {row.get('agent_name') or 'Agent'} — soft {row.get('avg_soft_score')} / KB {row.get('kb_compliance_rate')} / volume {row.get('total_calls')}")
        lines.append("")

    if opportunity_rows:
        lines += ["## Opportunités"]
        for row in opportunity_rows[:5]:
            lines.append(f"- {row.get('description')} — score {row.get('opportunity_score')} / fréquence {row.get('frequency')}")
        lines.append("")

    if competitor_rows:
        lines += ["## Competitor watch"]
        for row in competitor_rows[:5]:
            lines.append(f"- {row.get('competitor_name')} — {row.get('mentions')} mention(s)")
        lines.append("")

    if kb_gap_rows:
        lines += ["## KB gaps persistants vs nouveaux"]
        for row in kb_gap_rows[:5]:
            lines.append(f"- {row.get('topic')} — {row.get('frequency')} occurrence(s) — statut {row.get('status')}")
        lines.append("")

    actions = _dedupe_texts(build_actionable_items(analysis))
    if actions:
        lines += ["## Actions top 5 avec owner suggéré"]
        owner_map = {"kb": "Knowledge", "coaching": "Ops", "produit": "Produit", "cx": "Ops", "concurrence": "Direction"}
        for item in actions[:5]:
            lines.append(f"- [{owner_map.get(item.get('tag'), 'Ops')}] {item.get('description')}")
        lines.append("")

    return "\n".join(lines)
