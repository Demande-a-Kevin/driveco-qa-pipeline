"""
metrics_builder.py — Calcule les KPIs à partir des appels classifiés.
"""
import re
from collections import Counter
from datetime import datetime
from statistics import mean, pstdev
try:
    from zoneinfo import ZoneInfo
    _PARIS = ZoneInfo("Europe/Paris")
except ImportError:
    import pytz
    _PARIS = pytz.timezone("Europe/Paris")
import config
import persistence
import voc_taxonomy


def _icon(value: float, threshold: dict) -> str:
    green  = threshold["green"]
    yellow = threshold["yellow"]
    hib    = threshold["higher_is_better"]
    if hib:
        return "🟢" if value >= green else "🟡" if value >= yellow else "🔴"
    else:
        return "🟢" if value <= green else "🟡" if value <= yellow else "🔴"


def _parse_call_timestamp(call: dict) -> int | None:
    raw = call.get("call_started_at")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _compute_peak_windows(calls: list[dict]) -> list[dict]:
    window_seconds = max(1, int(config.PEAK_WINDOW_SECONDS))
    buckets: Counter[int] = Counter()
    for call in calls:
        ts = _parse_call_timestamp(call)
        if ts is None:
            continue
        buckets[int(ts // window_seconds)] += 1

    peak_windows = []
    for bucket, count in buckets.items():
        start_ts = bucket * window_seconds
        end_ts = start_ts + window_seconds
        start_dt = datetime.fromtimestamp(start_ts, tz=_PARIS)
        end_dt = datetime.fromtimestamp(end_ts, tz=_PARIS)
        peak_windows.append({
            "bucket": bucket,
            "count": count,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "start_local": start_dt.strftime("%H:%M"),
            "end_local": end_dt.strftime("%H:%M"),
            "label": f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}",
        })

    peak_windows.sort(key=lambda item: (-item["count"], item["start_ts"]))
    return peak_windows[:max(1, int(config.PEAK_WINDOWS_TOP_N))]


def _safe_pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


# Règle "Answer rate réel" : on exclut du dénominateur les appels qui n'ont
# jamais eu une chance d'être décrochés par un agent (call deflector, abandon
# dans l'IVR avant d'atteindre la file, hors horaires d'ouverture, abandons
# quasi-instantanés < 5s). Référence : champs Aircall `ivr_branch` (key_3 /
# "deflect" = message pré-enregistré) et `missed_call_reason`.
_NOT_ANSWERABLE_MISSED_REASONS = {
    "abandoned_in_ivr",
    "short_abandoned",
    "out_of_opening_hours",
}


def _is_call_deflected(call: dict) -> bool:
    ivr = str(call.get("ivr_branch") or "").lower()
    return "deflect" in ivr or "key_3" in ivr


def _is_call_answerable(call: dict) -> bool:
    """True si l'appel a pu atteindre la file agent (décrochable)."""
    if _is_call_deflected(call):
        return False
    reason = str(call.get("missed_call_reason") or "").lower()
    if reason in _NOT_ANSWERABLE_MISSED_REASONS:
        return False
    # Appel raccroché en < 5s sans tentative = non décrochable (client ou réseau)
    if call.get("answered") != "Yes":
        wait = int(call.get("waiting_time") or 0)
        if wait and wait < 5 and not reason:
            return False
    return True


def _line_kpis(line_calls: list[dict]) -> dict:
    """Retourne les KPIs (Inbounds, Answer rate, Durée moy) d'une ligne donnée."""
    presented = len(line_calls)
    answerable = [c for c in line_calls if _is_call_answerable(c)]
    answered = [c for c in line_calls if c.get("answered") == "Yes"]
    answered_amongst_answerable = [c for c in answerable if c.get("answered") == "Yes"]
    durations = [c.get("duration_in_call") or 0 for c in answered if (c.get("duration_in_call") or 0) > 0]
    return {
        "presented": presented,
        "answerable": len(answerable),
        "answered": len(answered),
        "answer_rate_pct": _safe_pct(len(answered_amongst_answerable), len(answerable)),
        "avg_duration_seconds": round(sum(durations) / len(durations)) if durations else 0,
    }


def _compute_long_ucc_calls(calls: list[dict]) -> tuple[int, list[dict]]:
    threshold = max(1, int(config.LONG_CALL_THRESHOLD_SECONDS))
    ucc_types = {"ucc_handled", "warm_transfer"}
    long_pool = [
        c for c in calls
        if c.get("classified_type") in ucc_types
        and c.get("answered") == "Yes"
        and (c.get("duration_in_call") or 0) >= threshold
    ]
    long_pool.sort(key=lambda call: call.get("duration_in_call") or 0, reverse=True)
    top_calls = []
    for call in long_pool[:5]:
        top_calls.append({
            "call_id": call.get("call_id_internal") or call.get("call_id") or "?",
            "duration_seconds": call.get("duration_in_call") or 0,
            "from_number": call.get("from_number") or call.get("customer_number") or "?",
            "classified_type": call.get("classified_type") or "",
            "call_started_at": call.get("call_started_at"),
        })
    return len(long_pool), top_calls


def compute_metrics(calls: list[dict]) -> dict:
    """Calcule tous les KPIs et retourne un dict prêt pour le prompt."""
    total = len(calls)
    if total == 0:
        return {"calls_presented": 0}

    answered   = [c for c in calls if c.get("answered") == "Yes"]
    overflows  = [c for c in calls if c.get("classified_type") == "ucc_overflow"]
    abandoned  = [c for c in calls if c.get("classified_type") == "abandoned"]
    escalations = [c for c in calls if c.get("classified_type") == "warm_transfer"]
    ucc_calls  = [c for c in calls if c.get("classified_type") == "ucc_handled"]
    transfer_line_answered = [c for c in calls if c.get("classified_type") == "ucc_transfer_handled"]
    transfer_line_missed = [c for c in calls if c.get("classified_type") == "ucc_transfer_missed"]
    assistance_line_calls = [c for c in calls if c.get("line_id") == config.AIRCALL_ASSISTANCE_LINE_ID]
    transfer_line_calls = [c for c in calls if c.get("line_id") == config.AIRCALL_UCC_TRANSFER_LINE_ID]
    assistance_charging_calls = [
        c for c in assistance_line_calls
        if "charging assistance" in str(c.get("ivr_branch") or "").strip().lower()
    ]
    transfer_line_answered_all = [c for c in transfer_line_calls if c.get("answered") == "Yes"]
    peak_windows = _compute_peak_windows(assistance_line_calls)
    long_ucc_count, long_ucc_top_calls = _compute_long_ucc_calls(calls)

    # KPIs ventilés par ligne Aircall (Assistance vs UCC transfert) — affichés
    # côte-à-côte dans le Slack daily pour permettre une lecture rapide.
    assistance_line_kpis = _line_kpis(assistance_line_calls)
    transfer_line_kpis   = _line_kpis(transfer_line_calls)

    # Answer rate global calculé sur les appels "décrochables" (hors call
    # deflector / abandons IVR). Cf. _is_call_answerable().
    answerable = [c for c in calls if _is_call_answerable(c)]
    answered_amongst_answerable = [c for c in answerable if c.get("answered") == "Yes"]
    answer_rate_pct = _safe_pct(len(answered_amongst_answerable), len(answerable))

    durations    = [c.get("duration_in_call") or 0 for c in answered]
    wait_times   = [c.get("waiting_time") or 0 for c in calls if c.get("waiting_time")]
    avg_dur      = sum(durations) / len(durations) if durations else 0
    avg_wait     = sum(wait_times) / len(wait_times) if wait_times else 0

    pickup_rate   = round(len(answered) / total * 100, 1)
    overflow_rate = round(len(overflows) / total * 100, 1)
    abandon_rate  = round(len(abandoned) / total * 100, 1)

    # Détection signaux d'alerte automatiques
    alerts = []
    caller_counts = Counter(c.get("from_number") or c.get("customer_number") for c in calls)
    repeat_callers = [num for num, cnt in caller_counts.items() if cnt >= 2 and num]
    if repeat_callers:
        alerts.append({
            "level": "warning",
            "message": f"{len(repeat_callers)} numéro(s) ont appelé 2+ fois — probable non-résolution",
            "numbers_count": len(repeat_callers),
        })

    if ucc_calls and avg_dur < 120:
        alerts.append({
            "level": "critical",
            "message": f"Durée moy. appels B2C = {avg_dur:.0f}s (< 2 min) — suspicion de non-résolution",
        })

    if peak_windows:
        top_peak = peak_windows[0]
        if top_peak["count"] >= 5:
            # Récupère jusqu'à 3 call_ids représentatifs du pic pour permettre
            # au bloc Alertes Slack d'ajouter des liens cliquables.
            peak_call_ids = []
            window_start, window_end = top_peak["start_ts"], top_peak["end_ts"]
            for call in assistance_line_calls:
                ts = _parse_call_timestamp(call)
                if ts is None or not (window_start <= ts < window_end):
                    continue
                cid = call.get("call_id_internal") or call.get("call_id")
                if cid:
                    peak_call_ids.append(str(cid))
                if len(peak_call_ids) >= 3:
                    break
            alerts.append({
                "level": "warning",
                "message": (
                    f"Pic détecté : {top_peak['count']} appels entre "
                    f"{top_peak['start_local']} et {top_peak['end_local']} — possible incident terrain"
                ),
                "call_ids": peak_call_ids,
            })

    thresholds = config.KPI_THRESHOLDS
    return {
        "calls_presented":          total,
        "calls_answered":           len(answered),
        "warm_transfer_count":      len(escalations),
        "driveco_transfer_count":   len(transfer_line_calls),
        "escalations_count":        max(len(escalations), len(transfer_line_calls)),
        "overflow_count":           len(overflows),
        "abandoned_count":          len(abandoned),
        "transfer_line_answered_count": len(transfer_line_answered),
        "transfer_line_missed_count": len(transfer_line_missed),
        "transfer_line_total_count": len(transfer_line_answered) + len(transfer_line_missed),
        "assistance_line_calls_presented": len(assistance_line_calls),
        "assistance_line_charging_assistance_count": len(assistance_charging_calls),
        "assistance_line_charging_assistance_pct": _safe_pct(len(assistance_charging_calls), len(assistance_line_calls)),
        "transfer_line_calls_presented": len(transfer_line_calls),
        "transfer_line_pickup_rate_pct": _safe_pct(len(transfer_line_answered_all), len(transfer_line_calls)),
        "long_ucc_calls_count": long_ucc_count,
        "long_ucc_calls_top":        long_ucc_top_calls,
        "pickup_rate_pct":          pickup_rate,
        "overflow_rate_pct":        overflow_rate,
        "abandon_rate_pct":         abandon_rate,
        "answerable_calls":         len(answerable),
        "answer_rate_pct":          answer_rate_pct,
        "avg_duration_seconds":     round(avg_dur),
        "avg_wait_time_seconds":    round(avg_wait),
        # Ventilation Assistance Driveco
        "assistance_line_answerable":          assistance_line_kpis["answerable"],
        "assistance_line_answered":            assistance_line_kpis["answered"],
        "assistance_line_answer_rate_pct":     assistance_line_kpis["answer_rate_pct"],
        "assistance_line_avg_duration_seconds": assistance_line_kpis["avg_duration_seconds"],
        # Ventilation Driveco UCC transfert
        "transfer_line_answerable":            transfer_line_kpis["answerable"],
        "transfer_line_answered":              transfer_line_kpis["answered"],
        "transfer_line_answer_rate_pct":       transfer_line_kpis["answer_rate_pct"],
        "transfer_line_avg_duration_seconds":  transfer_line_kpis["avg_duration_seconds"],
        "pickup_rate_icon":         _icon(pickup_rate, thresholds["pickup_rate"]),
        "overflow_rate_icon":       _icon(overflow_rate, thresholds["overflow_rate"]),
        "abandon_rate_icon":        _icon(abandon_rate, thresholds["abandon_rate"]),
        "peak_windows":             peak_windows,
        "alerts":                   alerts,
    }


def call_customer_number(call: dict) -> str:
    return "".join(ch for ch in str(call.get("from_number") or call.get("customer_number") or "") if ch.isdigit())


def repeat_caller_rate(calls: list[dict], future_calls: list[dict] | None = None) -> float:
    future_index = Counter()
    for call in future_calls or []:
        number = call_customer_number(call)
        if number and number not in config.INTERNAL_PHONE_BLACKLIST:
            future_index[number] += 1

    callers = Counter()
    eligible_numbers = set()
    for call in calls or []:
        number = call_customer_number(call)
        if not number or number in config.INTERNAL_PHONE_BLACKLIST:
            continue
        callers[number] += 1
        eligible_numbers.add(number)

    if not eligible_numbers:
        return 0.0
    if future_calls:
        repeated = sum(1 for number in eligible_numbers if future_index.get(number, 0) > 0)
        return round(repeated / len(eligible_numbers) * 100, 1)

    repeated_calls = sum(count for count in callers.values() if count >= 2)
    total_calls = sum(callers.values())
    return round(repeated_calls / max(1, total_calls) * 100, 1)


def kb_compliance_rate(call_evaluations: list[dict]) -> float | None:
    weights = {"conforme": 1.0, "partiel": 0.5, "non_conforme": 0.0}
    values = []
    for evaluation in call_evaluations or []:
        status = evaluation.get("kb_compliance")
        if status in weights:
            values.append(weights[status])
    if not values:
        return None
    return round(sum(values) / len(values) * 100, 1)


def first_call_resolution_rate(call_evaluations: list[dict]) -> float | None:
    statuses = [
        str(ev.get("resolution_status") or "").strip()
        for ev in call_evaluations or []
        if str(ev.get("resolution_status") or "").strip()
    ]
    if not statuses:
        return None
    resolved = sum(1 for status in statuses if status == "resolved")
    return round(resolved / len(statuses) * 100, 1)


def warm_transfer_success_rate(calls: list[dict]) -> float | None:
    transfer_calls = [
        call for call in calls or []
        if call.get("classified_type") in {"warm_transfer", "ucc_transfer_handled", "ucc_transfer_missed"}
    ]
    if not transfer_calls:
        return None
    successes = sum(
        1 for call in transfer_calls
        if call.get("classified_type") in {"warm_transfer", "ucc_transfer_handled"}
        or str(call.get("answered") or "").strip().lower() == "yes"
    )
    return round(successes / len(transfer_calls) * 100, 1)


def agent_snapshot_metrics(
    agent_id: str,
    agent_name: str,
    calls: list[dict],
    call_evaluations: list[dict],
    future_calls: list[dict] | None = None,
) -> dict:
    answered = [call for call in calls if call.get("answered") == "Yes"]
    durations = [int(call.get("duration_in_call") or 0) for call in answered]
    evaluation_index = {
        str(evaluation.get("call_id") or ""): evaluation
        for evaluation in call_evaluations or []
        if evaluation.get("call_id") is not None
    }
    agent_evaluations = []
    for call in calls:
        call_id = str(call.get("call_id_internal") or call.get("call_id") or "").strip()
        if call_id and call_id in evaluation_index:
            agent_evaluations.append(evaluation_index[call_id])

    pickup_rate = round(len(answered) / max(1, len(calls)) * 100, 1)
    abandon_rate = round(sum(1 for call in calls if call.get("answered") != "Yes") / max(1, len(calls)) * 100, 1)
    avg_handle_time = round(sum(durations) / len(durations)) if durations else 0
    notes = []
    for evaluation in agent_evaluations:
        try:
            notes.append(float((evaluation.get("soft_skills") or {}).get("note_globale")))
        except (TypeError, ValueError):
            continue

    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "calls_presented": len(calls),
        "pickup_rate_pct": pickup_rate,
        "abandon_rate_pct": abandon_rate,
        "avg_duration_seconds": avg_handle_time,
        "repeat_caller_rate_pct": repeat_caller_rate(calls, future_calls=future_calls),
        "avg_soft_score": round(sum(notes) / len(notes), 1) if notes else None,
        "coverage_pct": round(len(agent_evaluations) / max(1, len(calls)) * 100, 1),
        "kb_compliance_rate_pct": kb_compliance_rate(agent_evaluations),
        "warm_transfer_success_rate_pct": warm_transfer_success_rate(calls),
    }


