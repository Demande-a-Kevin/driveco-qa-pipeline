#!/usr/bin/env bash
set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PIPELINE_DIR/qa-driveco-data/logs"
LOG_FILE="$LOG_DIR/cron_daily.log"
RUNNER="$PIPELINE_DIR/run_from_cron.sh"
STATE_FILE="$PIPELINE_DIR/qa-driveco-data/state/daily_status.env"
PYTHON_BIN="${PYTHON_BIN:-$PIPELINE_DIR/.venv/bin/python}"
mkdir -p "$LOG_DIR"
STALE_LOG_SECONDS="${STALE_LOG_SECONDS:-900}"
MAX_RUNNING_SECONDS="${MAX_RUNNING_SECONDS:-3600}"
LOCK_DIR="$PIPELINE_DIR/qa-driveco-data/locks/daily.lock"

timestamp() {
  date '+%Y-%m-%d %H:%M:%S %z'
}

log_line() {
  printf '%s [daily-watchdog] %s\n' "$(timestamp)" "$*" >> "$LOG_FILE"
}

send_alert() {
  local level="$1"
  local message="$2"
  PIPELINE_DIR="$PIPELINE_DIR" PIPELINE_ALERT_LEVEL="$level" PIPELINE_ALERT_MESSAGE="$message" python3 - <<'PY' >/dev/null 2>&1 || true
import sys
import os
sys.path.insert(0, os.environ["PIPELINE_DIR"])
import notifier
notifier.send_alert(os.environ["PIPELINE_ALERT_MESSAGE"], level=os.environ["PIPELINE_ALERT_LEVEL"])
PY
}

target_date="$(
  python3 - <<'PY'
from datetime import date, timedelta
print((date.today() - timedelta(days=1)).isoformat())
PY
)"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

OUTPUT_DIR="$(
  PIPELINE_DIR="$PIPELINE_DIR" "$PYTHON_BIN" - <<'PY'
import os
import sys
sys.path.insert(0, os.environ["PIPELINE_DIR"])
import config
print(config.REPORT_OUTPUT_DIR)
PY
)"

if [ -z "$OUTPUT_DIR" ]; then
  OUTPUT_DIR="$PIPELINE_DIR/qa-driveco-data"
fi

report_file="$OUTPUT_DIR/${target_date}_daily_report.md"
flag_file="$OUTPUT_DIR/.slack_sent_daily_${target_date}.flag"
watchdog_alert_flag="$OUTPUT_DIR/.watchdog_alert_daily_${target_date}.flag"

running_pid="$(pgrep -fo -f "$PIPELINE_DIR/analysis_pipeline.py --mode daily" || true)"
lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
if [ -f "$report_file" ] || [ -f "$flag_file" ]; then
  log_line "skip target_date=$target_date already_done report_or_flag_present"
  exit 0
fi

status=""
started_at_unix=""
if [ -f "$STATE_FILE" ]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
fi

if [ -n "$lock_pid" ] && ps -p "$lock_pid" >/dev/null 2>&1; then
  log_line "skip target_date=$target_date daily_lock_held pid=$lock_pid"
  if [ ! -f "$watchdog_alert_flag" ]; then
    send_alert "warning" "Rapport QA quotidien ${target_date} pas encore publié à l'heure prévue, mais un run est bien en cours."
    touch "$watchdog_alert_flag"
  fi
  exit 0
fi

if [ -n "$running_pid" ] && ps -p "$running_pid" >/dev/null 2>&1; then
  log_mtime="$(stat -f '%m' "$LOG_FILE" 2>/dev/null || echo 0)"
  now_ts="$(date '+%s')"
  log_age=$(( now_ts - log_mtime ))
  run_age=0
  if [ -n "${started_at_unix:-}" ]; then
    run_age=$(( now_ts - started_at_unix ))
  fi
  if [ "$log_age" -lt "$STALE_LOG_SECONDS" ]; then
    log_line "skip target_date=$target_date already_running pid=$running_pid log_age_seconds=$log_age run_age_seconds=$run_age"
    if [ ! -f "$watchdog_alert_flag" ]; then
      send_alert "warning" "Rapport QA quotidien ${target_date} pas encore publié à l'heure prévue, mais le run est en cours depuis $(( run_age / 60 )) min."
      touch "$watchdog_alert_flag"
    fi
    exit 0
  fi
  if [ "$run_age" -gt "$MAX_RUNNING_SECONDS" ]; then
    log_line "stale_running_process target_date=$target_date pid=$running_pid log_age_seconds=$log_age run_age_seconds=$run_age killing_and_relaunching"
    kill "$running_pid" >/dev/null 2>&1 || true
    sleep 2
    if ps -p "$running_pid" >/dev/null 2>&1; then
      kill -9 "$running_pid" >/dev/null 2>&1 || true
    fi
    send_alert "critical" "Run QA quotidien ${target_date} bloqué depuis $(( run_age / 60 )) min. Process relancé automatiquement."
  else
    log_line "stale_running_process target_date=$target_date pid=$running_pid log_age_seconds=$log_age run_age_seconds=$run_age relaunching"
    send_alert "warning" "Run QA quotidien ${target_date} sans progrès depuis $(( log_age / 60 )) min. Relance automatique."
  fi
fi

if [ "${status:-}" = "failed" ]; then
  log_line "previous_run_failed target_date=$target_date relaunching"
  if [ ! -f "$watchdog_alert_flag" ]; then
    send_alert "critical" "Le run QA quotidien ${target_date} a échoué avant publication. Relance automatique en cours."
    touch "$watchdog_alert_flag"
  fi
fi

log_line "relaunch target_date=$target_date reason=missing_daily_output"
"$RUNNER" daily watchdog
