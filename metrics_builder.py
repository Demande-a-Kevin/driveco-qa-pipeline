"""
metrics_builder.py — Calcule les KPIs à partir des appels classifiés.
"""
from collections import Counter
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    _PARIS = ZoneInfo("Europe/Paris")
except ImportError:
    import pytz
    _PARIS = pytz.timezone("Europe/Paris")
import config


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
            alerts.append({
                "level": "warning",
                "message": (
                    f"Pic détecté : {top_peak['count']} appels entre "
                    f"{top_peak['start_local']} et {top_peak['end_local']} — possible incident terrain"
                ),
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
        "avg_duration_seconds":     round(avg_dur),
        "avg_wait_time_seconds":    round(avg_wait),
        "pickup_rate_icon":         _icon(pickup_rate, thresholds["pickup_rate"]),
        "overflow_rate_icon":       _icon(overflow_rate, thresholds["overflow_rate"]),
        "abandon_rate_icon":        _icon(abandon_rate, thresholds["abandon_rate"]),
        "peak_windows":             peak_windows,
        "alerts":                   alerts,
    }
