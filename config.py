"""
config.py — Centralise toutes les constantes et la configuration du pipeline.
Charge automatiquement le .env au démarrage.
"""
import os
from pathlib import Path
from datetime import date
from dotenv import load_dotenv

# Charge .env depuis le répertoire du script
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _split_csv_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _resolve_path_env(name: str, default: Path | str) -> Path:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        candidate = Path(default)
    else:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = BASE_DIR / candidate
    return candidate.resolve()


def _optional_int_env(name: str, default: int | None = None) -> int | None:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else None

# ── Cloudflare ──────────────────────────────────────────────────────────────
# Les IDs Cloudflare sont des métadonnées internes. On évite de les hardcoder
# pour forcer une config explicite par environnement.
CF_ACCOUNT_ID       = os.getenv("CF_ACCOUNT_ID", "")
CF_D1_DB_ID         = os.getenv("CF_D1_DATABASE_ID", "")
CF_API_TOKEN        = os.getenv("CF_API_TOKEN", "")
CF_WORKER_URL       = os.getenv("CF_WORKER_URL", "")
CF_WORKER_AUTH      = os.getenv("CF_WORKER_AUTH", "")

# ── Aircall ──────────────────────────────────────────────────────────────────
AIRCALL_API_ID      = os.getenv("AIRCALL_API_ID", "")
AIRCALL_API_TOKEN   = os.getenv("AIRCALL_API_TOKEN", "")
AIRCALL_ASSISTANCE_LINE_ID  = int(os.getenv("AIRCALL_ASSISTANCE_LINE_ID", "785174"))
AIRCALL_MAINTENANCE_LINE_ID = int(os.getenv("AIRCALL_MAINTENANCE_LINE_ID", "785175"))
AIRCALL_UCC_TRANSFER_LINE_ID = int(os.getenv("AIRCALL_UCC_TRANSFER_LINE_ID", "1214611"))
AIRCALL_BASE_URL    = "https://api.aircall.io/v1"

# ── Anthropic ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
# Modèles par défaut — surchargés dynamiquement depuis qa_config en DB
MODEL_STANDARD      = "claude-haiku-4-5-20251001"
MODEL_FLAGGED       = "claude-sonnet-4-6"
MODEL_REPORTING     = "claude-sonnet-4-6"

# ── Ollama (local, Mac mini Kev1n) ───────────────────────────────────────────
OLLAMA_BASE_URL         = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_FIXED_MODEL      = os.getenv(
    "OLLAMA_FIXED_MODEL",
    os.getenv("OLLAMA_MODEL_ANALYSIS") or os.getenv("OLLAMA_MODEL_SCREENING") or "gemma4:latest",
)
OLLAMA_MODEL_SCREENING  = OLLAMA_FIXED_MODEL
OLLAMA_MODEL_ANALYSIS   = OLLAMA_FIXED_MODEL
OLLAMA_TIMEOUT          = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_ANALYSIS_TIMEOUT = int(os.getenv("OLLAMA_ANALYSIS_TIMEOUT", "3600"))
OLLAMA_PRESCREEN_TIMEOUT = int(
    os.getenv(
        "OLLAMA_PRESCREEN_TIMEOUT",
        "180" if OLLAMA_FIXED_MODEL.startswith("gemma4") else "15",
    )
)
OLLAMA_PRESCREEN_BATCH_SIZE = int(
    os.getenv("OLLAMA_PRESCREEN_BATCH_SIZE", "4" if OLLAMA_FIXED_MODEL.startswith("gemma4") else "8")
)
OLLAMA_ANALYSIS_BATCH_SIZE = int(
    os.getenv("OLLAMA_ANALYSIS_BATCH_SIZE", "3" if OLLAMA_FIXED_MODEL.startswith("gemma4") else "5")
)
OLLAMA_TRANSCRIPT_MAX_CHARS = int(
    os.getenv(
        "OLLAMA_TRANSCRIPT_MAX_CHARS",
        "3600" if OLLAMA_FIXED_MODEL.startswith("gemma4") else "2200",
    )
)
OLLAMA_NUM_CTX          = _optional_int_env(
    "OLLAMA_NUM_CTX",
    32768 if OLLAMA_FIXED_MODEL.startswith("gemma4") else None,
)
OLLAMA_TEMPERATURE      = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_TOP_P            = float(os.getenv("OLLAMA_TOP_P", "0.95"))
OLLAMA_TOP_K            = int(os.getenv("OLLAMA_TOP_K", "64"))
OLLAMA_ENABLE_THINKING  = os.getenv("OLLAMA_ENABLE_THINKING", "false").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_ANTHROPIC_CONSOLIDATION = os.getenv("ENABLE_ANTHROPIC_CONSOLIDATION", "false").strip().lower() in {"1", "true", "yes", "on"}
# Seuil de risque au-delà duquel Ollama fait l'analyse complète (0-10)
OLLAMA_RISK_THRESHOLD   = float(os.getenv("OLLAMA_RISK_THRESHOLD", "4.0"))
# Seuil au-delà duquel Claude Haiku re-évalue (appels très problématiques)
HAIKU_REEVAL_THRESHOLD  = float(os.getenv("HAIKU_REEVAL_THRESHOLD", "7.0"))

