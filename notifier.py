"""
notifier.py — Envoie les notifications Slack (Block Kit), sauvegarde les rapports
en local ET les uploade vers Google Drive (dossier UCC AircallQuality Analysis).
"""
from collections import Counter
from datetime import datetime
from pathlib import Path
import re
import requests
import config
import gdrive_uploader
import notion_reporter
import call_fetcher
import report_formatter

OUTPUT = config.REPORT_OUTPUT_DIR

_SLACK_API_URL = "https://slack.com/api/chat.postMessage"
_AIRCALL_ASSET_BASE = "https://assets.aircall.io/calls"


def _slack_sent_flag(kind: str, mode: str, date: datetime) -> Path:
    """Chemin du flag de déduplication Slack.

    `kind="report"` conserve le nom historique `.slack_sent_{mode}_{date}.flag`
    pour rester compatible avec `run_daily_watchdog.sh` et les runtimes en prod.
    Les autres types (`voc`, `anomaly`) utilisent un flag distinct pour permettre
    de rejouer un sous-ensemble sans déclencher la republication du rapport principal.
    """
    date_str = date.strftime("%Y-%m-%d")
    if kind == "report":
        return OUTPUT / f".slack_sent_{mode}_{date_str}.flag"
    return OUTPUT / f".slack_sent_{kind}_{mode}_{date_str}.flag"


def _slack_already_sent(kind: str, mode: str, date: datetime) -> bool:
    return _slack_sent_flag(kind, mode, date).exists()


def _mark_slack_sent(kind: str, mode: str, date: datetime) -> None:
    flag = _slack_sent_flag(kind, mode, date)
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    except OSError as exc:
        print(f"[notifier] ⚠️  impossible de créer flag dédup {flag}: {exc}")

_ISSUE_TYPE_LABELS = {
    "manque_d_empathie": "Manque d'empathie",
    "mauvaise_qualification_b2b_b2c": "Mauvaise qualification B2B/B2C",
    "manque_de_connaissance_du_client_sur_les_conditions_d_heure_gratuite": "Manque de clarté sur les conditions d'heure gratuite",
}


