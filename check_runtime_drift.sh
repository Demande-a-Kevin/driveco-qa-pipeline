#!/usr/bin/env bash
# check_runtime_drift.sh — Détecte la dérive entre le repo SOURCE et le RUNTIME launchd.
#
# Le runtime launchd (~/Library/Application Support/driveco-qa-pipeline/runtime)
# est ce que macOS exécute réellement. Si quelqu'un édite le runtime en direct
# (ou édite la source sans resynchroniser), les deux divergent et on fait tourner
# du code différent de ce qu'on croit. Ce script compare les .py/.sh/.yaml,
# loggue les écarts et envoie une alerte Slack. À lancer depuis le watchdog ou à
# la main. Exit 2 si dérive détectée, 0 sinon.
set -euo pipefail

SOURCE_DIR="${QA_SOURCE_DIR:-/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline}"
RUNTIME_DIR="${QA_RUNTIME_DIR:-$HOME/Library/Application Support/driveco-qa-pipeline/runtime}"
PYTHON_BIN="${PYTHON_BIN:-$SOURCE_DIR/.venv/bin/python}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="$RUNTIME_DIR/.venv/bin/python"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"

QA_SOURCE_DIR="$SOURCE_DIR" QA_RUNTIME_DIR="$RUNTIME_DIR" "$PYTHON_BIN" - <<'PY'
import os
import sys
from pathlib import Path

src = os.environ["QA_SOURCE_DIR"]
rt = os.environ["QA_RUNTIME_DIR"]
# On importe ops_guards depuis la SOURCE (référence de vérité).
sys.path.insert(0, src)
import ops_guards  # noqa: E402

drift = ops_guards.runtime_drift_report(Path(src), Path(rt))
if not drift:
    print("no_drift")
    sys.exit(0)

lines = "\n".join(f"- {d['status']}: {d['file']}" for d in drift)
print(f"DRIFT ({len(drift)} fichier(s)):\n{lines}")
try:
    import notifier
    notifier.send_alert(
        f"⚠️ Dérive code source↔runtime QA détectée ({len(drift)} fichier(s)). "
        "Le runtime launchd ne reflète pas le repo source — resynchroniser via `deploy.sh`.\n"
        f"{lines}",
        level="warning",
    )
except Exception:
    pass
sys.exit(2)
PY
