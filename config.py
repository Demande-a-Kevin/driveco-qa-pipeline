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


def _float_env(name: str, default: float) -> float:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_set_env(name: str, default: str) -> set[int]:
    out: set[int] = set()
    for item in _split_csv_env(name, default):
        try:
            out.add(int(item))
        except ValueError:
            continue
    return out

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
AIRCALL_CALL_HISTORY_LINE_IDS = _int_set_env(
    "AIRCALL_CALL_HISTORY_LINE_IDS",
    ",".join(
        str(line_id)
        for line_id in (
            AIRCALL_ASSISTANCE_LINE_ID,
            AIRCALL_MAINTENANCE_LINE_ID,
            AIRCALL_UCC_TRANSFER_LINE_ID,
            1075934,  # Belgique
            1075935,  # Italie
            1075937,  # Espagne
        )
    ),
)

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
    os.getenv("OLLAMA_MODEL_ANALYSIS") or os.getenv("OLLAMA_MODEL_SCREENING") or "gemma4:12b",
)
OLLAMA_MODEL_SCREENING  = OLLAMA_FIXED_MODEL
OLLAMA_MODEL_ANALYSIS   = OLLAMA_FIXED_MODEL
OLLAMA_TIMEOUT          = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_ANALYSIS_TIMEOUT = int(os.getenv("OLLAMA_ANALYSIS_TIMEOUT", "600"))
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
# num_ctx : 16384 par défaut sur gemma4. Mesure 13/06 (mono-locataire) : 8192,
# 16384 et 32768 chargent tous à 100% GPU et tournent ~66 s/appel — le num_ctx
# n'était PAS le goulot (la contention l'était, cf. chantier 0.1). 16384 garde une
# marge mémoire confortable pour la cohabitation diurne (catchup + insights) tout
# en couvrant la quasi-totalité des transcripts une fois tronqués (TRANSCRIPT_MAX_CHARS).
OLLAMA_NUM_CTX          = _optional_int_env(
    "OLLAMA_NUM_CTX",
    16384 if OLLAMA_FIXED_MODEL.startswith("gemma4") else None,
)
# keep_alive : garde le modèle résident entre les batches du daily pour éviter un
# rechargement (≈ plusieurs s) à chaque batch. Ressource partagée du Mac mini :
# la nuit, le 12B doit rester chaud et seul (cf. pause des insights 23h-08h).
OLLAMA_KEEP_ALIVE       = os.getenv("OLLAMA_KEEP_ALIVE", "30m").strip()
# ── Analyse one-shot (1 appel = factual + scorecard + VoC) ────────────────────
# Réduit le nombre d'appels Ollama (1 au lieu de 3) → runs plus rapides. Le
# fallback legacy (3 passes) reste actif si la sortie one-shot est invalide.
OLLAMA_ANALYSIS_ONE_SHOT = os.getenv("OLLAMA_ANALYSIS_ONE_SHOT", "true").strip().lower() in {"1", "true", "yes", "on"}
OLLAMA_LEGACY_FALLBACK_ON_ONE_SHOT_FAILURE = os.getenv(
    "OLLAMA_LEGACY_FALLBACK_ON_ONE_SHOT_FAILURE", "true"
).strip().lower() in {"1", "true", "yes", "on"}
OLLAMA_ONE_SHOT_MAX_TOKENS = int(os.getenv("OLLAMA_ONE_SHOT_MAX_TOKENS", "5200"))
# Timeout court : un appel pendu échoue vite (→ fallback) au lieu de bloquer 1h.
OLLAMA_ONE_SHOT_TIMEOUT = int(os.getenv("OLLAMA_ONE_SHOT_TIMEOUT", "300"))
OLLAMA_ONE_SHOT_MAX_ATTEMPTS = int(os.getenv("OLLAMA_ONE_SHOT_MAX_ATTEMPTS", "1"))
OLLAMA_TEMPERATURE      = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_TOP_P            = float(os.getenv("OLLAMA_TOP_P", "0.95"))
OLLAMA_TOP_K            = int(os.getenv("OLLAMA_TOP_K", "64"))
OLLAMA_ENABLE_THINKING  = os.getenv("OLLAMA_ENABLE_THINKING", "false").strip().lower() in {"1", "true", "yes", "on"}