def _post_to_slack(blocks: list[dict], text: str = "", channel: str | None = None,
                   thread_ts: str | None = None) -> bool:
    """Envoie un message Slack via l'API HTTP directe (bot token).
    Retourne le `ts` du message (string, truthy) si succès, True si Slack désactivé,
    False sinon. thread_ts permet de répondre en fil (chantier 0.6 catchup)."""
    if config.DISABLE_SLACK_NOTIFICATIONS:
        print("[notifier] ℹ️  Slack désactivé par config — envoi ignoré")
        return True
    token = config.SLACK_BOT_TOKEN
    target_channel = channel or config.SLACK_CHANNEL_ID
    if not token:
        print("[notifier] ⚠️  SLACK_BOT_TOKEN non défini — envoi Slack ignoré")
        return False
    try:
        body = {"channel": target_channel, "blocks": blocks, "text": text}
        if thread_ts:
            body["thread_ts"] = thread_ts
        resp = requests.post(
            _SLACK_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            print(f"[notifier] ✅ Slack envoyé → #{target_channel}")
            return data.get("ts") or True
        else:
            print(f"[notifier] ❌ Erreur Slack : {data.get('error', 'unknown')}")
            return False
    except Exception as e:
        print(f"[notifier] ❌ Exception Slack : {e}")
        return False


def _score_icon(score) -> str:
    try:
        return "🟢" if float(score) >= 8 else "🟡" if float(score) >= 6 else "🔴"
    except (TypeError, ValueError):
        return "⚪"


def _score_text(score) -> str:
    try:
        return f"{float(score):.1f}/10"
    except (TypeError, ValueError):
        return "n/a"


def _score_icon_n(score, n, min_n: int | None = None) -> str:
    """Icône statut d'un score QA en tenant compte de l'effectif n (chantier 0.5).
    Sous le seuil de significativité, on n'affiche PAS de rouge/vert trompeur : ⚪."""
    min_n = config.SCORE_MIN_N if min_n is None else min_n
    try:
        if n is None or int(n) < int(min_n):
            return "⚪"
    except (TypeError, ValueError):
        return "⚪"
    return _score_icon(score)


def _score_text_n(score, n) -> str:
    """Texte du score avec effectif explicite : `4.2/10 (n=4)`."""
    base = _score_text(score)
    try:
        if n is not None:
            return f"{base} (n={int(n)})"
    except (TypeError, ValueError):
        pass
    return base


def _aircall_link(call_id) -> str:
    """Retourne un lien Aircall mrkdwn pour un call_id."""
    if not call_id or str(call_id) in ("?", ""):
        return str(call_id or "?")
    return f"<{_AIRCALL_ASSET_BASE}/{call_id}/recording/info|{call_id}>"


def _kpi_icon(value, key: str) -> str:
    if value is None:
        return "⚪"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "⚪"
    t = config.KPI_THRESHOLDS.get(key, {"green": 80, "yellow": 60, "higher_is_better": True})
    if t["higher_is_better"]:
        return "🟢" if value >= t["green"] else "🟡" if value >= t["yellow"] else "🔴"
    return "🟢" if value <= t["green"] else "🟡" if value <= t["yellow"] else "🔴"


def _format_duration(seconds) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return str(seconds or "n/a")
    return f"{total // 60}min{total % 60:02d}s"


def _format_call_reason_lines(call_reasons: list[dict], limit: int = 6) -> list[str]:
    lines = []
    for item in (call_reasons or [])[:limit]:
        label = item.get("label") or item.get("reason_code") or "Raison non classée"
        count = int(item.get("count") or 0)
        subreasons = []
        for subreason in item.get("subreasons") or []:
            sub_label = subreason.get("label")
            sub_count = int(subreason.get("count") or 0)
            if sub_label and sub_count:
                subreasons.append(f"{sub_label}: {sub_count}")
        detail = f" ({', '.join(subreasons[:3])})" if subreasons else ""
        lines.append(f"• *{label}* — {count} appel(s){detail}")
    return lines


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
    cleaned = cleaned.replace("Driveco", "Driveco")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def _phone_digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _is_internal_number(value) -> bool:
    digits = _phone_digits(value)
    return bool(digits) and digits in config.INTERNAL_PHONE_BLACKLIST


def _normalize_key(value) -> str:
    return "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum())


def _call_id_candidates(call: dict) -> set[str]:
    candidates = set()
    for key in ("call_id_internal", "call_id", "id"):
        value = call.get(key)
        if value is not None and str(value).strip():
            candidates.add(str(value).strip())
    return candidates


def _build_evaluation_index(analysis: dict) -> dict[str, dict]:
    out = {}
    for ev in analysis.get("call_evaluations", []) or []:
        if not isinstance(ev, dict):
            continue
        call_id = ev.get("call_id_internal") or ev.get("call_id")
        if call_id is not None and str(call_id).strip():
            out[str(call_id).strip()] = ev
    return out


def _find_evaluation_for_call(call: dict, evaluation_index: dict[str, dict]) -> dict | None:
    for candidate in _call_id_candidates(call):
        if candidate in evaluation_index:
            return evaluation_index[candidate]
    return None


def _is_primary_ucc_call(call: dict) -> bool:
    return call.get("classified_type") == "ucc_handled"


def _is_maintenance_call(call: dict) -> bool:
    if not isinstance(call, dict):
        return False
    if call.get("classified_type") == "maintenance_direct":
        return True
    if str(call.get("line_id") or "").strip() == "785175":
        return True
    line_name = str(call.get("line_name") or "")
    if _is_maintenance_ivr(line_name):
        return True
    branch = str(call.get("ivr_branch") or "")
    return bool(branch) and _is_maintenance_ivr(branch)


def _is_maintenance_ivr(branch: str) -> bool:
    key = _normalize_key(branch)
    return any(token in key for token in ("maintenance", "mes", "supervision", "technique"))


def _is_drv_crf_ivr(branch: str) -> bool:
    key = _normalize_key(branch)
    return "drv" in key or "crf" in key or "formulaire" in key


def _is_b2b_ivr(branch: str) -> bool:
    key = _normalize_key(branch)
    return "b2b" in key or "key2" in key


def _repeat_call_resolution_stats(calls: list[dict]) -> dict:
    by_number: dict[str, list[dict]] = {}
    for call in calls or []:
        number = call.get("from_number") or call.get("customer_number")
        if not number or _is_internal_number(number):
            continue
        by_number.setdefault(str(number), []).append(call)

    repeat_entries = []
    eventually_answered = 0
    never_answered = 0
    for number, bucket in by_number.items():
        if len(bucket) < 2:
            continue
        answered = any(c.get("answered") == "Yes" for c in bucket)
        if answered:
            eventually_answered += 1
        else:
            never_answered += 1
        repeat_entries.append((number, len(bucket), answered))

    repeat_entries.sort(key=lambda row: row[1], reverse=True)
    return {
        "entries": repeat_entries,
        "eventually_answered": eventually_answered,
        "never_answered": never_answered,
    }


def _format_call_started_at(call: dict) -> str | None:
    raw = call.get("call_started_at")
    if raw in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(raw)).strftime("%d/%m %H:%M")
    except (TypeError, ValueError, OSError):
        return None


def _best_issue_label(ev: dict | None) -> str | None:
    if not ev:
        return None
    errors = ev.get("errors") or []
    if errors:
        text = _normalize_issue_text(errors[0])
        if text:
            return text
    alerts = ev.get("alerts") or []
    if alerts:
        first = alerts[0]
        if isinstance(first, dict):
            text = _normalize_issue_text(first.get("message"))
        else:
            text = _normalize_issue_text(first)
        if text:
            return text
    return None


def _customer_call_reason(ev: dict | None) -> str | None:
    if not ev:
        return None
    text = _normalize_issue_text(ev.get("customer_call_reason"))
    return text or None


def _display_agent_name(value) -> str | None:
    text = " ".join(str(value or "").strip().split())
    if not text or text in {"?", "[No associated user]", "N/A"}:
        return None
    return text


def _best_call_reason(call: dict, ev: dict | None) -> str:
    customer_reason = _customer_call_reason(ev)
    if customer_reason:
        return f"raison d'appel : {customer_reason}"
    issue = _best_issue_label(ev)
    if issue:
        return issue
    return "raison d'appel indisponible"


def _build_transcript_reason_summary(analysis: dict) -> list[tuple[str, int]]:
    counts = Counter()
    for ev in analysis.get("call_evaluations", []) or []:
        if not isinstance(ev, dict):
            continue
        reason = _customer_call_reason(ev)
        if not reason:
            continue
        counts[reason] += 1
    return counts.most_common(5)


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


def _format_transfer_summary(call: dict) -> str | None:
    if call.get("classified_type") not in {"warm_transfer", "ucc_transfer_handled"}:
        return None
    transfer = call_fetcher.summarize_transfer_context(call)
    if not transfer:
        return "warm transfer : détail indisponible"
    if transfer.get("pre_transfer_seconds") is not None:
        pre = _format_duration(transfer.get("pre_transfer_seconds"))
        target = transfer.get("transfer_target_name") or "cible inconnue"
        return f"avant transfert {pre} vers {target}"
    if transfer.get("transfer_detected"):
        target = transfer.get("transfer_target_name") or "cible inconnue"
        return f"transfert détecté vers {target}"
    return "warm transfer non confirmé"