def build_agent_daily_snapshots(
    calls: list[dict],
    call_evaluations: list[dict],
    future_calls: list[dict] | None = None,
) -> list[dict]:
    grouped_calls: dict[str, list[dict]] = {}
    agent_names: dict[str, str] = {}
    for call in calls or []:
        agent_id = persistence.canonical_agent_id(call)
        if not agent_id:
            continue
        grouped_calls.setdefault(agent_id, []).append(call)
        agent_names[agent_id] = str(call.get("user_name") or "").strip() or agent_id

    snapshots = []
    for agent_id, bucket in grouped_calls.items():
        snapshots.append(agent_snapshot_metrics(agent_id, agent_names.get(agent_id, agent_id), bucket, call_evaluations, future_calls=future_calls))
    snapshots.sort(key=lambda item: (-int(item["calls_presented"]), item["agent_name"]))
    return snapshots


def representative_call_ids(metric: str, calls: list[dict], evaluations: list[dict], limit: int = 3) -> list[str]:
    evaluation_index = {
        str(ev.get("call_id") or ""): ev
        for ev in evaluations or []
        if ev.get("call_id") is not None
    }
    ranked = []
    for call in calls or []:
        call_id = str(call.get("call_id_internal") or call.get("call_id") or "").strip()
        if not call_id:
            continue
        evaluation = evaluation_index.get(call_id, {})
        score = 0
        if metric == "avg_soft_score":
            try:
                score = -float((evaluation.get("soft_skills") or {}).get("note_globale"))
            except (TypeError, ValueError):
                score = 0
        elif metric == "pickup_rate":
            score = 1 if call.get("answered") != "Yes" else 0
        elif metric == "abandon_rate":
            score = 1 if call.get("classified_type") == "abandoned" or call.get("answered") != "Yes" else 0
        else:
            score = int(call.get("duration_in_call") or 0)
        ranked.append((call_id, score))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [call_id for call_id, _ in ranked[:limit]]


