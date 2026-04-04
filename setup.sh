#!/bin/bash
# ============================================================
# setup.sh — Installation du pipeline QA Driveco sur Mac Mini
# Lancer UNE seule fois : bash setup.sh
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
echo ""
echo "=== Installation Pipeline QA Driveco ==="
echo "Répertoire : $SCRIPT_DIR"
echo ""

# ── 1. Vérifier Python 3.11+ ─────────────────────────────────────────────────
echo "▶ Vérification Python..."
PYTHON=$(which python3.11 2>/dev/null || which python3 2>/dev/null || echo "")
if [ -z "$PYTHON" ]; then
    echo "❌ Python 3 non trouvé. Installer via : brew install python@3.11"
    exit 1
fi
PY_VERSION=$($PYTHON --version 2>&1)
echo "  ✅ $PY_VERSION ($PYTHON)"

# ── 2. Créer l'environnement virtuel ────────────────────────────────────────
echo "▶ Préparation de l'environnement virtuel..."
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
fi
VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip -q
"$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo "  ✅ Environnement virtuel prêt : $VENV_DIR"

# ── 3. Créer le .env si absent ───────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo ""
    echo "⚠️  IMPORTANT : Le fichier .env a été créé depuis le template."
    echo "   Remplis les valeurs manquantes avant de continuer :"
    echo "   → CF_WORKER_URL / CF_WORKER_AUTH"
    echo "   → AIRCALL_API_ID / AIRCALL_API_TOKEN"
    echo "   → ANTHROPIC_API_KEY"
    echo "   → NOTION_API_KEY / NOTION_KB_PAGE_ID / NOTION_REPORTS_PAGE_ID"
    echo "   → SLACK_BOT_TOKEN / SLACK_CHANNEL_ID"
    echo ""
    echo "   Fichier : $SCRIPT_DIR/.env"
    echo ""
else
    echo "  ✅ .env déjà présent (non écrasé)"
fi

# ── 4. Préparer les dossiers de sortie repo-locaux ──────────────────────────
echo "▶ Création des répertoires de sortie..."
mkdir -p "$SCRIPT_DIR/qa-driveco-data/logs" "$SCRIPT_DIR/qa-driveco-data/cache"
echo "  ✅ Dossiers qa-driveco-data prêts"

# ── 5. Test de connectivité ──────────────────────────────────────────────────
echo "▶ Test de connectivité (nécessite le .env rempli)..."
"$VENV_PYTHON" "$SCRIPT_DIR/analysis_pipeline.py" --mode test || true

# ── 6. Configurer le cron ────────────────────────────────────────────────────
echo ""
echo "▶ Configuration du cron..."
CRON_DAILY="0 7 * * * $VENV_PYTHON $SCRIPT_DIR/analysis_pipeline.py --mode daily >> $SCRIPT_DIR/qa-driveco-data/logs/daily.log 2>&1"
CRON_WEEKLY="30 7 * * 1 $VENV_PYTHON $SCRIPT_DIR/analysis_pipeline.py --mode weekly >> $SCRIPT_DIR/qa-driveco-data/logs/weekly.log 2>&1"

# Vérifie si les crons existent déjà
EXISTING=$(crontab -l 2>/dev/null || echo "")

if echo "$EXISTING" | grep -q "analysis_pipeline.py --mode daily"; then
    echo "  ✅ Cron quotidien déjà configuré"
else
    (echo "$EXISTING"; echo "$CRON_DAILY") | crontab -
    echo "  ✅ Cron quotidien ajouté (07h00 chaque jour)"
fi

if echo "$EXISTING" | grep -q "analysis_pipeline.py --mode weekly"; then
    echo "  ✅ Cron hebdomadaire déjà configuré"
else
    (crontab -l 2>/dev/null; echo "$CRON_WEEKLY") | crontab -
    echo "  ✅ Cron hebdomadaire ajouté (08h00 chaque lundi)"
fi

echo ""
echo "=== Installation terminée ==="
echo ""
echo "Prochaines étapes :"
echo "  1. Remplis $SCRIPT_DIR/.env avec tes clés API"
echo "  2. Lance le test : $VENV_PYTHON $SCRIPT_DIR/analysis_pipeline.py --mode test"
echo "  3. Lance une analyse manuelle : $VENV_PYTHON $SCRIPT_DIR/analysis_pipeline.py --mode daily --date 2026-03-24"
echo ""