def _compact_alert_lines(actionable_items: list[dict], max_lines: int = 5) -> list[str]:
    """Lignes 'à regarder' du post compact : seulement priorités critical/warning."""
    lines: list[str] = []
    for item in actionable_items or []:
        pr = item.get("priority")
        if pr not in ("critical", "warning"):
            continue
        icon = "🔴" if pr == "critical" else "🟡"
        desc = (item.get("description") or item.get("label") or "").strip()
        if not desc:
            continue
        ids = item.get("representative_call_ids") or item.get("call_ids") or []
        links = " ".join(_aircall_link(c) for c in ids[:3] if c)
        lines.append(f"{icon} {desc}" + (f" — {links}" if links else ""))
        if len(lines) >= max_lines:
            break
    return lines


def build_slack_blocks_compact(analysis: dict, mode: str, date: datetime,
                               calls: list[dict] = None,
                               ucc_calls: list[dict] = None,
                               qa_calls: list[dict] = None) -> list[dict]:
    """Post Slack 'exception-based' (chantier A) : ≤10 blocs, lisible mobile.
    Header + config, 1 bloc KPIs (n affiché, ⚪ si n<10), 1 bloc 'à regarder'
    (warning/critical, max 5, sinon RAS), 1 bloc liens. Le détail vit dans
    Markdown/Notion/cockpit."""
    scores = analysis.get("scores", {})
    kpis   = analysis.get("kpis", {})
    meta   = analysis.get("analysis_meta", {})
    actionable_items = analysis.get("actionable_items") or report_formatter.build_actionable_items(analysis)
    analysis["actionable_items"] = actionable_items

    label   = "Quotidien" if mode == "daily" else "Hebdomadaire"
    date_str = date.strftime("%d/%m/%Y")
    ucc_score = scores.get("ucc_quality_score", "?")
    drv_score = scores.get("driveco_care_score", "?")
    ucc_n = scores.get("ucc_evaluated_calls")
    drv_n = scores.get("driveco_care_evaluated_calls")
    answer_rate = kpis.get("answer_rate_pct", kpis.get("pickup_rate_pct"))
    abandon     = kpis.get("abandon_rate_pct")
    escalations = kpis.get("escalations_count", 0)
    analyzed = meta.get("analyzed_calls")
    eligible = meta.get("eligible_calls")

    # Couverture honnête : si partielle (run dégradé / rattrapage en cours).
    coverage_note = ""
    try:
        if analyzed is not None and eligible and int(analyzed) < int(eligible):
            coverage_note = f"\n_{analyzed}/{eligible} analysés — rattrapage en cours dans la journée._"
    except (TypeError, ValueError):
        pass

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📊 QA Driveco — {label} {date_str}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"⚙️ {config.runtime_config_summary()}"}]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Score UCC* {_score_icon_n(ucc_score, ucc_n)}\n`{_score_text_n(ucc_score, ucc_n)}`"},
            {"type": "mrkdwn", "text": f"*Score Driveco* {_score_icon_n(drv_score, drv_n)}\n`{_score_text_n(drv_score, drv_n)}`"},
            {"type": "mrkdwn", "text": f"*Answer rate* {_kpi_icon(answer_rate, 'answer_rate_pct')}\n{answer_rate if answer_rate is not None else 'n/a'}%"},
            {"type": "mrkdwn", "text": f"*Abandon* {_kpi_icon(abandon, 'abandon_rate_pct')}\n{abandon if abandon is not None else 'n/a'}%"},
            {"type": "mrkdwn", "text": f"*Escalades*\n{escalations}"},
        ]},
    ]
    if coverage_note:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": coverage_note.strip()}]})

    alert_lines = _compact_alert_lines(actionable_items, max_lines=5)
    body = "\n".join(alert_lines) if alert_lines else "✅ RAS — rien de critique aujourd'hui."
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*🚨 À regarder aujourd'hui*\n{body}"}})

    # Liens (Notion · cockpit · Markdown) — conditionnels.
    link_parts = []
    notion_url = analysis.get("notion_url") or meta.get("notion_url")
    if notion_url:
        link_parts.append(f"<{notion_url}|Notion>")
    if config.COCKPIT_BASE_URL:
        link_parts.append(f"<{config.COCKPIT_BASE_URL}/qa/runs|Cockpit>")
    link_parts.append(f"Markdown : `{date.strftime('%Y-%m-%d')}_daily_report.md`")
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(link_parts)}]})
    return blocks


