#!/usr/bin/env bash
set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$PIPELINE_DIR/analysis_pipeline.py"
BENCH_SCRIPT="$PIPELINE_DIR/bench_ollama_models.py"
BENCH_SUMMARY_SCRIPT="$PIPELINE_DIR/summarize_benchmark_result.py"
PYTHON_BIN="${PYTHON_BIN:-$PIPELINE_DIR/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

MODE="${1:-daily}"
RUN_REASON="${2:-cron}"
LOG_DIR="$PIPELINE_DIR/qa-driveco-data/logs"
STATE_DIR="$PIPELINE_DIR/qa-driveco-data/state"
LOCK_DIR="$PIPELINE_DIR/qa-driveco-data/locks"
mkdir -p "$LOG_DIR"
mkdir -p "$STATE_DIR"
mkdir -p "$LOCK_DIR"
CAFFEINATE_BIN="$(command -v caffeinate || true)"

case "$MODE" in
  daily)
    LOG_FILE="$LOG_DIR/cron_daily.log"
    ;;
  weekly)
    LOG_FILE="$LOG_DIR/cron_weekly.log"
    ;;
  reliability)
    LOG_FILE="$LOG_DIR/cron_reliability.log"
    ;;
  benchmark)
    LOG_FILE="$LOG_DIR/cron_benchmark.log"
    ;;
  *)
    echo "Mode invalide: $MODE" >&2
    exit 1
    ;;
esac

timestamp() {
  date '+%Y-%m-%d %H:%M:%S %z'
}

unix_ts() {
  date '+%s'
}

log_line() {
  printf '%s [cron-wrapper] %s\n' "$(timestamp)" "$*" >> "$LOG_FILE"
}

STATUS_FILE="$STATE_DIR/${MODE}_status.env"
MODE_LOCK_DIR="$LOCK_DIR/${MODE}.lock"

write_status() {
  local escaped_reason escaped_status escaped_message
  printf -v escaped_reason '%q' "$RUN_REASON"
  printf -v escaped_status '%q' "$1"
  printf -v escaped_message '%q' "${2:-}"
  cat > "$STATUS_FILE" <<EOF
mode=$MODE
reason=$escaped_reason
status=$escaped_status
pid=$$
started_at_unix=${START_TS:-$(unix_ts)}
updated_at_unix=$(unix_ts)
message=$escaped_message
EOF
}

release_lock() {
  if [ -d "$MODE_LOCK_DIR" ] && [ -f "$MODE_LOCK_DIR/pid" ]; then
    current_lock_pid="$(cat "$MODE_LOCK_DIR/pid" 2>/dev/null || true)"
    if [ "$current_lock_pid" = "$$" ]; then
      rm -rf "$MODE_LOCK_DIR"
    fi
  fi
}

acquire_lock() {
  if mkdir "$MODE_LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$MODE_LOCK_DIR/pid"
    trap release_lock EXIT
    return 0
  fi

  existing_pid="$(cat "$MODE_LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$existing_pid" ] && ps -p "$existing_pid" >/dev/null 2>&1; then
    log_line "skip mode=$MODE reason=$RUN_REASON lock_held pid=$existing_pid"
    write_status "skipped" "lock_held pid=$existing_pid"
    exit 0
  fi

  rm -rf "$MODE_LOCK_DIR"
  if mkdir "$MODE_LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$MODE_LOCK_DIR/pid"
    trap release_lock EXIT
    return 0
  fi

  log_line "skip mode=$MODE reason=$RUN_REASON lock_busy_unknown"
  write_status "skipped" "lock_busy_unknown"
  exit 0
}

send_alert() {
  local level="$1"
  local message="$2"
  PIPELINE_DIR="$PIPELINE_DIR" PIPELINE_ALERT_LEVEL="$level" PIPELINE_ALERT_MESSAGE="$message" "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1 || true
import sys
import os
sys.path.insert(0, os.environ["PIPELINE_DIR"])
import notifier
notifier.send_alert(os.environ["PIPELINE_ALERT_MESSAGE"], level=os.environ["PIPELINE_ALERT_LEVEL"])
PY
}

