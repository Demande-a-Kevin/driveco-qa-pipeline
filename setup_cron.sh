#!/usr/bin/env bash
# setup_cron.sh — Configure le cron du pipeline QA Driveco sur le Mac mini Kev1n.
#
# Horaires par défaut :
#   Benchmark        : 01h30 tous les jours
#   Quotidien        : 05h15 tous les jours (viser publication avant 07h00)
#   Watchdog daily   : 06h45 tous les jours (rattrapage si rien n'est parti)
#   Hebdomadaire     : 07h15 chaque lundi (semaine précédente)
#
# Prérequis :
#   - un environnement virtuel .venv dans le repo, ou python3 dans le PATH
#   - .env configuré dans le répertoire du pipeline
#   - Ollama accessible sur localhost:11434

set -euo pipefail

# ── Paramètres à adapter si besoin ───────────────────────────────────────────
PIPELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$PIPELINE_DIR/analysis_pipeline.py"
RUNNER="$PIPELINE_DIR/run_from_cron.sh"
WATCHDOG="$PIPELINE_DIR/run_daily_watchdog.sh"
PYTHON_BIN="${PYTHON_BIN:-$PIPELINE_DIR/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi
LOG_DIR="$PIPELINE_DIR/qa-driveco-data/logs"
CRON_USER="$(whoami)"
BENCH_CRON_MINUTE="${BENCH_CRON_MINUTE:-30}"
BENCH_CRON_HOUR="${BENCH_CRON_HOUR:-1}"
DAILY_CRON_MINUTE="${DAILY_CRON_MINUTE:-15}"
DAILY_CRON_HOUR="${DAILY_CRON_HOUR:-5}"
WATCHDOG_CRON_MINUTE="${WATCHDOG_CRON_MINUTE:-45}"
WATCHDOG_CRON_HOUR="${WATCHDOG_CRON_HOUR:-6}"
WEEKLY_CRON_MINUTE="${WEEKLY_CRON_MINUTE:-15}"
WEEKLY_CRON_HOUR="${WEEKLY_CRON_HOUR:-7}"

# ── Vérifications préalables ─────────────────────────────────────────────────
echo "=== Setup cron QA Driveco ==="
echo "Pipeline : $SCRIPT"
echo "Logs     : $LOG_DIR"
echo "Python   : $($PYTHON_BIN --version 2>&1)"
echo ""

if [ ! -f "$SCRIPT" ]; then
  echo "❌ Script introuvable : $SCRIPT"
  exit 1
fi

if [ ! -f "$RUNNER" ]; then
  echo "❌ Wrapper introuvable : $RUNNER"
  exit 1
fi

if [ ! -f "$WATCHDOG" ]; then
  echo "❌ Watchdog introuvable : $WATCHDOG"
  exit 1
fi

mkdir -p "$LOG_DIR"
chmod +x "$RUNNER" "$WATCHDOG"

# ── Construction des lignes cron ─────────────────────────────────────────────
BENCH_CRON="$BENCH_CRON_MINUTE $BENCH_CRON_HOUR * * * $RUNNER benchmark"
DAILY_CRON="$DAILY_CRON_MINUTE $DAILY_CRON_HOUR * * * $RUNNER daily"
WATCHDOG_CRON="$WATCHDOG_CRON_MINUTE $WATCHDOG_CRON_HOUR * * * $WATCHDOG"
WEEKLY_CRON="$WEEKLY_CRON_MINUTE $WEEKLY_CRON_HOUR * * 1 $RUNNER weekly"

# ── Injection dans crontab (sans écraser les lignes existantes) ───────────────
# On retire les entrées existantes du pipeline, puis on réinjecte les nouvelles
TMP_CRONTAB="$(mktemp)"
{
  crontab -l 2>/dev/null | awk -v repo="$PIPELINE_DIR" '
    index($0, repo "/.venv/bin/python " repo "/analysis_pipeline.py") == 0 &&
    index($0, repo "/run_from_cron.sh") == 0 &&
    index($0, repo "/run_daily_watchdog.sh") == 0
  '
  echo "$BENCH_CRON"
  echo "$DAILY_CRON"
  echo "$WATCHDOG_CRON"
  echo "$WEEKLY_CRON"
} > "$TMP_CRONTAB"
crontab "$TMP_CRONTAB"
rm -f "$TMP_CRONTAB"

echo "✅ Cron configuré pour $CRON_USER :"
echo "  $BENCH_CRON"
echo "  $DAILY_CRON"
echo "  $WATCHDOG_CRON"
echo "  $WEEKLY_CRON"
echo ""
echo "Vérifier avec : crontab -l | grep 'driveco-qa-pipeline'"
echo ""

# ── Test de connectivité facultatif ──────────────────────────────────────────
if [ "${1:-}" = "--test" ]; then
  echo "=== Test de connectivité ==="
  "$PYTHON_BIN" "$SCRIPT" --mode test
fi