def build_slack_blocks(analysis: dict, mode: str, date: datetime,
                       calls: list[dict] = None,
                       ucc_calls: list[dict] = None,
                       qa_calls: list[dict] = None) -> list[dict]:
    """Construit les blocs Slack détaillés. Pour le daily, send_slack_notification
    découpe ensuite en post principal + compléments en fil (chantier A v2)."""
    scores = analysis.get("scores", {})
    kpis   = analysis.get("kpis", {})
    alerts = analysis.get("alerts", [])
    kb     = analysis.get("kb_gaps", {})
    meta   = analysis.get("analysis_meta", {})
    issues = analysis.get("top_issues", [])
    recs   = analysis.get("recommendations", [])
    evaluation_index = _build_evaluation_index(analysis)
    actionable_items = analysis.get("actionable_items") or report_formatter.build_actionable_items(analysis)
    analysis["actionable_items"] = actionable_items

    ucc_score = scores.get("ucc_quality_score", "?")
    drv_score = scores.get("driveco_care_score", "?")
    # Effectif réellement évalué par scope (chantier 0.5 : ⚪+n si trop peu d'appels).
    ucc_n_eval = scores.get("ucc_evaluated_calls")
    drv_n_eval = scores.get("driveco_care_evaluated_calls")
    label     = "Quotidien" if mode == "daily" else "Hebdomadaire"
    date_str  = date.strftime("%d/%m/%Y")

    # KPIs globaux — labels harmonisés avec la terminologie Aircall (Inbounds,
    # Answer rate). "Answer rate" est calculé sur les appels décrochables
    # (hors call deflector et abandons IVR) — cf. metrics_builder._is_call_answerable.
    total    = kpis.get("calls_presented", 0)
    answered = kpis.get("calls_answered", 0)
    pickup   = kpis.get("pickup_rate_pct", 0)
    overflow = kpis.get("overflow_rate_pct", 0)
    abandon  = kpis.get("abandon_rate_pct", 0)
    avg_dur  = kpis.get("avg_duration_seconds", 0)
    answerable       = kpis.get("answerable_calls", total)
    answer_rate      = kpis.get("answer_rate_pct", pickup)
    # Ventilation par ligne Aircall
    assist_inbounds  = kpis.get("assistance_line_calls_presented", 0)
    assist_answerable = kpis.get("assistance_line_answerable", 0)
    assist_answered  = kpis.get("assistance_line_answered", 0)
    assist_rate      = kpis.get("assistance_line_answer_rate_pct", 0)
    assist_avg_dur   = kpis.get("assistance_line_avg_duration_seconds", 0)
    transfer_inbounds    = kpis.get("transfer_line_calls_presented", 0)
    transfer_answerable  = kpis.get("transfer_line_answerable", 0)
    transfer_answered_kpi = kpis.get("transfer_line_answered", 0)
    transfer_rate        = kpis.get("transfer_line_answer_rate_pct", 0)
    transfer_avg_dur     = kpis.get("transfer_line_avg_duration_seconds", 0)
    escalations = kpis.get("escalations_count", 0)
    warm_transfers = kpis.get("warm_transfer_count", 0)
    analyzed_calls = meta.get("analyzed_calls")
    eligible_calls = meta.get("eligible_calls")
    eligible_ucc_calls = meta.get("eligible_ucc_calls")
    eligible_driveco_calls = meta.get("eligible_driveco_calls")
    analyzed_ucc_calls = meta.get("analyzed_ucc_calls")
    analyzed_driveco_calls = meta.get("analyzed_driveco_calls")
    transcript_calls = meta.get("transcript_calls")
    transcript_rate = meta.get("transcript_rate_pct")
    actual_coverage = meta.get("actual_coverage_pct")
    target_coverage = meta.get("target_coverage_pct")
    llm_usage = meta.get("llm_usage") or {}
    transfer_total = kpis.get("transfer_line_total_count", 0)
    transfer_answered = kpis.get("transfer_line_answered_count", 0)
    transfer_missed = kpis.get("transfer_line_missed_count", 0)
    peak_windows = kpis.get("peak_windows", []) or []
    assistance_presented = kpis.get("assistance_line_calls_presented", 0)
    assistance_charging_count = kpis.get("assistance_line_charging_assistance_count", 0)
    assistance_charging_pct = kpis.get("assistance_line_charging_assistance_pct", 0)
    transfer_presented = kpis.get("transfer_line_calls_presented", 0)
    transfer_pickup_pct = kpis.get("transfer_line_pickup_rate_pct", 0)
    assistance_scope_calls = [c for c in (calls or []) if c.get("line_id") == config.AIRCALL_ASSISTANCE_LINE_ID]
    qa_scope_calls = qa_calls or ucc_calls or []

    blocks: list[dict] = [
        # ── Header ──────────────────────────────────────────────────────────
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📊 Analyse Appels Driveco — {label} {date_str}"},
        },
        # (La config effective n'est PAS affichée dans le post Slack — lecteurs
        # métier. Elle reste loggée côté pipeline via [run-config].)
        # ── Scores QA ───────────────────────────────────────────────────────
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Score UCC* {_score_icon_n(ucc_score, ucc_n_eval)}\n`{_score_text_n(ucc_score, ucc_n_eval)}`"},
                {"type": "mrkdwn", "text": f"*Score Driveco Care* {_score_icon_n(drv_score, drv_n_eval)}\n`{_score_text_n(drv_score, drv_n_eval)}`"},
            ],
        },
        # ── KPIs globaux (tous périmètres confondus) ────────────────────────
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Inbounds*\n{total}"},
                {"type": "mrkdwn", "text": f"{_kpi_icon(answer_rate, 'pickup_rate')} *Answer rate*\n{answer_rate}% ({answered}/{answerable} décrochables)"},
                {"type": "mrkdwn", "text": f"*Durée moyenne*\n{_format_duration(avg_dur)}"},
                # Abandon = total non-décrochés / total inbounds (inclut deflector
                # et abandons IVR — base différente de l'Answer rate).
                {"type": "mrkdwn", "text": f"{_kpi_icon(abandon, 'abandon_rate')} *Abandon (sur total inbounds)*\n{abandon}% — {total - answered}/{total}"},
                {"type": "mrkdwn", "text": f"*Escalades détectées*\n{escalations} (tags UCC : {warm_transfers})"},
            ],
        },
        # ── Ligne Assistance Driveco ────────────────────────────────────────
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*📞 Ligne Assistance Driveco*"},
            "fields": [
                {"type": "mrkdwn", "text": f"*Inbounds*\n{assist_inbounds}"},
                {"type": "mrkdwn", "text": f"*Answer rate*\n{assist_rate}% ({assist_answered}/{assist_answerable})"},
                {"type": "mrkdwn", "text": f"*Durée moyenne*\n{_format_duration(assist_avg_dur)}"},
                {"type": "mrkdwn", "text": f"*Transférés vers UCC (IVR charging)*\n{assistance_charging_count} — {assistance_charging_pct}%"},
            ],
        },
        # ── Ligne Driveco UCC transfert ─────────────────────────────────────
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*🔁 Ligne Driveco UCC transfert*"},
            "fields": [
                {"type": "mrkdwn", "text": f"*Inbounds*\n{transfer_inbounds}"},
                {"type": "mrkdwn", "text": f"*Answer rate*\n{transfer_rate}% ({transfer_answered_kpi}/{transfer_answerable})"},
                {"type": "mrkdwn", "text": f"*Durée moyenne*\n{_format_duration(transfer_avg_dur)}"},
            ],
        },
        # ── Appels éligibles QA / analysés / couverture transcripts ─────────
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Éligibles QA*\n{eligible_calls if eligible_calls is not None else 'n/a'} appel(s) (UCC {eligible_ucc_calls if eligible_ucc_calls is not None else 'n/a'} / Driveco {eligible_driveco_calls if eligible_driveco_calls is not None else 'n/a'})"},
                {"type": "mrkdwn", "text": f"*Analysés / couverture*\n{analyzed_calls if analyzed_calls is not None else 'n/a'} appel(s) — {actual_coverage if actual_coverage is not None else 'n/a'}% / cible {target_coverage if target_coverage is not None else 'n/a'}% (UCC {analyzed_ucc_calls if analyzed_ucc_calls is not None else 'n/a'} / Driveco {analyzed_driveco_calls if analyzed_driveco_calls is not None else 'n/a'})"},
                {"type": "mrkdwn", "text": f"*Transcripts exploitables*\n{transcript_calls if transcript_calls is not None else 'n/a'} ({transcript_rate if transcript_rate is not None else 'n/a'}%)"},
            ],
        },
    ]
    # ── 🚨 À regarder aujourd'hui (exceptions critical/warning) — reste dans le
    # post PRINCIPAL (avant le 1er divider) ; le détail part en thread. ──────────
    _alert_lines = _compact_alert_lines(actionable_items, max_lines=5)
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*🚨 À regarder aujourd'hui*\n" + (
            "\n".join(_alert_lines) if _alert_lines else "✅ RAS — rien de critique aujourd'hui.")},
    })
    blocks.append({"type": "divider"})

    # ── Routage IVR ─────────────────────────────────────────────────────────
    ivr_scope_calls = [c for c in assistance_scope_calls if not _is_maintenance_call(c)]
    if ivr_scope_calls:
        ivr_counts = Counter(
            c.get("ivr_branch")
            for c in ivr_scope_calls
            if c.get("ivr_branch")
            and not _is_maintenance_ivr(c.get("ivr_branch"))
            and not _is_drv_crf_ivr(c.get("ivr_branch"))
            and not _is_b2b_ivr(c.get("ivr_branch"))
        )
        pre_ivr_abandon = sum(
            1 for c in ivr_scope_calls
            if c.get("answered") == "No" and not str(c.get("ivr_branch") or "").strip()
        )
        drv_crf_count = sum(1 for c in ivr_scope_calls if _is_drv_crf_ivr(c.get("ivr_branch") or ""))
        b2b_calls = [c for c in ivr_scope_calls if _is_b2b_ivr(c.get("ivr_branch") or "")]
        b2b_count = len(b2b_calls)
        b2b_pickup_pct = round(sum(1 for c in b2b_calls if c.get("answered") == "Yes") / max(1, b2b_count) * 100, 1) if b2b_count else 0.0
        ivr_lines = [f"• *Abandons avant choix IVR* — {pre_ivr_abandon} appel(s)"]
        ivr_lines.append(f"• *Formulaire DRV&CRF* — {drv_crf_count} appel(s)")
        ivr_lines.append(f"• *B2B* — {b2b_count} appel(s) ({b2b_pickup_pct}% décrochés par Driveco)")
        for branch, cnt in ivr_counts.most_common(3):
            ivr_lines.append(f"• `{branch}` — {cnt} appel(s)")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Routage IVR :*\n" + "\n".join(ivr_lines)},
        })
        blocks.append({"type": "divider"})

    transcript_reasons = _build_transcript_reason_summary(analysis)
    if mode != "daily" and transcript_reasons:
        reason_lines = [f"• {label} — {count} occurrence(s)" for label, count in transcript_reasons]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Pourquoi les clients ont appelé (transcripts) :*\n" + "\n".join(reason_lines)},
        })
        blocks.append({"type": "divider"})

    voc_summary = analysis.get("voc_summary") or {}
    call_reasons = voc_summary.get("call_reasons") or []
    top_topics = voc_summary.get("top_topics") or []
    opportunities = voc_summary.get("opportunities") or []
    best_practices = voc_summary.get("best_practices") or []
    competitors = voc_summary.get("competitors") or []
    # Bloc principal : on privilégie les raisons d'appel granulaires. Les
    # top_topics restent en fallback pour les anciens rapports sans call_reasons.
    reason_lines = _format_call_reason_lines(call_reasons)
    if not reason_lines and top_topics:
        reason_lines = [
            f"• *{item.get('label') or item.get('topic_code')}* — {item.get('count', 0)} mention(s)"
            for item in top_topics[:6]
        ]
    if reason_lines:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Raisons d’appel :*\n" + "\n".join(reason_lines)},
        })
        blocks.append({"type": "divider"})

    if opportunities:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*💡 Opportunités détectées :*\n" + "\n".join(
                f"• {item.get('description')} — {item.get('count', 0)} occurrence(s)" for item in opportunities[:5]
            )},
        })
        blocks.append({"type": "divider"})

    if best_practices:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*✨ Bonnes pratiques agents :*\n" + "\n".join(
                f"• Agent anonymisé — « {item.get('quote')} »" for item in best_practices[:3]
            )},
        })
        blocks.append({"type": "divider"})

    if competitors:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*👀 Concurrents cités :*\n" + "\n".join(
                f"• {item.get('competitor_name')} — {item.get('count', 0)} mention(s)" for item in competitors[:4]
            )},
        })
        blocks.append({"type": "divider"})

    # ── Clients frustrés (appels répétés) ────────────────────────────────────
    if assistance_scope_calls:
        repeat_stats = _repeat_call_resolution_stats(assistance_scope_calls)
        repeat = repeat_stats["entries"]
        if repeat:
            repeat_lines = "\n".join([
                f"• `{num}` — {cnt}x — {'décroché au moins une fois' if answered else 'jamais décroché'}"
                for num, cnt, answered in repeat[:5]
            ])
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn",
                         "text": (
                             f"*⚠️ Clients frustrés ({len(repeat)} numéros, 2+ appels) :*\n"
                             f"{repeat_lines}\n"
                             f"_Bilan : {repeat_stats['eventually_answered']} finalement décrochés / "
                             f"{repeat_stats['never_answered']} jamais décrochés_"
                         )},
            })

    # ── Pics d'appels ───────────────────────────────────────────────────────
    if peak_windows:
        peak_lines = [
            f"• *{window.get('label', '?')}* — {window.get('count', 0)} appel(s)"
            for window in peak_windows[:3]
        ]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Pics d'appels (top 3 fenêtres de 2h) :*\n" + "\n".join(peak_lines)},
        })
        blocks.append({"type": "divider"})

    # ── Appels longs UCC (≥ 15 min) ─────────────────────────────────────────
    if ucc_calls:
        threshold = config.LONG_CALL_THRESHOLD_SECONDS
        long_pool = [
            c for c in ucc_calls
            if c.get("answered") == "Yes" and (c.get("duration_in_call") or 0) >= threshold
        ]
        long_list = sorted(
            long_pool,
            key=lambda x: x.get("duration_in_call") or 0,
            reverse=True,
        )[:5]
        if long_pool:
            long_lines = []
            for c in long_list:
                cid  = c.get("call_id_internal") or c.get("call_id") or "?"
                dur  = c.get("duration_in_call") or 0
                mins = f"{dur // 60}min{dur % 60:02d}s"
                started_at = _format_call_started_at(c) or "date/heure indisponible"
                ev = _find_evaluation_for_call(c, evaluation_index)
                reason = _best_call_reason(c, ev)
                long_lines.append(f"• {_aircall_link(cid)} — {started_at} — {mins} — {reason}")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn",
                         "text": f"*Appels longs UCC (≥{threshold // 60}min) — total : {len(long_pool)}*\n" + "\n".join(long_lines)},
            })

    blocks.append({"type": "divider"})

    # ── Top 5 appels problématiques ─────────────────────────────────────────
    top_prob = analysis.get("top_problematic_calls", [])
    if top_prob:
        lines_prob = []
        limit = 3 if mode == "daily" else 5
        for ev in top_prob[:limit]:
            cid       = ev.get("call_id_internal") or ev.get("call_id", "?")
            score_txt = ""
            try:
                score_txt = f" — score {float(ev.get('score_global')):.1f}/10"
            except (TypeError, ValueError):
                score_txt = ""
            errors    = ev.get("errors", [])
            err_short = _normalize_issue_text(errors[0]) if errors else "problème non détaillé"
            kb_ico    = "❌" if ev.get("kb_compliance") == "non_conforme" else "⚠️"
            source_call = None
            for pool in (qa_scope_calls or [], calls or []):
                source_call = next(
                    (
                        c for c in pool
                        if str(c.get("call_id_internal") or c.get("call_id") or "").strip() == str(cid).strip()
                    ),
                    None,
                )
                if source_call:
                    break
            agent = _display_agent_name(ev.get("agent")) or _display_agent_name(ev.get("user_name"))
            if agent is None and source_call:
                agent = _display_agent_name(source_call.get("user_name"))
            duration_seconds = source_call.get("duration_in_call") if source_call else None
            duration_note = _format_duration(duration_seconds) if duration_seconds else None
            prefix_bits = [bit for bit in (agent, duration_note) if bit]
            prefix = f" — {' | '.join(prefix_bits)}" if prefix_bits else ""
            lines_prob.append(f"{kb_ico} *{_aircall_link(cid)}*{prefix}{score_txt} — {err_short}")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"*🚨 Top 5 appels problématiques :*\n" + "\n".join(lines_prob)},
        })

    # ── Alertes ─────────────────────────────────────────────────────────────
    alert_items = [item for item in actionable_items if item.get("priority") == "critical" and item.get("source") == "anomaly"]
    critical = [a for a in alerts if a.get("level") == "critical"]
    warnings = [a for a in alerts if a.get("level") == "warning"]
    if critical or warnings or alert_items:
        def _alert_with_links(prefix: str, message: str, call_ids: list) -> str:
            links = " ".join(_aircall_link(cid) for cid in (call_ids or []) if cid)
            suffix = f" — appels : {links}" if links else ""
            return f"{prefix} {message}{suffix}"

        alert_lines = [
            _alert_with_links("🔴", item.get("description") or "", item.get("representative_call_ids") or [])
            for item in alert_items[:5]
        ]
        alert_lines += [
            _alert_with_links("🔴", a.get("message") or "", a.get("call_ids") or [])
            for a in critical
        ]
        alert_lines += [
            _alert_with_links("🟡", a.get("message") or "", a.get("call_ids") or [])
            for a in warnings
        ]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Alertes :*\n" + "\n".join(alert_lines)},
        })

    # ── Knowledge Base gaps ─────────────────────────────────────────────────
    kb_items = [item for item in actionable_items if item.get("tag") == "kb"]
    if kb_items:
        kb_lines = [f"• {item.get('description')}" for item in kb_items[:5]]
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"*📚 KB :*\n" + "\n".join(kb_lines)},
        })

    coaching_items = [item for item in actionable_items if item.get("tag") == "coaching"]
    focus_items = [item for item in coaching_items if item.get("description") not in {x.get("description") for x in coaching_items[:5]}]
    if focus_items:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Focus coaching du jour :*\n" + "\n".join(
                f"• {item.get('description')}" for item in focus_items[:3]
            )},
        })

    if llm_usage:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": (
                    f"Usage API LLM : {llm_usage.get('anthropic_calls', 0)} appel(s) "
                    f"| input {llm_usage.get('anthropic_input_tokens', 0)} tok "
                    f"| output {llm_usage.get('anthropic_output_tokens', 0)} tok"
                ),
            }],
        })

    return blocks


