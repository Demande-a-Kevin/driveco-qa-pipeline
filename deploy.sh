#!/usr/bin/env bash
# deploy.sh — Déploiement SÉCURISÉ du repo source vers le runtime launchd.
#
# Le runtime (~/Library/Application Support/driveco-qa-pipeline/runtime) est ce
# que macOS exécute réellement. Ce wrapper applique le workflow obligatoire du
# CLAUDE.md : lancer la suite pytest, et ne synchroniser vers le runtime QUE si
# TOUT est vert. Empêche qu'on pousse du code cassé (ce que les modifs récentes
# faites en direct ont permis). Utiliser CECI au lieu d'appeler sync_launchd
# directement.
set -euo pipefail
PIPELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PIPELINE_DIR"
PYTHON_BIN="${PYTHON_BIN:-$PIPELINE_DIR/.venv/bin/python}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"

echo "▶ 1/2  Tests (pytest -x)…"
if ! "$PYTHON_BIN" -m pytest -x -q; then
  echo "" >&2
  echo "✖ Tests en échec — déploiement ANNULÉ. Le runtime n'a PAS été touché." >&2
  exit 1
fi

echo ""
echo "▶ 2/2  Tests verts → synchronisation runtime + launchd…"
bash "$PIPELINE_DIR/sync_launchd_runtime.sh"
bash "$PIPELINE_DIR/setup_launchd.sh"
echo ""
echo "✔ Déploiement terminé : runtime synchronisé après tests verts."