def detect_snapshot_anomalies(
    snapshot_date: datetime,
    scope: str,
    agent_id: str,
    current_metrics: dict,
    history_rows: list[dict],
    calls: list[dict],
    evaluations: list[dict],
) -> list[dict]:
    metrics_to_check = ("pickup_rate", "abandon_rate", "avg_soft_score")
    anomalies = []
    if len(history_rows) < 7:
        return anomalies
    for metric in metrics_to_check:
        current_value = current_metrics.get(metric)
        if current_value is None:
            continue
        series = [float(row.get(metric)) for row in history_rows if row.get(metric) is not None]
        if len(series) < 7:
            continue
        baseline_mean = mean(series)
        baseline_stddev = pstdev(series)
        if baseline_stddev <= 0:
            continue
        z_score = (float(current_value) - baseline_mean) / baseline_stddev
        if abs(z_score) <= 2:
            continue
        anomalies.append(
            {
                "id": f"anomaly:{scope}:{agent_id or 'global'}:{metric}:{snapshot_date.strftime('%Y-%m-%d')}",
                "detected_on": snapshot_date.strftime("%Y-%m-%d"),
                "scope": scope,
                "agent_id": agent_id,
                "metric": metric,
                "z_score": round(z_score, 3),
                "current_value": current_value,
                "baseline_mean": round(baseline_mean, 2),
                "baseline_stddev": round(baseline_stddev, 2),
                "representative_call_ids": representative_call_ids(metric, calls, evaluations),
                "context": {"history_points": len(series)},
                "status": "new",
            }
        )
    return anomalies