def send_slack_notification(analysis: dict, mode: str, date: datetime,
                            calls: list[dict] = None,
                            ucc_calls: list[dict] = None,
                            qa_calls: list[dict] = None) -> bool:
    """Envoie le rapport dans #drv_ucc_ops. 1 seul envoi par jour (déduplication flag file)."""
    if _slack_already_sent("report", mode, date):
        print(f"[notifier] ℹ️  Slack {mode} {date.strftime('%Y-%m-%d')} déjà envoyé — ignoré")
        return True

    blocks   = build_slack_blocks(analysis, mode, date, calls=calls, ucc_calls=ucc_calls, qa_calls=qa_calls)
    fallback = f"Rapport {mode} Driveco {date.strftime('%d/%m/%Y')}"

    # Daily (chantier A v2) : post PRINCIPAL court (KPIs + lignes + à regarder),
    # puis compléments EN FIL (routage IVR, raisons, pics, appels longs, top
    # problématiques). L'hebdo reste un post détaillé unique.
    if mode == "daily":
        main_blocks, thread_groups = _split_main_and_threads(blocks)
        ok = _post_to_slack(main_blocks, text=fallback)
        if not ok:
            return ok
        _mark_slack_sent("report", mode, date)
        if isinstance(ok, str):
            try:
                import catchup_state
                catchup_state.save_daily_slack_ref(date, config.SLACK_CHANNEL_ID, ok)
            except Exception:  # noqa: BLE001
                pass
            for grp in thread_groups:
                _post_to_slack(grp, text=f"Détail {date.strftime('%d/%m/%Y')}", thread_ts=ok)
        return ok

    ok = _post_to_slack(blocks, text=fallback)
    if ok:
        _mark_slack_sent("report", mode, date)
    return ok


