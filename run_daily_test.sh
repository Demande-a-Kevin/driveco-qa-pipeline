#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

TEST_DATE="${1:-$(python3 - <<'PY'
from datetime import date, timedelta
print((date.today() - timedelta(days=1)).isoformat())
PY
)}"

mkdir -p "$SCRIPT_DIR/qa-driveco-data/logs"
cd "$SCRIPT_DIR"
"$PYTHON_BIN" analysis_pipeline.py --mode daily --date "$TEST_DATE" \
  > "$SCRIPT_DIR/qa-driveco-data/logs/manual_test.log" 2>&1
echo "EXIT:$?" >> "$SCRIPT_DIR/qa-driveco-data/logs/manual_test.log"
