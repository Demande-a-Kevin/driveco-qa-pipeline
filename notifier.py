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

OUTPUT = config.REPORT_OUTPUT_DIR

_SLACK_API_URL = "https://slack.com/api/chat.postMessage"
_AIRCALL_ASSET_BASE = "https://asset.aircall.io/calls"
_ISSUE_TYPE_LABELS = {
    "manque_d_empathie": "Manque d'empathie",
    "mauvaise_qualification_b2b_b2c": "Mauvaise qualification B2B/B2C",
    "manque_de_connaissance_du_client_sur_les_conditions_d_heure_gratuite": "Manque de clarté sur les conditions d'heure gratuite",
}


def _post_to_slack(blocks: list[dict], text: str = "", channel: str | None = None) -> bool:
    """Envoie un message Slack via l'API HTTP directe (bot token). Retourne True si succès."""
    if config.DISABLE_SLACK_NOTIFICATIONS:
        print("[notifier] ℹ️  Slack désactivé par config — envoi ignoré")
        return True
    token = config.SLACK_BOT_TOKEN
    target_channel = channel or config.SLACK_CHANNEL_ID
    if not token:
        print("[notifier] ⚠️  SLACK_BOT_TOKEN non défini — envoi Slack ignoré")
        return False
    try:
        resp = requests.post(
            _SLACK_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "channel": target_channel,
                "blocks": blocks,
                "text": text,
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            print(f"[notifier] ✅ Slack envoyé → #{target_channel}")
            return True
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


def build_slack_blocks(analysis: dict, mode: str, date: datetime,
                       calls: list[dict] = None,
                       ucc_calls: list[dict] = None,
                       qa_calls: list[dict] = None) -> list[dict]:
    """Construit le message Slack enrichi avec Block Kit."""
    scores = analysis.get("scores", {})
    kpis   = analysis.get("kpis", {})
    alerts = analysis.get("alerts", [])
    kb     = analysis.get("kb_gaps", {})
    meta   = analysis.get("analysis_meta", {})
    issues = analysis.get("top_issues", [])
    recs   = analysis.get("recommendations", [])
    evaluation_index = _build_evaluation_index(analysis)

    ucc_score = scores.get("ucc_quality_score", "?")
    drv_score = scores.get("driveco_care_score", "?")
    label     = "Quotidien" if mode == "daily" else "Hebdomadaire"
    date_str  = date.strftime("%d/%m/%Y")

    # KPIs
    total    = kpis.get("calls_presented", 0)
    answered = kpis.get("calls_answered", 0)
    pickup   = kpis.get("pickup_rate_pct", 0)
    overflow = kpis.get("overflow_rate_pct", 0)
    abandon  = kpis.get("abandon_rate_pct", 0)
    avg_dur  = kpis.get("avg_duration_seconds", 0)
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
        # ── Scores QA ───────────────────────────────────────────────────────
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Score UCC* {_score_icon(ucc_score)}\n`{_score_text(ucc_score)}`"},
                {"type": "mrkdwn", "text": f"*Score Driveco Care* {_score_icon(drv_score)}\n`{_score_text(drv_score)}`"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Appels présentés*\n{total}"},
                {"type": "mrkdwn", "text": f"*Décrochés*\n{answered} ({pickup}%)"},
                {"type": "mrkdwn", "text": f"{_kpi_icon(overflow, 'overflow_rate')} *Overflow Aircall*\n{overflow}%"},
                {"type": "mrkdwn", "text": f"{_kpi_icon(abandon, 'abandon_rate')} *Abandon*\n{abandon}%"},
                {"type": "mrkdwn", "text": f"*Durée moyenne*\n{_format_duration(avg_dur)}"},
                {"type": "mrkdwn", "text": f"*Escalades détectées*\n{escalations} (tags UCC : {warm_transfers})"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Ligne assistance 785174*\n{assistance_presented} appel(s) entrants"},
                {"type": "mrkdwn", "text": f"*Transférés à UCC via IVR charging assistance*\n{assistance_charging_count} appel(s) — {assistance_charging_pct}%"},
                {"type": "mrkdwn", "text": f"*Ligne UCC transfert 1214611*\n{transfer_presented} appel(s) entrants"},
                {"type": "mrkdwn", "text": f"*Taux décroché ligne 1214611*\n{transfer_pickup_pct}%"},
                {"type": "mrkdwn", "text": f"*Éligibles QA*\n{eligible_calls if eligible_calls is not None else 'n/a'} appel(s) (UCC {eligible_ucc_calls if eligible_ucc_calls is not None else 'n/a'} / Driveco {eligible_driveco_calls if eligible_driveco_calls is not None else 'n/a'})"},
                {"type": "mrkdwn", "text": f"*Analysés / couverture*\n{analyzed_calls if analyzed_calls is not None else 'n/a'} appel(s) — {actual_coverage if actual_coverage is not None else 'n/a'}% / cible {target_coverage if target_coverage is not None else 'n/a'}% (UCC {analyzed_ucc_calls if analyzed_ucc_calls is not None else 'n/a'} / Driveco {analyzed_driveco_calls if analyzed_driveco_calls is not None else 'n/a'})"},
                {"type": "mrkdwn", "text": f"*Transcripts exploitables*\n{transcript_calls if transcript_calls is not None else 'n/a'} ({transcript_rate if transcript_rate is not None else 'n/a'}%)"},
            ],
        },
        {"type": "divider"},
    ]

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
    if transcript_reasons:
        reason_lines = [f"• {label} — {count} occurrence(s)" for label, count in transcript_reasons]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Pourquoi les clients ont appelé (transcripts) :*\n" + "\n".join(reason_lines)},
        })
        blocks.append({"type": "divider"})

    voc_summary = analysis.get("voc_summary") or {}
    top_topics = voc_summary.get("top_topics") or []
    weak_signals = voc_summary.get("weak_signals") or []
    if top_topics:
        topic_lines = [
            f"• *{item.get('label', item.get('topic_code'))}* — {item.get('count', 0)} mention(s)"
            for item in top_topics[:4]
        ]
        if weak_signals:
            weak_signal_line = ", ".join(
                f"{item.get('topic_code')} ({item.get('count', 0)})" for item in weak_signals[:3]
            )
            topic_lines.append(f"_Signaux faibles: {weak_signal_line}_")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Voix du client :*\n" + "\n".join(topic_lines)},
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
        for ev in top_prob[:5]:
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
    critical = [a for a in alerts if a.get("level") == "critical"]
    warnings = [a for a in alerts if a.get("level") == "warning"]
    if critical or warnings:
        alert_lines = (
            [f"🔴 {a.get('message')}" for a in critical] +
            [f"🟡 {a.get('message')}" for a in warnings]
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Alertes :*\n" + "\n".join(alert_lines)},
        })

    if issues:
        issue_lines = []
        for issue in issues[:3]:
            label = _normalize_issue_text(issue.get("issue"))
            count = issue.get("occurrences", "?")
            if label:
                issue_lines.append(f"• {label} — {count} occurrence(s)")
        if issue_lines:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Enseignements du jour :*\n" + "\n".join(issue_lines)},
            })

    # ── Knowledge Base gaps ─────────────────────────────────────────────────
    missing    = _normalize_kb_items(kb.get("missing", []), "missing")
    incomplete = _normalize_kb_items(kb.get("incomplete", []), "incomplete")
    to_revise  = _normalize_kb_items(kb.get("to_revise", []), "to_revise")
    total_gaps = len(missing) + len(incomplete) + len(to_revise)
    if total_gaps:
        kb_lines = (
            [f"➕ *Manquant :* {a}" for a in missing[:2]] +
            [f"✏️ *Incomplet :* {a}" for a in incomplete[:2]] +
            [f"🔄 *À réviser :* {a}" for a in to_revise[:2]]
        )
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"*📚 KB — {total_gaps} gap(s) identifié(s) :*\n" + "\n".join(kb_lines)},
        })

    if recs:
        rec_lines = [f"• {_normalize_issue_text(rec)}" for rec in recs[:3] if _normalize_issue_text(rec)]
        if rec_lines:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Actions recommandées :*\n" + "\n".join(rec_lines)},
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
    # Déduplication : on ne poste qu'une fois par jour par mode
    flag_file = OUTPUT / f".slack_sent_{mode}_{date.strftime('%Y-%m-%d')}.flag"
    if flag_file.exists():
        print(f"[notifier] ℹ️  Slack {mode} {date.strftime('%Y-%m-%d')} déjà envoyé — ignoré")
        return True

    blocks   = build_slack_blocks(analysis, mode, date, calls=calls, ucc_calls=ucc_calls, qa_calls=qa_calls)
    fallback = f"Rapport {mode} Driveco {date.strftime('%d/%m/%Y')}"
    ok = _post_to_slack(blocks, text=fallback)
    if ok:
        flag_file.touch()
    return ok


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
    return _post_to_slack(blocks, text=f"ALERTE : {message}")