# ── Notion ───────────────────────────────────────────────────────────────────
NOTION_API_KEY      = os.getenv("NOTION_API_KEY", "")
NOTION_KB_PAGE_ID   = os.getenv("NOTION_KB_PAGE_ID", "")
NOTION_CACHE_TTL    = 604800  # 7 jours en secondes (KB évolue lentement)
# Page Analytics Driveco où les rapports QA sont archivés
NOTION_REPORTS_PAGE_ID = os.getenv("NOTION_REPORTS_PAGE_ID", "")

# ── Slack ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN     = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID    = os.getenv("SLACK_CHANNEL_ID", "")
SLACK_VOC_ALERTS_CHANNEL_ID = os.getenv("SLACK_VOC_ALERTS_CHANNEL_ID", SLACK_CHANNEL_ID)

# ── Supabase ────────────────────────────────────────────────────────────────
SUPABASE_URL        = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_DASHBOARD_ANON_KEY = os.getenv("SUPABASE_DASHBOARD_ANON_KEY", "")
SUPABASE_TIMEOUT_SECONDS = int(os.getenv("SUPABASE_TIMEOUT_SECONDS", "20"))

# ── VoC ──────────────────────────────────────────────────────────────────────
ENABLE_VOC_ANALYSIS = os.getenv("ENABLE_VOC_ANALYSIS", "true").strip().lower() in {"1", "true", "yes", "on"}
VOC_VERBATIM_RETENTION_DAYS = int(os.getenv("VOC_VERBATIM_RETENTION_DAYS", "180"))
VOC_MIN_WEAK_SIGNAL_COUNT = int(os.getenv("VOC_MIN_WEAK_SIGNAL_COUNT", "3"))
ENABLE_CLAUDE_SHADOW = os.getenv("ENABLE_CLAUDE_SHADOW", "false").strip().lower() in {"1", "true", "yes", "on"}
CLAUDE_SHADOW_SAMPLE_PCT = float(os.getenv("CLAUDE_SHADOW_SAMPLE_PCT", "0.10"))
RELIABILITY_MAE_ALERT_THRESHOLD = float(os.getenv("RELIABILITY_MAE_ALERT_THRESHOLD", "1.0"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8788"))
RUN_DEGRADED_THRESHOLD = float(os.getenv("RUN_DEGRADED_THRESHOLD", "0.5"))

# ── Lignes Aircall ───────────────────────────────────────────────────────────
# Lignes analysées pour le QA UCC (assistance + transferts chauds vers Care)
UCC_LINE_IDS        = {AIRCALL_ASSISTANCE_LINE_ID, AIRCALL_UCC_TRANSFER_LINE_ID}
# Ligne backup / maintenance — présente dans les données mais hors scope QA UCC
BACKUP_LINE_IDS     = {AIRCALL_MAINTENANCE_LINE_ID}

# ── Seuils KPI ───────────────────────────────────────────────────────────────
KPI_THRESHOLDS = {
    "pickup_rate":               {"green": 85, "yellow": 70, "higher_is_better": True},
    "overflow_rate":             {"green": 10, "yellow": 20, "higher_is_better": False},
    "abandon_rate":              {"green": 8,  "yellow": 15, "higher_is_better": False},
    "kb_compliance_rate":        {"green": 80, "yellow": 60, "higher_is_better": True},
    "unnecessary_escalation_rate": {"green": 10, "yellow": 25, "higher_is_better": False},
    "warm_transfer_rate":        {"green": 15, "yellow": 25, "higher_is_better": False},
    "resolution_rate":           {"green": 80, "yellow": 65, "higher_is_better": True},
}

# ── Google Drive ─────────────────────────────────────────────────────────────
GDRIVE_FOLDER_ID        = os.getenv("GDRIVE_FOLDER_ID", "")
GDRIVE_CREDENTIALS_FILE = str(
    _resolve_path_env("GDRIVE_CREDENTIALS_FILE", BASE_DIR / "gdrive_credentials.json")
)
GDRIVE_TOKEN_FILE       = str(
    _resolve_path_env("GDRIVE_TOKEN_FILE", BASE_DIR / "gdrive_token.json")
)

# ── Bornes temporelles d'analyse ────────────────────────────────────────────
# Ne jamais analyser des données antérieures à cette date
ANALYSIS_MIN_DATE = date(2026, 3, 1)

# ── Couverture d'analyse ─────────────────────────────────────────────────────
# % d'appels QA soumis à l'analyse (pré-screening Ollama puis LLM)
ANALYSIS_COVERAGE_PCT   = 0.75   # 75% des appels analysables
ANALYSIS_BATCH_SIZE     = 10     # Appels par batch (metadata-only ou mixte)
ANALYSIS_BATCH_SIZE_TX  = 5      # Appels par batch quand transcript inclus
TOP_PROBLEMATIC_CALLS   = 5      # Top appels problématiques isolés dans le rapport
# Cap optionnel (None par défaut = 75% couverture préservée).
# À n'activer que pour un incident ponctuel via env DAILY_MAX_CALLS_ANALYZED=<n>.
DAILY_MAX_CALLS_ANALYZED = _optional_int_env("DAILY_MAX_CALLS_ANALYZED", None)
# Nombre de batches Ollama traités en parallèle (ThreadPoolExecutor).
# 1 = comportement séquentiel historique. Gemma4 tolère 2-3 sur Mac mini.
OLLAMA_ANALYSIS_MAX_WORKERS = max(1, int(os.getenv("OLLAMA_ANALYSIS_MAX_WORKERS", "2")))
# Cache idempotent des analyses Ollama (hash transcript+prompt+modèle).
# Évite de re-payer le temps Ollama sur un rerun manuel même date.
LLM_CACHE_ENABLED = os.getenv("LLM_CACHE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
# Version du prompt QA : à bumper manuellement quand on modifie
# qa_prompting.build_extraction_messages / build_scoring_messages / build_voc_messages
# ou le schéma CallEvaluation. Invalide le cache en douceur.
LLM_ANALYSIS_CACHE_VERSION = os.getenv("LLM_ANALYSIS_CACHE_VERSION", "v1")
LONG_CALL_THRESHOLD_SECONDS = int(os.getenv("LONG_CALL_THRESHOLD_SECONDS", "900"))
PEAK_WINDOW_SECONDS         = int(os.getenv("PEAK_WINDOW_SECONDS", "7200"))
PEAK_WINDOWS_TOP_N          = int(os.getenv("PEAK_WINDOWS_TOP_N", "3"))

# Numéros internes / techniques à exclure des "clients frustrés".
INTERNAL_PHONE_BLACKLIST = {
    "".join(ch for ch in item if ch.isdigit())
    for item in _split_csv_env(
        "INTERNAL_PHONE_BLACKLIST",
        default="33972562680,33187650773,393386655599",
    )
}

# ── Outputs ──────────────────────────────────────────────────────────────────
# Répertoire de sortie repo-local par défaut pour limiter les chemins implicites.
_DEFAULT_REPORT_DIR = BASE_DIR / "qa-driveco-data"
REPORT_OUTPUT_DIR   = _resolve_path_env("REPORT_OUTPUT_DIR", _DEFAULT_REPORT_DIR)
LOG_DIR             = _resolve_path_env("LOG_DIR", REPORT_OUTPUT_DIR / "logs")
NOTION_CACHE_PATH   = _resolve_path_env(
    "NOTION_CACHE_PATH",
    REPORT_OUTPUT_DIR / "cache" / "notion_kb_cache.json",
)
LLM_CACHE_DIR       = _resolve_path_env(
    "LLM_CACHE_DIR",
    REPORT_OUTPUT_DIR / "cache" / "ollama_analysis",
)
DISABLE_SLACK_NOTIFICATIONS = os.getenv("DISABLE_SLACK_NOTIFICATIONS", "false").strip().lower() in {"1", "true", "yes", "on"}
DISABLE_EXTERNAL_PUBLISH = os.getenv("DISABLE_EXTERNAL_PUBLISH", "false").strip().lower() in {"1", "true", "yes", "on"}

# ── Obsidian publication ────────────────────────────────────────────────────
# Dépose les rapports Markdown (daily/weekly) dans un vault Obsidian local
# pour archivage et consultation hors ligne. Désactivé si le chemin n'existe pas.
_DEFAULT_OBSIDIAN_VAULT = Path("/Users/kev1n/Documents/Obsidian/Kev1n")
OBSIDIAN_VAULT_DIR      = _resolve_path_env("OBSIDIAN_VAULT_DIR", _DEFAULT_OBSIDIAN_VAULT)
OBSIDIAN_REPORTS_SUBDIR = os.getenv("OBSIDIAN_REPORTS_SUBDIR", "Driveco QA").strip() or "Driveco QA"
DISABLE_OBSIDIAN_PUBLISH = os.getenv("DISABLE_OBSIDIAN_PUBLISH", "false").strip().lower() in {"1", "true", "yes", "on"}

# Crée les répertoires si absents
REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
NOTION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
