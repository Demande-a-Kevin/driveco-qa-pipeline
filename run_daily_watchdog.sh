#!/usr/bin/env bash
set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PIPELINE_DIR/qa-driveco-data/logs"
LOG_FILE="$LOG_DIR/cron_daily.log"
RUNNER="$PIPELINE_DIR/run_from_cron.sh"
mkdir -p "$LOG_DIR"
STALE_LOG_SECONDS="${STALE_LOG_SECONDS:-900}"

timestamp() {
  date '+%Y-%m-%d %H:%M:%S %z'
}

log_line() {
  printf '%s [daily-watchdog] %s\n' "$(timestamp)" "$*" >> "$LOG_FILE"
}

target_date="$(
  python3 - <<'PY'
from datetime import date, timedelta
print((date.today() - timedelta(days=1)).isoformat())
PY
)"

report_file="$PIPELINE_DIR/qa-driveco-data/${target_date}_daily_report.md"
flag_file="$PIPELINE_DIR/qa-driveco-data/.slack_sent_daily_${target_date}.flag"

running_pid="$(pgrep -fo -f "$PIPELINE_DIR/analysis_pipeline.py --mode daily" || true)"
if [ -f "$report_file" ] || [ -f "$flag_file" ]; then
  log_line "skip target_date=$target_date already_done report_or_flag_present"
  exit 0
fi

if [ -n "$running_pid" ] && ps -p "$running_pid" >/dev/null 2>&1; then
  log_mtime="$(stat -f '%m' "$LOG_FILE" 2>/dev/null || echo 0)"
  now_ts="$(date '+%s')"
  log_age=$(( now_ts - log_mtime ))
  if [ "$log_age" -lt "$STALE_LOG_SECONDS" ]; then
    log_line "skip target_date=$target_date already_running pid=$running_pid log_age_seconds=$log_age"
    exit 0
  fi
  log_line "stale_running_process target_date=$target_date pid=$running_pid log_age_seconds=$log_age relaunching"
fi

log_line "relaunch target_date=$target_date reason=missing_daily_output"
"$RUNNER" daily watchdog