def send_voc_alerts(analysis: dict, mode: str, date: datetime) -> bool:
    summary = analysis.get("voc_summary") or {}
    weak_signals = summary.get("weak_signals") or []
    churn_risk_calls = summary.get("churn_risk_calls") or []
    if not weak_signals and not churn_risk_calls:
        return True

    date_str = date.strftime("%d/%m/%Y")
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Voix du client — {mode} {date_str}"},
        }
    ]
    if weak_signals:
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
    if churn_risk_calls:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Risque churn :*\n" + "\n".join(
                        f"• Appel `{item.get('call_id', '?')}` — risque *{item.get('risk')}* — « {item.get('quote') or 'verbatim indisponible'} »"
                        for item in churn_risk_calls[:5]
                    ),
                },
            }
        )
    return _post_to_slack(
        blocks,
        text=f"Voix du client {mode} {date_str}",
        channel=config.SLACK_VOC_ALERTS_CHANNEL_ID,
    )


def send_anomaly_alerts(analysis: dict, date: datetime) -> bool:
    anomalies = analysis.get("anomalies") or []
    if not anomalies:
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
    return _post_to_slack(blocks, text=f"Anomalies KPI {date.strftime('%d/%m/%Y')}")


def save_report(report_md: str, date: datetime, mode: str) -> Path:
    """
    Sauvegarde le rapport en local + Google Drive + Notion.
    Retourne le chemin local du fichier.
    """
    filename = f"{date.strftime('%Y-%m-%d')}_{mode}_report.md"
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
    notion_reporter.save_report_to_notion(report_md, date, mode)

    return path
