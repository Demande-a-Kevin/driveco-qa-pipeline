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
mkdir -p "$LOG_DIR"
CAFFEINATE_BIN="$(command -v caffeinate || true)"

case "$MODE" in
  daily)
    LOG_FILE="$LOG_DIR/cron_daily.log"
    ;;
  weekly)
    LOG_FILE="$LOG_DIR/cron_weekly.log"
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

log_line() {
  printf '%s [cron-wrapper] %s\n' "$(timestamp)" "$*" >> "$LOG_FILE"
}

write_benchmark_interrupted_summary() {
  if [ -f "$BENCH_SUMMARY_SCRIPT" ]; then
    "$PYTHON_BIN" - <<PY >> "$LOG_FILE" 2>&1
import sys
sys.path.insert(0, "$PIPELINE_DIR")
import summarize_benchmark_result
path = summarize_benchmark_result.write_interrupted_summary("interrompu_par_daily")
print(f"[cron-wrapper] benchmark summary updated: {path}")
PY
  fi
}

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
  exit 0
fi

if [ "$MODE" = "daily" ]; then
  benchmark_pid="$(pgrep -fo -f "$BENCH_SCRIPT" || true)"
  if [ -n "$benchmark_pid" ] && ps -p "$benchmark_pid" >/dev/null 2>&1; then
    log_line "preempt mode=daily reason=$RUN_REASON stopping_benchmark pid=$benchmark_pid"
    write_benchmark_interrupted_summary
    kill "$benchmark_pid" || true
    sleep 2
    if ps -p "$benchmark_pid" >/dev/null 2>&1; then
      kill -9 "$benchmark_pid" || true
      log_line "preempt mode=daily reason=$RUN_REASON benchmark_force_killed pid=$benchmark_pid"
    fi
  fi
fi

if [ -n "$CAFFEINATE_BIN" ]; then
  log_line "start mode=$MODE reason=$RUN_REASON python=$PYTHON_BIN caffeinate=1"
else
  log_line "start mode=$MODE reason=$RUN_REASON python=$PYTHON_BIN caffeinate=0"
fi
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
  exit 0
else
  exit_code=$?
  log_line "done mode=$MODE reason=$RUN_REASON exit=$exit_code"
  exit "$exit_code"
fi