def cluster_kb_gaps(call_evaluations: list[dict], limit: int = 8) -> list[dict]:
    stopwords = {
        "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou", "en", "sur", "pour", "avec", "dans",
        "plus", "pas", "par", "au", "aux", "ne", "que", "qui", "est", "sont", "fait", "faire", "client",
        "agent", "appel", "driveco", "ucc", "care",
    }
    buckets: dict[str, dict] = {}
    for evaluation in call_evaluations or []:
        call_id = str(evaluation.get("call_id") or "").strip()
        for item in evaluation.get("improvement_items") or []:
            if item.get("kb_reference"):
                continue
            text = re.sub(r"[^\w\s]", " ", str(item.get("text") or "").lower())
            tokens = [token for token in text.split() if len(token) >= 4 and token not in stopwords]
            topic = "_".join(tokens[:3]) or "kb_gap_non_classe"
            bucket = buckets.setdefault(topic, {"topic": topic, "frequency": 0, "example_call_ids": [], "status": "new"})
            bucket["frequency"] += 1
            if call_id and call_id not in bucket["example_call_ids"] and len(bucket["example_call_ids"]) < 5:
                bucket["example_call_ids"].append(call_id)
    rows = list(buckets.values())
    rows.sort(key=lambda item: (-item["frequency"], item["topic"]))
    return rows[:limit]


