"""
ops_guards.py — Garde-fous opérationnels du run quotidien.

Objectif : empêcher qu'une modification faite ailleurs (CSAT, cockpit, backfill…)
ne casse silencieusement le run QA quotidien. Deux garde-fous indépendants :

1. validate_publish_config() / run_preflight_or_abort()
   Preflight *fail-fast*. Au tout début d'un `--mode daily`, on vérifie que les
   clés requises par la publication (liste versionnée dans `.env.qa.required`)
   sont présentes dans la config active AVANT de lancer des heures de calcul.
   Une clé requise manquante => échec en quelques secondes + alerte Slack, au
   lieu de découvrir l'absence après un run de plusieurs heures qui ne publie rien.
   (C'est exactement le scénario qui a fait perdre 2 jours de reporting.)

2. runtime_drift_report()
   Compare les fichiers `.py` du repo *source* et du *runtime launchd* et
   signale toute divergence — le classique « édité en direct sans resynchroniser »
   qui fait tourner du code différent de ce qu'on croit.
"""
from __future__ import annotations

import os
from pathlib import Path

import config

BASE_DIR = Path(__file__).resolve().parent
REQUIRED_MANIFEST = BASE_DIR / ".env.qa.required"


class PreflightError(RuntimeError):
    """Levée quand une clé *required* du run quotidien est absente."""


# ── Manifeste des clés requises ────────────────────────────────────────────────

def parse_required_manifest(path: Path | None = None) -> dict[str, list[str]]:
    """Lit `.env.qa.required` -> {"required": [...], "warn": [...]}.

    Format : sections `[required]` / `[warn]`, une clé par ligne, `#` = commentaire.
    Si le manifeste est absent, on renvoie des listes vides (fail-open : on ne
    bloque jamais un run à cause d'un manifeste manquant).
    """
    manifest_path = path or REQUIRED_MANIFEST
    sections: dict[str, list[str]] = {"required": [], "warn": []}
    if not manifest_path.exists():
        return sections
    current = "required"
    for raw in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip().lower()
            if name in sections:
                current = name
            continue
        sections[current].append(line.split("=", 1)[0].strip())
    return sections


def _key_is_present(key: str) -> bool:
    """Une clé est « présente » si la config active la résout en valeur non vide.

    On lit d'abord l'attribut résolu de `config` (reflète le .env chargé +
    valeurs par défaut), puis on retombe sur `os.environ` par sécurité.
    """
    value = getattr(config, key, None)
    if value is None:
        value = os.getenv(key)
    if value is None:
        return False
    text = str(value).strip()
    return bool(text)


def validate_publish_config(path: Path | None = None) -> dict[str, list[str]]:
    """Renvoie les clés manquantes : {"required": [...], "warn": [...]}."""
    manifest = parse_required_manifest(path)
    return {
        "required": [k for k in manifest["required"] if not _key_is_present(k)],
        "warn": [k for k in manifest["warn"] if not _key_is_present(k)],
    }


def run_preflight_or_abort(context: str = "daily", *, alerter=None, logger=None) -> None:
    """Preflight fail-fast pour le run quotidien.

    - clés `warn` manquantes  -> log + alerte Slack (non bloquant)
    - clés `required` manquantes -> alerte Slack best-effort + PreflightError

    `alerter(message, level)` et `logger` sont injectables pour les tests ; par
    défaut on utilise `notifier.send_alert` et le logger du pipeline.
    """
    missing = validate_publish_config()

    def _log(level: str, msg: str) -> None:
        if logger is not None:
            getattr(logger, level, logger.info)(msg)

    def _alert(message: str, level: str) -> None:
        if alerter is not None:
            alerter(message, level)
            return
        try:  # best-effort : ne jamais faire échouer le preflight sur l'alerte
            import notifier
            notifier.send_alert(message, level=level)
        except Exception:  # noqa: BLE001
            pass

    if missing["warn"]:
        keys = ", ".join(missing["warn"])
        _log("warning", f"[preflight] clés optionnelles absentes ({context}): {keys}")
        _alert(
            f"⚠️ Pipeline QA {context} : clés optionnelles absentes ({keys}). "
            "Le rapport sera publié mais en sortie dégradée (ex. cockpit/Supabase non alimenté).",
            "warning",
        )

    if missing["required"]:
        keys = ", ".join(missing["required"])
        message = (
            f"🛑 Pipeline QA {context} ABORTÉ avant calcul : clés requises absentes "
            f"({keys}). Vérifier le .env actif — probablement écrasé par une autre modif "
            "(CSAT/cockpit). Aucun run lancé."
        )
        _log("error", f"[preflight] {message}")
        _alert(message, "critical")
        raise PreflightError(message)

    _log("info", f"[preflight] config de publication validée ({context}).")


# ── Détecteur de dérive source <-> runtime ─────────────────────────────────────

def runtime_drift_report(source_dir: Path, runtime_dir: Path,
                         patterns: tuple[str, ...] = ("*.py", "*.sh", "*.yaml")) -> list[dict]:
    """Compare le code source et le runtime launchd, fichier par fichier.

    Renvoie une liste d'écarts : [{"file": rel, "status": ...}], status ∈
    {"differs", "missing_in_runtime", "missing_in_source"}. Liste vide => pas de
    dérive. On ignore les répertoires de données / caches / venv / archives.
    """
    import fnmatch

    ignore_parts = {".venv", "qa-driveco-data", "__pycache__", "archives",
                    ".git", "node_modules", "tests"}

    def _iter_files(root: Path) -> dict[str, Path]:
        found: dict[str, Path] = {}
        if not root.exists():
            return found
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if ignore_parts & set(p.relative_to(root).parts):
                continue
            if not any(fnmatch.fnmatch(p.name, pat) for pat in patterns):
                continue
            found[str(p.relative_to(root))] = p
        return found

    src = _iter_files(source_dir)
    rt = _iter_files(runtime_dir)
    drift: list[dict] = []
    for rel in sorted(set(src) | set(rt)):
        if rel not in rt:
            drift.append({"file": rel, "status": "missing_in_runtime"})
        elif rel not in src:
            drift.append({"file": rel, "status": "missing_in_source"})
        elif src[rel].read_bytes() != rt[rel].read_bytes():
            drift.append({"file": rel, "status": "differs"})
    return drift