def _split_main_and_threads(blocks: list[dict], max_blocks_per_thread: int = 14):
    """Découpe les blocs détaillés en (post principal, [messages de fil]).
    Principal = tout ce qui précède le 1er divider (header, scores, KPIs globaux,
    lignes Assistance/Transfert, éligibles, à regarder). Le reste est regroupé par
    section (dividers) puis empaqueté en messages de fil lisibles."""
    first_div = next((i for i, b in enumerate(blocks) if b.get("type") == "divider"), len(blocks))
    main = [b for b in blocks[:first_div] if b.get("type") != "divider"]

    sections, cur = [], []
    for b in blocks[first_div:]:
        if b.get("type") == "divider":
            if cur:
                sections.append(cur)
                cur = []
        else:
            cur.append(b)
    if cur:
        sections.append(cur)

    threads, msg = [], []
    for sec in sections:
        if msg and len(msg) + len(sec) > max_blocks_per_thread:
            threads.append(msg)
            msg = []
        msg += sec
    if msg:
        threads.append(msg)
    return main, threads


def post_catchup_thread(date: datetime, text: str) -> bool:
    """Poste un message de complétion de couverture EN FIL du post quotidien
    (chantier 0.6). Si la référence du post est introuvable, poste à plat en repli."""
    import catchup_state
    ref = catchup_state.load_daily_slack_ref(date)
    block = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if ref:
        channel, ts = ref
        return bool(_post_to_slack(block, text=text, channel=channel, thread_ts=ts))
    return bool(_post_to_slack(block, text=text))


