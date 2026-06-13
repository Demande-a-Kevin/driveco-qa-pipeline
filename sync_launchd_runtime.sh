#!/usr/bin/env bash
set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="${LAUNCHD_RUNTIME_DIR:-$HOME/Library/Application Support/driveco-qa-pipeline/runtime}"
RUNTIME_VENV="$RUNTIME_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"

if [ -z "$PYTHON_BIN" ]; then
  echo "python3 introuvable" >&2
  exit 1
fi

mkdir -p "$RUNTIME_DIR"

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync introuvable" >&2
  exit 1
fi

rsync -a \
  --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'archives/' \
  --exclude 'qa-driveco-data/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  --exclude '.csat_insight_state.json' \
  --exclude '.sentiment_insight_state.json' \
  "$PIPELINE_DIR/" "$RUNTIME_DIR/"

mkdir -p \
  "$RUNTIME_DIR/qa-driveco-data/logs" \
  "$RUNTIME_DIR/qa-driveco-data/cache"

for extra_file in .env gdrive_credentials.json gdrive_token.json; do
  if [ -f "$PIPELINE_DIR/$extra_file" ]; then
    cp "$PIPELINE_DIR/$extra_file" "$RUNTIME_DIR/$extra_file"
  fi
done

# Chantier 0.5 : fige la version du code au déploiement (le runtime n'est pas un
# repo git) → lisible dans le header de run pour repérer tout drift de version.
git -C "$PIPELINE_DIR" describe --tags --always --dirty > "$RUNTIME_DIR/.runtime_version" 2>/dev/null || true

if [ ! -x "$RUNTIME_VENV/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$RUNTIME_VENV"
fi

if [ ! -x "$RUNTIME_VENV/bin/pip" ]; then
  "$RUNTIME_VENV/bin/python" -m ensurepip --upgrade
fi

"$RUNTIME_VENV/bin/python" -m pip install --upgrade pip -q
"$RUNTIME_VENV/bin/python" -m pip install -r "$RUNTIME_DIR/requirements.txt" -q

echo "Runtime launchd synchronisé : $RUNTIME_DIR"
