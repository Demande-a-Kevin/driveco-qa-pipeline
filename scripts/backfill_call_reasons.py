"""backfill_call_reasons.py — one-shot backfill of daily_call_reasons.

Reconstructs voc_summary.call_reasons per day from already-persisted evaluations
and writes the aggregate into Supabase table daily_call_reasons.

Usage:
    python scripts/backfill_call_reasons.py --from 2026-05-01 --to 2026-05-31
    python scripts/backfill_call_reasons.py --from 2026-05-01           # today as default 'to'

Idempotent: each (detected_on, reason_code) row is upserted; the persistence
helper already deletes the day before re-insert.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Allow running from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from supabase import create_client  # type: ignore

import metrics_builder  # noqa: E402  (path adjusted above)
import persistence  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill_call_reasons")

BATCH = 1000


def _client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _load_evaluations_for_day(sb, day: date) -> list[dict]:
    """Load all evaluations whose underlying call started on `day` (UTC).

    Joins via call_id → calls.started_at. Returns a list of dicts shaped like
    the live pipeline evaluations (raw merged at top level so aggregate_call_reasons
    finds customer_call_reason etc.).
    """
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    end = datetime.combine(day, datetime.max.time(), tzinfo=timezone.utc).isoformat()
    # 1. Calls of the day
    calls = (
        sb.table("calls")
        .select("id")
        .gte("started_at", start)
        .lte("started_at", end)
        .limit(5000)
        .execute()
    )
    call_ids = [c["id"] for c in (calls.data or [])]
    if not call_ids:
        return []
    # 2. Evaluations linked to these calls (chunk to avoid URL limits)
    evals: list[dict] = []
    for i in range(0, len(call_ids), 200):
        chunk = call_ids[i : i + 200]
        res = (
            sb.table("evaluations")
            .select("id,call_id,score_global,raw")
            .in_("call_id", chunk)
            .limit(BATCH)
            .execute()
        )
        evals.extend(res.data or [])
    # 3. Reshape so aggregate_call_reasons sees a "live" evaluation dict
    out = []
    for e in evals:
        raw = e.get("raw") or {}
        merged = {**raw, "call_id": e.get("call_id"), "evaluation_id": e.get("id")}
        out.append(merged)
    return out


def backfill(from_date: date, to_date: date) -> None:
    sb = _client()
    total_days = 0
    total_reasons = 0
    for day in _daterange(from_date, to_date):
        evals = _load_evaluations_for_day(sb, day)
        if not evals:
            log.info("  %s : 0 evaluations — skip", day.isoformat())
            continue
        reasons = metrics_builder.aggregate_call_reasons(evals, limit=8)
        if not reasons:
            log.info("  %s : %d evals → 0 reasons", day.isoformat(), len(evals))
            continue
        n = persistence.save_call_reasons(reasons, datetime.combine(day, datetime.min.time()))
        log.info("  %s : %d evals → %d reasons persisted", day.isoformat(), len(evals), n)
        total_days += 1
        total_reasons += n
    log.info("Backfill done : %d days, %d reason rows total", total_days, total_reasons)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="from_", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument("--to", dest="to_", default=None, help="YYYY-MM-DD inclusive (default: today)")
    args = parser.parse_args()
    start = date.fromisoformat(args.from_)
    end = date.fromisoformat(args.to_) if args.to_ else date.today()
    if start > end:
        raise SystemExit("--from must be <= --to")
    backfill(start, end)


if __name__ == "__main__":
    main()