def send_alert(message: str, level: str = "warning") -> bool:
    """Envoie une alerte immédiate (ex : incident terrain détecté)."""
    icon = "🔴" if level == "critical" else "🟡"
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{icon} ALERTE — Driveco Assistance"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
        },
    ]
    return _post_to_slack(blocks, text=f"ALERTE : {message}", channel=config.SLACK_ALERT_CHANNEL_ID)


def send_voc_alerts(analysis: dict, mode: str, date: datetime) -> bool:
    summary = analysis.get("voc_summary") or {}
    call_reasons = summary.get("call_reasons") or []
    weak_signals = summary.get("weak_signals") or []
    if not weak_signals and not call_reasons:
        return True
    if _slack_already_sent("voc", mode, date):
        print(f"[notifier] ℹ️  Slack VoC {mode} {date.strftime('%Y-%m-%d')} déjà envoyé — ignoré")
        return True

    date_str = date.strftime("%d/%m/%Y")
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Raisons d'appel — {mode} {date_str}"},
        }
    ]
    reason_lines = _format_call_reason_lines(call_reasons, limit=8)
    if reason_lines:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Raisons d’appel principales :*\n" + "\n".join(reason_lines),
                },
            }
        )
    if weak_signals:
        if reason_lines:
            blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Signaux faibles détectés :*\n" + "\n".join(
                        f"• `{item.get('topic_code')}` — {item.get('count', 0)} mention(s)"
                        for item in weak_signals[:5]
                    ),
                },
            }
        )
    ok = _post_to_slack(
        blocks,
        text=f"Raisons d'appel {mode} {date_str}",
        channel=config.SLACK_VOC_ALERTS_CHANNEL_ID,
    )
    if ok:
        _mark_slack_sent("voc", mode, date)
    return ok