# Chantier A : style du post Slack quotidien. "compact" (défaut) = exception-based,
# ≤10 blocs (header, config, KPIs, "à regarder", liens). "full" = post historique
# détaillé. Rollback instantané par variable. L'hebdo reste toujours en détaillé.
SLACK_REPORT_STYLE = os.getenv("SLACK_REPORT_STYLE", "compact").strip().lower()
# Base URL du cockpit (lien dans le post compact). Vide = lien omis.
COCKPIT_BASE_URL = os.getenv("COCKPIT_BASE_URL", "").strip().rstrip("/")
# Seuil de significativité d'un score QA par scope (chantier 0.5). En dessous,
# le post Slack affiche ⚪ + n au lieu d'un rouge/vert trompeur sur trop peu d'appels.
SCORE_MIN_N = int(os.getenv("SCORE_MIN_N", "10"))


def git_describe() -> str:
    """Version du code pour le header de run. Best-effort. En runtime launchd
    (pas un repo git), lit le fichier .runtime_version écrit par sync_launchd_runtime.sh."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    # Runtime launchd : version figée au déploiement.
    try:
        vf = BASE_DIR / ".runtime_version"
        if vf.exists():
            txt = vf.read_text(encoding="utf-8").strip()
            if txt:
                return txt
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def runtime_config_summary() -> str:
    """Ligne unique de config effective au démarrage d'un run (chantier 0.5).
    Rend le drift visible immédiatement (modèle, num_ctx, budget, couverture, version)."""
    budget = DAILY_MAX_WALL_SECONDS
    budget_txt = f"{budget // 60}min" if budget else "∞"
    cov = f"{int(ANALYSIS_COVERAGE_PCT * 100)}%"
    return (
        f"modèle={OLLAMA_FIXED_MODEL} num_ctx={OLLAMA_NUM_CTX} keep_alive={OLLAMA_KEEP_ALIVE} "
        f"budget={budget_txt} couverture_cible={cov} insight_pause={INSIGHT_PAUSE_WINDOW} "
        f"code={git_describe()}"
    )


# ── Pause nocturne des jobs Insight (chantier 0.1) ───────────────────────────
# Les jobs CSAT/Sentiment Insight (launchd toutes les 3 min) partagent le même
# Ollama que le daily QA. Pendant le run de nuit, le 12B doit être SEUL en RAM
# (sinon offload partiel CPU → ~25 min/appel au lieu de ~1 min, mesuré le 13/06).
# Fenêtre HH:MM-HH:MM (peut enjamber minuit). Dans la fenêtre, les jobs insight
# loguent une ligne et exit 0 (pas d'erreur). Le curseur d'état n'avance pas →
# rattrapage automatique des posts de la nuit à la reprise (08:00). Vide = désactivé.
INSIGHT_PAUSE_WINDOW    = os.getenv("INSIGHT_PAUSE_WINDOW", "23:00-08:00").strip()


def _parse_hhmm(s: str) -> int | None:
    """'HH:MM' → minutes depuis minuit, ou None si invalide."""
    try:
        h, m = s.strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except (ValueError, AttributeError):
        pass
    return None


def insight_paused_now(now=None) -> bool:
    """True si l'instant courant est dans INSIGHT_PAUSE_WINDOW (gère l'enjambement
    de minuit). Fenêtre vide/invalide → jamais en pause."""
    window = INSIGHT_PAUSE_WINDOW
    if not window or "-" not in window:
        return False
    start_s, end_s = window.split("-", 1)
    start = _parse_hhmm(start_s)
    end = _parse_hhmm(end_s)
    if start is None or end is None:
        return False
    import datetime as _dt
    now = now or _dt.datetime.now()
    cur = now.hour * 60 + now.minute
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    # fenêtre qui enjambe minuit (ex. 23:00-08:00)
    return cur >= start or cur < end
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
SLACK_ALERT_CHANNEL_ID      = os.getenv("SLACK_ALERT_CHANNEL_ID", SLACK_CHANNEL_ID)

# ── CSAT Call Insight ─────────────────────────────────────────────────────────
SLACK_CSAT_CHANNEL_ID = os.getenv("SLACK_CSAT_CHANNEL_ID", "C0B724V5X4L")
SLACK_BOT_USER_ID     = os.getenv("SLACK_BOT_USER_ID", "U0AMEHDCDV5")  # bot Kev1n
DISABLE_CSAT_INSIGHT  = os.getenv("DISABLE_CSAT_INSIGHT", "false").strip().lower() in {"1", "true", "yes", "on"}

# ── Sentiment Call Insight (canal UCC sentiment) ──────────────────────────────
SLACK_SENTIMENT_CHANNEL_ID = os.getenv("SLACK_SENTIMENT_CHANNEL_ID", "C0B7PA2EZQ8")
DISABLE_SENTIMENT_INSIGHT  = os.getenv("DISABLE_SENTIMENT_INSIGHT", "false").strip().lower() in {"1", "true", "yes", "on"}
SENTIMENT_INSIGHT_MAX_PER_RUN = int(os.getenv("SENTIMENT_INSIGHT_MAX_PER_RUN", "5"))

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
DAILY_REUSE_EXISTING_EVALUATIONS = os.getenv(
    "DAILY_REUSE_EXISTING_EVALUATIONS", "false"
).strip().lower() in {"1", "true", "yes", "on"}
DAILY_REUSE_EXISTING_TRANSCRIPTS = os.getenv(
    "DAILY_REUSE_EXISTING_TRANSCRIPTS", "false"
).strip().lower() in {"1", "true", "yes", "on"}

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
ANALYSIS_COVERAGE_PCT   = min(1.0, max(0.0, _float_env("ANALYSIS_COVERAGE_PCT", 1.0)))
ANALYSIS_BATCH_SIZE     = 10     # Appels par batch (metadata-only ou mixte)
ANALYSIS_BATCH_SIZE_TX  = 5      # Appels par batch quand transcript inclus
TOP_PROBLEMATIC_CALLS   = 5      # Top appels problématiques isolés dans le rapport
# Cap optionnel (None par défaut = 75% couverture préservée).
# À n'activer que pour un incident ponctuel via env DAILY_MAX_CALLS_ANALYZED=<n>.
DAILY_MAX_CALLS_ANALYZED = _optional_int_env("DAILY_MAX_CALLS_ANALYZED", None)
# Garde anti-marathon : budget temps (secondes) sur la phase d'analyse LLM du
# run *daily*. Au-delà, on arrête d'analyser de nouveaux batches et on publie un
# rapport dégradé avec ce qui est déjà calculé, au lieu de tenir le lock 16h et
# de bloquer les runs suivants. None / 0 = désactivé. 5400 = 90 min.
DAILY_MAX_WALL_SECONDS = _optional_int_env("DAILY_MAX_WALL_SECONDS", 5400)
# Chantier 0.6 : budget propre du run de rattrapage (--mode catchup), qui tourne
# en journée et cohabite avec les jobs insight. Défaut 120 min par passe.
CATCHUP_MAX_WALL_SECONDS = _optional_int_env("CATCHUP_MAX_WALL_SECONDS", 7200)
# Profondeur max du rattrapage : on reprend les pending de J-1 et J-2 (au-delà,
# considéré comme perdu — évite d'accumuler indéfiniment).
CATCHUP_MAX_LOOKBACK_DAYS = int(os.getenv("CATCHUP_MAX_LOOKBACK_DAYS", "2"))
# Nombre de batches Ollama traités en parallèle (ThreadPoolExecutor).
# 1 = comportement séquentiel historique. Gemma4 tolère 2-3 sur Mac mini.
OLLAMA_ANALYSIS_MAX_WORKERS = max(1, int(os.getenv("OLLAMA_ANALYSIS_MAX_WORKERS", "2")))
# Cache idempotent des analyses Ollama (hash transcript+prompt+modèle).
# Évite de re-payer le temps Ollama sur un rerun manuel même date.
LLM_CACHE_ENABLED = os.getenv("LLM_CACHE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
# Version du prompt QA : à bumper manuellement quand on modifie
# qa_prompting.build_extraction_messages / build_scoring_messages / build_voc_messages
# ou le schéma CallEvaluation. Invalide le cache en douceur.
LLM_ANALYSIS_CACHE_VERSION = os.getenv("LLM_ANALYSIS_CACHE_VERSION", "v2")
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
ALLOW_EMPTY_DAILY_REPORT = os.getenv("ALLOW_EMPTY_DAILY_REPORT", "false").strip().lower() in {"1", "true", "yes", "on"}
# Garde anti-volume-anormalement-bas : la source D1 (worker Cloudflare) n'est pas
# toujours alimentée pour la veille à l'heure du cron daily (01:00). Quand elle ne
# l'est pas encore, fetch_calls_for_date renvoie une poignée d'appels et le
# pipeline publiait un rapport trompeur ("1 appel, 9.4/10", alertes stats dégénérées).
# On bloque donc la publication quand le volume brut est sous ce plancher : le run
# échoue proprement (aucun rapport/flag écrit) et le watchdog de 06:45 relance une
# fois D1 complet. Override pour une journée réellement très creuse : ALLOW_LOW_VOLUME_DAILY_REPORT=true.
MIN_DAILY_RAW_CALLS = _optional_int_env("MIN_DAILY_RAW_CALLS", 15)
ALLOW_LOW_VOLUME_DAILY_REPORT = os.getenv("ALLOW_LOW_VOLUME_DAILY_REPORT", "false").strip().lower() in {"1", "true", "yes", "on"}

# ── Obsidian publication ────────────────────────────────────────────────────
# Dépose les rapports Markdown (daily/weekly) dans un vault Obsidian local
# pour archivage et consultation hors ligne. Désactivé si le chemin n'existe pas.
_DEFAULT_OBSIDIAN_VAULT = Path("/Users/kev1n/Documents/Obsidian/Kev1n")
OBSIDIAN_VAULT_DIR      = _resolve_path_env("OBSIDIAN_VAULT_DIR", _DEFAULT_OBSIDIAN_VAULT)
OBSIDIAN_REPORTS_SUBDIR = os.getenv("OBSIDIAN_REPORTS_SUBDIR", "Driveco QA").strip() or "Driveco QA"
DISABLE_OBSIDIAN_PUBLISH = os.getenv("DISABLE_OBSIDIAN_PUBLISH", "false").strip().lower() in {"1", "true", "yes", "on"}
# KB Obsidian : source de la KB consommée par la pipeline QA (mirror de la page Notion configurée).
OBSIDIAN_KB_SUBDIR      = os.getenv("OBSIDIAN_KB_SUBDIR", "Driveco QA/KB").strip() or "Driveco QA/KB"
# Si true : la pipeline lit la KB depuis Obsidian au lieu de Notion.
OBSIDIAN_KB_ENABLED     = os.getenv("OBSIDIAN_KB_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
SKIP_KB_SYNC            = os.getenv("SKIP_KB_SYNC", "false").strip().lower() in {"1", "true", "yes", "on"}

# Crée les répertoires si absents
REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
NOTION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