write_benchmark_interrupted_summary() {
  summary_path="$PIPELINE_DIR/qa-driveco-data/bench_ollama_latest_summary.md"
  cat > "$summary_path" <<EOF
# Benchmark Ollama — interrompu

- Date : \`$(date '+%Y-%m-%d %H:%M:%S')\`
- Statut : \`interrompu_par_daily\`
- Action : le run \`daily\` de publication a été priorisé.
- Consulter : \`qa-driveco-data/logs/cron_benchmark.log\`
EOF
  log_line "benchmark summary updated: $summary_path"
}

stop_benchmark_processes() {
  bench_patterns=(
    "$PIPELINE_DIR/run_from_cron.sh benchmark"
    "$BENCH_SCRIPT"
  )

  bench_pids=""
  for pattern in "${bench_patterns[@]}"; do
    while IFS= read -r pid; do
      [ -n "$pid" ] && bench_pids="$bench_pids $pid"
    done < <(pgrep -f "$pattern" || true)
  done

  unique_pids="$(printf '%s\n' $bench_pids 2>/dev/null | awk 'NF && !seen[$0]++')"
  [ -z "$unique_pids" ] && return 0

  log_line "preempt mode=daily reason=$RUN_REASON stopping_benchmark pids=$(echo "$unique_pids" | tr '\n' ',')"
  write_benchmark_interrupted_summary

  while IFS= read -r pid; do
    [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
  done <<< "$unique_pids"

  sleep 3

  remaining=""
  while IFS= read -r pid; do
    [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1 && remaining="$remaining $pid"
  done <<< "$unique_pids"

  if [ -n "$remaining" ]; then
    while IFS= read -r pid; do
      [ -n "$pid" ] && kill -9 "$pid" >/dev/null 2>&1 || true
    done <<< "$(printf '%s\n' $remaining)"
    log_line "preempt mode=daily reason=$RUN_REASON benchmark_force_killed pids=$(echo "$remaining" | xargs)"
  fi
}

acquire_lock

case "$MODE" in
  benchmark)
    running_pid="$(pgrep -fo -f "$BENCH_SCRIPT" || true)"
    ;;
  *)
    running_pid="$(pgrep -fo -f "$SCRIPT --mode $MODE" || true)"
    ;;
esac

if [ -n "$running_pid" ] && ps -p "$running_pid" >/dev/null 2>&1; then
  log_line "skip mode=$MODE reason=$RUN_REASON already_running pid=$running_pid"
  write_status "skipped" "already_running pid=$running_pid"
  exit 0
fi

if [ "$MODE" = "daily" ]; then
  stop_benchmark_processes
fi

if [ -n "$CAFFEINATE_BIN" ]; then
  log_line "start mode=$MODE reason=$RUN_REASON python=$PYTHON_BIN caffeinate=1"
else
  log_line "start mode=$MODE reason=$RUN_REASON python=$PYTHON_BIN caffeinate=0"
fi
START_TS="$(unix_ts)"
write_status "running" "wrapper_started"
cd "$PIPELINE_DIR"
if [ "$MODE" = "benchmark" ]; then
  if [ -n "$CAFFEINATE_BIN" ]; then
    RUN_CMD=( "$CAFFEINATE_BIN" -dimsu nice -n 10 "$PYTHON_BIN" "$BENCH_SCRIPT" )
  else
    RUN_CMD=( nice -n 10 "$PYTHON_BIN" "$BENCH_SCRIPT" )
  fi
else
  if [ -n "$CAFFEINATE_BIN" ]; then
    RUN_CMD=( "$CAFFEINATE_BIN" -dimsu "$PYTHON_BIN" "$SCRIPT" --mode "$MODE" )
  else
    RUN_CMD=( "$PYTHON_BIN" "$SCRIPT" --mode "$MODE" )
  fi
fi
if "${RUN_CMD[@]}" >> "$LOG_FILE" 2>&1; then
  if [ "$MODE" = "benchmark" ] && [ -f "$BENCH_SUMMARY_SCRIPT" ]; then
    log_line "postprocess mode=benchmark step=summary"
    if "$PYTHON_BIN" "$BENCH_SUMMARY_SCRIPT" >> "$LOG_FILE" 2>&1; then
      log_line "postprocess mode=benchmark step=summary exit=0"
    else
      summary_exit=$?
      log_line "postprocess mode=benchmark step=summary exit=$summary_exit"
    fi
  fi
  log_line "done mode=$MODE reason=$RUN_REASON exit=0"
  write_status "success" "exit=0"
  exit 0
else
  exit_code=$?
  log_line "done mode=$MODE reason=$RUN_REASON exit=$exit_code"
  write_status "failed" "exit=$exit_code"
  if [ "$MODE" = "daily" ]; then
    send_alert "critical" "Pipeline QA daily en échec (${RUN_REASON}) avec exit=${exit_code}. Vérifie le log cron_daily.log sur le Mac."
  elif [ "$MODE" = "reliability" ]; then
    send_alert "critical" "Pipeline QA reliability en échec (${RUN_REASON}) avec exit=${exit_code}. Vérifie le log cron_reliability.log sur le Mac."
  fi
  exit "$exit_code"
fi
