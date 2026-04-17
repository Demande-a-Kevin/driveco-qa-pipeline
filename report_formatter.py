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

_AIRCALL_BASE = "https://asset.aircall.io/calls"
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
    top_topics = summary.get("top_topics") or []
    verbatims = summary.get("verbatims") or []
    weak_signals = summary.get("weak_signals") or []
    competitors = summary.get("competitors") or []
    opportunities = summary.get("opportunities") or []
    if not (top_topics or verbatims or weak_signals or competitors or opportunities):
        return

    lines += ["## Voix du client", ""]
    if top_topics:
        lines.append("### Top topics")
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
        lines.append("### Opportunités produit")
        for item in opportunities[:5]:
            lines.append(f"- {item.get('description')} — {item.get('count', 0)} occurrence(s)")
        lines.append("")


def format_daily_report(date: datetime, metrics: dict, analysis: dict) -> str:
    kpis   = analysis.get("kpis", metrics)
    scores = analysis.get("scores", {})
    run_health = analysis.get("run_health") or {}

    ucc_score     = scores.get("ucc_quality_score", "N/A")
    drv_score     = scores.get("driveco_care_score", "N/A")
    ucc_just      = scores.get("ucc_score_justification", "")
    drv_just      = scores.get("driveco_score_justification", "")

    lines = []
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

    # Top appels problématiques — mis en avant avant tout le reste
    top_prob = analysis.get("top_problematic_calls", [])
    if top_prob:
        lines += ["## 🚨 Appels les plus problématiques", ""]
        for ev in top_prob:
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

    issues = analysis.get("top_issues", [])
    if issues:
        lines += ["## Top problèmes clients"]
        for i, issue in enumerate(issues[:5], 1):
            lines.append(f"{i}. {issue.get('issue')} — {issue.get('occurrences', '?')} occurrence(s)")
        lines.append("")

    alerts = analysis.get("alerts", []) + metrics.get("alerts", [])
    if alerts:
        lines += ["## Alertes"]
        for a in alerts:
            icon = "🔴" if a.get("level") == "critical" else "🟡"
            lines.append(f"{icon} {a.get('message')}")
        lines.append("")

    kb = analysis.get("kb_gaps", {})
    lines += ["## Recommandations Knowledge Base", ""]
    missing = _normalize_kb_items(kb.get("missing", []), "missing")
    incomplete = _normalize_kb_items(kb.get("incomplete", []), "incomplete")
    to_revise = _normalize_kb_items(kb.get("to_revise", []), "to_revise")
    if missing:
        lines += ["### Articles à créer"]
        for item in missing:
            lines.append(f"- [ ] {item}")
        lines.append("")
    if incomplete:
        lines += ["### Articles à compléter"]
        for item in incomplete:
            lines.append(f"- [ ] {item}")
        lines.append("")
    if to_revise:
        lines += ["### Articles à réviser"]
        for item in to_revise:
            lines.append(f"- [ ] {item}")
        lines.append("")

    recs = analysis.get("recommendations", [])
    if recs:
        lines += ["## Recommandations opérationnelles"]
        lines += [f"- {r}" for r in recs]

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
    """
    Rapport hebdomadaire structuré — 7 jours, KPIs CS complets, breakdown journalier.
    Conforme aux standards Customer Care : volumétrie, taux décroché, AHT, CSAT proxy, tendances.
    """
    kpis   = analysis.get("kpis", metrics)
    scores = analysis.get("scores", {})
    trend  = analysis.get("weekly_trend") or ""

    ucc_score  = scores.get("ucc_quality_score", "N/A")
    drv_score  = scores.get("driveco_care_score", "N/A")
    ucc_just   = scores.get("ucc_score_justification", "")
    drv_just   = scores.get("driveco_score_justification", "")

    week_label = f"Semaine du {start.strftime('%d/%m')} au {end.strftime('%d/%m/%Y')}"

    lines = [
        f"# Bilan Hebdomadaire — {week_label}",
        "",
        "## Scores qualité",
        f"**UCC** {_score_icon(ucc_score)} {_score_text(ucc_score)} — {ucc_just}",
        f"**Driveco Care** {_score_icon(drv_score)} {_score_text(drv_score)} — {drv_just}",
        "",
    ]

    # ── KPIs principaux (semaine complète) ────────────────────────────────────
    total     = kpis.get("calls_presented", 0)
    answered  = kpis.get("calls_answered", 0)
    overflow  = kpis.get("overflow_count", 0)
    abandoned = kpis.get("abandoned_count", 0)
    escalations = kpis.get("escalations_count", 0)
    pickup    = kpis.get("pickup_rate_pct", 0)
    ovfl_pct  = kpis.get("overflow_rate_pct", 0)
    abn_pct   = kpis.get("abandon_rate_pct", 0)
    kb_rate   = kpis.get("kb_compliance_rate_pct", 0)
    avg_dur   = kpis.get("avg_duration_seconds", 0)
    avg_wait  = kpis.get("avg_wait_time_seconds", 0)

    # AHT en minutes:secondes
    def _fmt_dur(seconds) -> str:
        try:
            s = int(seconds)
            return f"{s // 60}m{s % 60:02d}s"
        except (TypeError, ValueError):
            return f"{seconds}s"

    lines += [
        "## KPIs hebdomadaires",
        "| Métrique | Valeur | Objectif | Statut |",
        "|---|---|---|---|",
        f"| Appels présentés | {total} | — | — |",
        f"| Appels décrochés | {answered} | — | — |",
        f"| Taux de décroché (UCC) | {pickup}% | ≥ 85% | {_icon(pickup, 'pickup_rate')} |",
        f"| Taux d'overflow | {ovfl_pct}% | ≤ 10% | {_icon(ovfl_pct, 'overflow_rate')} |",
        f"| Taux d'abandon | {abn_pct}% | ≤ 8% | {_icon(abn_pct, 'abandon_rate')} |",
        f"| Appels abandonnés | {abandoned} | — | — |",
        f"| Escalades (transferts chauds) | {escalations} | — | — |",
        f"| Conformité KB | {kb_rate}% | ≥ 80% | {_icon(kb_rate, 'kb_compliance_rate')} |",
        f"| Durée moyenne d'appel (AHT) | {_fmt_dur(avg_dur)} | — | — |",
        f"| Temps d'attente moyen | {_fmt_dur(avg_wait)} | — | — |",
        "",
    ]

    # ── Breakdown journalier ───────────────────────────────────────────────────
    daily_breakdown = metrics.get("daily_breakdown", {})
    if daily_breakdown:
        lines += ["## Détail journalier", ""]
        lines.append("| Jour | Appels | Décroché | Overflow | Abandon | AHT |")
        lines.append("|---|---|---|---|---|---|")
        from datetime import timedelta
        for i in range(7):
            day = start + timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            dm = daily_breakdown.get(day_str, {})
            if not dm:
                lines.append(f"| {day.strftime('%a %d/%m')} | 0 | — | — | — | — |")
                continue
            d_pickup = dm.get("pickup_rate_pct", 0)
            d_ovfl   = dm.get("overflow_rate_pct", 0)
            d_abn    = dm.get("abandon_rate_pct", 0)
            d_dur    = _fmt_dur(dm.get("avg_duration_seconds", 0))
            lines.append(
                f"| {day.strftime('%a %d/%m')} "
                f"| {dm.get('calls_presented', 0)} "
                f"| {_icon(d_pickup, 'pickup_rate')} {d_pickup}% "
                f"| {_icon(d_ovfl, 'overflow_rate')} {d_ovfl}% "
                f"| {_icon(d_abn, 'abandon_rate')} {d_abn}% "
                f"| {d_dur} |"
            )
        lines.append("")

    # ── Top appels problématiques ──────────────────────────────────────────────
    top_prob = analysis.get("top_problematic_calls", [])
    if top_prob:
        lines += ["## Appels les plus problématiques de la semaine", ""]
        for ev in top_prob:
            cid   = ev.get("call_id", "?")
            agent = ev.get("agent") or ev.get("user_name") or "N/A"
            dur   = ev.get("duration_seconds") or ev.get("duration_in_call") or "?"
            kb_c  = ev.get("kb_compliance", "?")
            errors = ev.get("errors", [])
            alts   = ev.get("alerts", [])
            day_ref = ev.get("day") or ""
            day_str = f" ({day_ref})" if day_ref else ""
            link = _aircall_link_md(cid)
            lines.append(f"### Appel {link} — {agent}{day_str} ({dur}s) — KB : `{kb_c}`")
            for err in errors[:3]:
                lines.append(f"- ❌ {err}")
            for alt in alts[:2]:
                icon = "🔴" if alt.get("level") == "critical" else "⚠️"
                lines.append(f"- {icon} {alt.get('message', '')}")
            lines.append("")

    # ── Bonnes pratiques ──────────────────────────────────────────────────────
    good = analysis.get("good_practices", [])
    if good:
        lines += ["## Bonnes pratiques observées"]
        lines += [f"- {p}" for p in good]
        lines.append("")

    # ── Top problèmes clients ─────────────────────────────────────────────────
    issues = analysis.get("top_issues", [])
    if issues:
        lines += ["## Top problèmes clients"]
        for i, issue in enumerate(issues[:5], 1):
            lines.append(f"{i}. {issue.get('issue')} — {issue.get('occurrences', '?')} occurrence(s)")
        lines.append("")

    # ── Tendance hebdomadaire (S vs S-1) ──────────────────────────────────────
    if trend:
        lines += ["## Tendance vs semaine précédente", "", trend, ""]

    # ── Alertes ───────────────────────────────────────────────────────────────
    alerts = analysis.get("alerts", []) + metrics.get("alerts", [])
    if alerts:
        lines += ["## Alertes"]
        for a in alerts:
            icon = "🔴" if a.get("level") == "critical" else "🟡"
            lines.append(f"{icon} {a.get('message')}")
        lines.append("")

    # ── Soft skills synthèse ──────────────────────────────────────────────────
    evals = analysis.get("call_evaluations", [])
    soft_evals = [(ev.get("call_id", "?"), ev.get("soft_skills")) for ev in evals if ev.get("soft_skills")]
    soft_evals = [(cid, ss) for cid, ss in soft_evals if ss and ss.get("note_globale") is not None]
    if soft_evals:
        notes = [float(ss.get("note_globale")) for _, ss in soft_evals]
        avg_note = round(sum(notes) / len(notes), 1) if notes else None
        if avg_note is not None:
            lines += [
                "## Soft Skills — synthèse semaine",
                f"Note moyenne : **{avg_note}/10** sur {len(soft_evals)} appels évalués",
                "",
            ]

    # ── Knowledge Base ────────────────────────────────────────────────────────
    kb = analysis.get("kb_gaps", {})
    lines += ["## Recommandations Knowledge Base", ""]
    missing = _normalize_kb_items(kb.get("missing", []), "missing")
    incomplete = _normalize_kb_items(kb.get("incomplete", []), "incomplete")
    to_revise = _normalize_kb_items(kb.get("to_revise", []), "to_revise")
    if missing:
        lines += ["### Articles à créer"]
        for item in missing:
            lines.append(f"- [ ] {item}")
        lines.append("")
    if incomplete:
        lines += ["### Articles à compléter"]
        for item in incomplete:
            lines.append(f"- [ ] {item}")
        lines.append("")
    if to_revise:
        lines += ["### Articles à réviser"]
        for item in to_revise:
            lines.append(f"- [ ] {item}")
        lines.append("")

    # ── Recommandations opérationnelles ──────────────────────────────────────
    recs = analysis.get("recommendations", [])
    if recs:
        lines += ["## Recommandations opérationnelles"]
        lines += [f"- {r}" for r in recs]
        lines.append("")

    _append_voc_section(lines, analysis)

    lines += [
        "---",
        "*⚠️ Note couverture : les appels de la ligne 1214611 (DRIVECO - UCC Transfer) "
        "ne sont pas capturés dans Aircall/D1. Les overflows directs UCC→Driveco "
        "(~85 appels sur la période analysée) sont absents de cette analyse.*",
    ]

    return "\n".join(lines)
