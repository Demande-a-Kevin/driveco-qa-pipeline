"""
config.py — Centralise toutes les constantes et la configuration du pipeline.
Charge automatiquement le .env au démarrage.
"""
import os
from pathlib import Path
from datetime import date
from dotenv import load_dotenv

# Charge .env depuis le répertoire du script
load_dotenv(Path(__file__).parent / ".env")


def _split_csv_env(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

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
OLLAMA_FIXED_MODEL      = "llama3.1:8b"
OLLAMA_MODEL_SCREENING  = OLLAMA_FIXED_MODEL
OLLAMA_MODEL_ANALYSIS   = OLLAMA_FIXED_MODEL
OLLAMA_TIMEOUT          = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_ANALYSIS_TIMEOUT = int(os.getenv("OLLAMA_ANALYSIS_TIMEOUT", "3600"))
OLLAMA_TRANSCRIPT_MAX_CHARS = int(os.getenv("OLLAMA_TRANSCRIPT_MAX_CHARS", "2200"))
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
GDRIVE_CREDENTIALS_FILE = os.getenv("GDRIVE_CREDENTIALS_FILE",
                            str(Path(__file__).parent / "gdrive_credentials.json"))
GDRIVE_TOKEN_FILE       = os.getenv("GDRIVE_TOKEN_FILE",
                            str(Path(__file__).parent / "gdrive_token.json"))

# ── Bornes temporelles d'analyse ────────────────────────────────────────────
# Ne jamais analyser des données antérieures à cette date
ANALYSIS_MIN_DATE = date(2026, 3, 1)

# ── Couverture d'analyse ─────────────────────────────────────────────────────
# % d'appels UCC soumis à l'analyse (pré-screening Ollama puis LLM)
ANALYSIS_COVERAGE_PCT   = 0.75   # 75% des appels UCC — modulable
ANALYSIS_BATCH_SIZE     = 10     # Appels par batch (metadata-only ou mixte)
ANALYSIS_BATCH_SIZE_TX  = 5      # Appels par batch quand transcript inclus
MAX_TRANSCRIPT_CALLS    = 20     # Max appels pour lesquels on tente le transcript Aircall AI
TOP_PROBLEMATIC_CALLS   = 5      # Top appels problématiques isolés dans le rapport
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
_DEFAULT_REPORT_DIR = str(Path(__file__).parent / "qa-driveco-data")
REPORT_OUTPUT_DIR   = Path(os.getenv("REPORT_OUTPUT_DIR", _DEFAULT_REPORT_DIR))
LOG_DIR             = Path(os.getenv("LOG_DIR", str(REPORT_OUTPUT_DIR / "logs")))
NOTION_CACHE_PATH   = Path(
    os.getenv("NOTION_CACHE_PATH", str(REPORT_OUTPUT_DIR / "cache" / "notion_kb_cache.json"))
)

# Crée les répertoires si absents
REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
NOTION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