def send_anomaly_alerts(analysis: dict, date: datetime) -> bool:
    anomalies = analysis.get("anomalies") or []
    if not anomalies:
        return True
    if _slack_already_sent("anomaly", "daily", date):
        print(f"[notifier] ℹ️  Slack anomalies {date.strftime('%Y-%m-%d')} déjà envoyé — ignoré")
        return True
    lines = []
    for item in anomalies[:5]:
        label = "#anomaly"
        agent_suffix = f" / {item.get('agent_id')}" if item.get("agent_id") else ""
        reps = ", ".join(f"`{call_id}`" for call_id in (item.get("representative_call_ids") or [])[:3]) or "n/a"
        lines.append(
            f"• {label} *{item.get('metric')}* sur `{item.get('scope')}`{agent_suffix} "
            f"(z={item.get('z_score')}, valeur={item.get('current_value')}, base={item.get('baseline_mean')}) — appels: {reps}"
        )
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Anomalies KPI — {date.strftime('%d/%m/%Y')}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        },
    ]
    ok = _post_to_slack(blocks, text=f"Anomalies KPI {date.strftime('%d/%m/%Y')}")
    if ok:
        _mark_slack_sent("anomaly", "daily", date)
    return ok


def save_report(
    report_md: str,
    date: datetime,
    mode: str,
    filename_suffix: str | None = None,
    notion_title_prefix: str | None = None,
    metrics: dict | None = None,
    analysis: dict | None = None,
) -> Path:
    """
    Sauvegarde le rapport en local + Google Drive + Notion.
    Retourne le chemin local du fichier.
    """
    suffix = f"_{filename_suffix}" if filename_suffix else ""
    filename = f"{date.strftime('%Y-%m-%d')}_{mode}_report{suffix}.md"
    path = OUTPUT / filename
    path.write_text(report_md, encoding="utf-8")
    print(f"[notifier] 💾 Local → {path}")

    if config.DISABLE_EXTERNAL_PUBLISH:
        print("[notifier] ℹ️  Publications externes désactivées par config")
        return path

    # Upload Google Drive (silencieux si credentials manquants)
    gdrive_link = gdrive_uploader.upload_report(path, report_type=mode)
    if gdrive_link:
        print(f"[notifier] ☁️  Drive → {gdrive_link}")

    # Export Notion (silencieux si API key manquante)
    notion_reporter.save_report_to_notion(report_md, date, mode, title_prefix=notion_title_prefix)

    # Export Obsidian (silencieux si vault introuvable ou désactivé)
    try:
        obsidian_path = _publish_to_obsidian(report_md, date, mode, filename_suffix)
        if obsidian_path:
            print(f"[notifier] 📓 Obsidian → {obsidian_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"[notifier] ⚠️  Export Obsidian échoué : {exc}")

    return path


def _publish_to_obsidian(
    report_md: str,
    date: datetime,
    mode: str,
    filename_suffix: str | None = None,
) -> Path | None:
    """Écrit le rapport dans le vault Obsidian sous `<vault>/<subdir>/<Mode>/`.

    Renvoie None si désactivé ou si le vault n'existe pas. Ajoute un frontmatter
    YAML (date, type, tags) pour faciliter les requêtes et vues Obsidian.
    """
    if getattr(config, "DISABLE_OBSIDIAN_PUBLISH", False):
        return None
    vault = getattr(config, "OBSIDIAN_VAULT_DIR", None)
    if not vault or not Path(vault).exists():
        return None

    mode_label = {"daily": "Daily", "weekly": "Weekly"}.get(mode, mode.capitalize())
    subdir = getattr(config, "OBSIDIAN_REPORTS_SUBDIR", "Driveco QA") or "Driveco QA"
    target_dir = Path(vault) / subdir / mode_label
    target_dir.mkdir(parents=True, exist_ok=True)

    suffix = f" — {filename_suffix}" if filename_suffix else ""
    filename = f"{date.strftime('%Y-%m-%d')} — Driveco QA {mode_label}{suffix}.md"
    target_path = target_dir / filename

    frontmatter = (
        "---\n"
        f"date: {date.strftime('%Y-%m-%d')}\n"
        f"type: qa-report\n"
        f"mode: {mode}\n"
        f"tags: [driveco, qa, {mode}]\n"
        "---\n\n"
    )
    target_path.write_text(frontmatter + report_md, encoding="utf-8")
    return target_path