def anonymize_verbatim(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", "[email masqué]", value)
    value = re.sub(r"(?:(?:\+|00)33|0)[1-9](?:[\s\.-]?\d{2}){4}", "[téléphone masqué]", value)
    value = re.sub(r"\b\d{9,16}\b", "[numéro masqué]", value)
    value = re.sub(r"\b([A-Z][a-zéèêëàâîïôöùûüç]+)\s+([A-Z][a-zéèêëàâîïôöùûüç]+)\b", "[nom masqué]", value)
    return value


def _iter_voc_evaluations(evaluations: list[dict]) -> list[dict]:
    rows = []
    for evaluation in evaluations or []:
        voc_extract = evaluation.get("voc_extract")
        if isinstance(voc_extract, dict):
            rows.append({"evaluation": evaluation, "voc_extract": voc_extract})
    return rows


def aggregate_voc_topics(evaluations: list[dict], limit: int = 8) -> list[dict]:
    counts = Counter()
    sentiment_scores: dict[str, list[int]] = {}
    severity_scores: dict[str, list[int]] = {}
    labels = voc_taxonomy.axis_label_map("topics")
    sentiment_map = {"très_négatif": -2, "négatif": -1, "neutre": 0, "positif": 1, "très_positif": 2}
    for row in _iter_voc_evaluations(evaluations):
        for topic in row["voc_extract"].get("topics") or []:
            code = topic.get("topic_code") or "autre"
            counts[code] += 1
            sentiment_scores.setdefault(code, []).append(sentiment_map.get(topic.get("sentiment"), 0))
            severity_scores.setdefault(code, []).append(int(topic.get("severity") or 0))
    output = []
    for code, count in counts.most_common(limit):
        sentiments = sentiment_scores.get(code) or [0]
        severities = severity_scores.get(code) or [0]
        output.append(
            {
                "topic_code": code,
                "label": labels.get(code, code.replace("_", " ").title()),
                "count": count,
                "avg_sentiment": round(sum(sentiments) / len(sentiments), 2),
                "avg_severity": round(sum(severities) / len(severities), 1),
            }
        )
    return output


def aggregate_voc_entity_sentiment(evaluations: list[dict]) -> list[dict]:
    labels = voc_taxonomy.axis_label_map("entities")
    sentiment_map = {"très_négatif": -2, "négatif": -1, "neutre": 0, "positif": 1, "très_positif": 2}
    buckets: dict[str, list[int]] = {}
    for row in _iter_voc_evaluations(evaluations):
        for item in row["voc_extract"].get("entity_perceptions") or []:
            code = item.get("entity_code") or "autre"
            buckets.setdefault(code, []).append(sentiment_map.get(item.get("sentiment"), 0))
    output = []
    for code, values in buckets.items():
        output.append(
            {
                "entity_code": code,
                "label": labels.get(code, code.replace("_", " ").title()),
                "mentions": len(values),
                "avg_sentiment": round(sum(values) / len(values), 2),
            }
        )
    output.sort(key=lambda item: (item["avg_sentiment"], -item["mentions"]))
    return output


def aggregate_voc_churn_risk_typology(evaluations: list[dict]) -> dict:
    """Retourne la répartition {élevé: N, modéré: N} des risques client."""
    buckets = Counter()
    for evaluation in evaluations or []:
        voc_extract = evaluation.get("voc_extract") or {}
        signal = voc_extract.get("churn_risk_signal")
        if signal in {"modéré", "élevé"}:
            buckets[signal] += 1
    return {
        "eleve": buckets.get("élevé", 0),
        "modere": buckets.get("modéré", 0),
        "total": sum(buckets.values()),
    }


def aggregate_voc_churn_risks(evaluations: list[dict]) -> list[dict]:
    output = []
    for evaluation in evaluations or []:
        voc_extract = evaluation.get("voc_extract") or {}
        if voc_extract.get("churn_risk_signal") not in {"modéré", "élevé"}:
            continue
        verbatims = voc_extract.get("verbatim_quotes") or []
        quote = ""
        if verbatims:
            quote = anonymize_verbatim(verbatims[0].get("quote") or "")
        output.append(
            {
                "call_id": evaluation.get("call_id"),
                "agent": evaluation.get("agent") or evaluation.get("user_name"),
                "risk": voc_extract.get("churn_risk_signal"),
                "quote": quote,
                "satisfaction_signal": voc_extract.get("satisfaction_signal"),
            }
        )
    return output


def aggregate_voc_opportunities(evaluations: list[dict], limit: int = 8) -> list[dict]:
    counts = Counter()
    for row in _iter_voc_evaluations(evaluations):
        for item in (row["voc_extract"].get("product_ideas") or []) + (row["voc_extract"].get("unmet_needs") or []):
            cleaned = re.sub(r"\s+", " ", str(item or "").strip())
            if cleaned:
                counts[cleaned] += 1
    return [{"description": text, "count": count} for text, count in counts.most_common(limit)]


def aggregate_voc_best_practices(evaluations: list[dict], limit: int = 3) -> list[dict]:
    rows = []
    for evaluation in evaluations or []:
        voc_extract = evaluation.get("voc_extract") or {}
        for item in voc_extract.get("best_practice_moments") or []:
            quote = anonymize_verbatim(item.get("quote") or "")
            if not quote:
                continue
            rows.append(
                {
                    "call_id": evaluation.get("call_id"),
                    "agent": evaluation.get("agent") or evaluation.get("user_name") or "Agent",
                    "quote": quote,
                    "topic_code": item.get("topic_code"),
                }
            )
    return rows[:limit]


def aggregate_voc_positive_satisfaction(evaluations: list[dict]) -> dict:
    positive_calls = []
    for evaluation in evaluations or []:
        voc_extract = evaluation.get("voc_extract") or {}
        if voc_extract.get("satisfaction_signal") != "positif":
            continue
        quote = ""
        for item in voc_extract.get("verbatim_quotes") or []:
            quote = anonymize_verbatim(item.get("quote") or "")
            if quote:
                break
        positive_calls.append({"call_id": evaluation.get("call_id"), "quote": quote})
    return {
        "count": len(positive_calls),
        "sample_quote": positive_calls[0]["quote"] if positive_calls else "",
    }


def aggregate_voc_competitor_watch(evaluations: list[dict], limit: int = 6) -> list[dict]:
    counts = Counter()
    samples: dict[str, str] = {}
    for row in _iter_voc_evaluations(evaluations):
        for item in row["voc_extract"].get("competitor_mentions") or []:
            name = re.sub(r"\s+", " ", str(item.get("competitor_name") or "").strip())
            if not name:
                continue
            counts[name] += 1
            samples.setdefault(name, anonymize_verbatim(item.get("context_quote") or ""))
    return [{"competitor_name": name, "count": count, "sample_quote": samples.get(name, "")} for name, count in counts.most_common(limit)]


def build_voc_summary(evaluations: list[dict]) -> dict:
    topic_counts = Counter()
    review_items = 0
    verbatims = []
    for row in _iter_voc_evaluations(evaluations):
        voc_extract = row["voc_extract"]
        for topic in voc_extract.get("topics") or []:
            topic_counts[topic.get("topic_code") or "autre"] += 1
            if topic.get("needs_taxonomy_review"):
                review_items += 1
        for item in voc_extract.get("entity_perceptions") or []:
            if item.get("needs_taxonomy_review"):
                review_items += 1
        for quote in voc_extract.get("verbatim_quotes") or []:
            text = anonymize_verbatim(quote.get("quote") or "")
            if text:
                verbatims.append(
                    {
                        "call_id": row["evaluation"].get("call_id"),
                        "quote": text,
                        "topic_code": quote.get("topic_code"),
                        "sentiment": quote.get("sentiment"),
                    }
                )
    weak_signals = [
        {"topic_code": code, "count": count}
        for code, count in topic_counts.items()
        if count >= config.VOC_MIN_WEAK_SIGNAL_COUNT
    ]
    weak_signals.sort(key=lambda item: (-item["count"], item["topic_code"]))
    return {
        "top_topics": aggregate_voc_topics(evaluations),
        "entity_sentiment": aggregate_voc_entity_sentiment(evaluations),
        "churn_risk_calls": aggregate_voc_churn_risks(evaluations),
        "churn_risk_typology": aggregate_voc_churn_risk_typology(evaluations),
        "opportunities": aggregate_voc_opportunities(evaluations),
        "best_practices": aggregate_voc_best_practices(evaluations),
        "positive_satisfaction": aggregate_voc_positive_satisfaction(evaluations),
        "competitors": aggregate_voc_competitor_watch(evaluations),
        "weak_signals": weak_signals,
        "verbatims": verbatims[:5],
        "taxonomy_review_items": review_items,
    }
