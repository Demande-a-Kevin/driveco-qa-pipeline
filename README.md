# driveco-qa-pipeline

Pipeline Python d'analyse qualité des appels Driveco. Tourne en autonomie sur un Mac mini sous macOS (`launchd`).

**Ce qu'il fait :**
- Récupère les appels depuis un worker Cloudflare (Aircall / D1)
- Classe les appels UCC et Driveco Care
- Analyse la qualité agent via Ollama local (Gemma 4)
- Extrait la voix du client (VoC) séparément
- Publie un rapport : **un seul post Slack** + Markdown local + Notion + Obsidian
- **CSAT Call Insight** — répond automatiquement en thread sous chaque post CSAT Sprig avec le lien transcript Aircall + verdict Gemma (agent vs borne/app, ≤ 55 mots), toutes les 3 min via launchd

## Documentation

| Doc | Contenu |
|-----|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Flux de données, modules, conventions métier, runtime vs repo |
| [RUNBOOK.md](RUNBOOK.md) | Exploitation, logs, checks matinaux, incidents fréquents |
| [CLAUDE.md](CLAUDE.md) | Instructions pour agents IA — règles, variables clés, pièges |

## Prérequis

- macOS (launchd) ou Linux (cron)
- Python 3.11+
- [Ollama](https://ollama.com) avec `gemma4:latest` chargé
- Accès au worker Cloudflare `driveco-aircall-worker`
- Comptes Aircall, Slack, Notion (Google Drive optionnel)

## Installation

```bash
cd "/chemin/vers/driveco-qa-pipeline"
bash setup.sh
```

Le script crée `.venv`, installe les dépendances, copie `.env.example` → `.env`, et prépare `qa-driveco-data/`.

## Configuration `.env`

```bash
cp .env.example .env
# Remplir les variables ci-dessous
```

**Variables indispensables :**

```env
# Worker Cloudflare (source appels)
CF_WORKER_URL=
CF_WORKER_AUTH=

# Aircall (transcripts)
AIRCALL_API_ID=
AIRCALL_API_TOKEN=

# Ollama local
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_FIXED_MODEL=gemma4:latest

# Supabase (analytique, optionnel)
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# Notion
NOTION_API_KEY=
NOTION_KB_PAGE_ID=
NOTION_REPORTS_PAGE_ID=

# Base de connaissances Obsidian (prioritaire si ENABLED=true)
OBSIDIAN_VAULT_DIR=/chemin/vers/vault
OBSIDIAN_KB_SUBDIR=Driveco QA/KB
OBSIDIAN_KB_ENABLED=true

# Slack
SLACK_BOT_TOKEN=
SLACK_CHANNEL_ID=

# Google Drive (optionnel)
GDRIVE_CREDENTIALS_FILE=
GDRIVE_TOKEN_FILE=
GDRIVE_FOLDER_ID=
```

> Note : `CF_ACCOUNT_ID`, `CF_D1_DATABASE_ID` et `CF_API_TOKEN` sont documentés dans `.env.example` mais non utilisés par le code Python — le flux passe par `CF_WORKER_AUTH`.

## Commandes utiles

```bash
# Test de connectivité
.venv/bin/python analysis_pipeline.py --mode test

# Run quotidien manuel (depuis le runtime)
cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python analysis_pipeline.py --mode daily --date 2026-04-27

# Run hebdomadaire manuel
.venv/bin/python analysis_pipeline.py --mode weekly --date 2026-04-27

# Tests unitaires
.venv/bin/python -m pytest -x --tb=short   # doit passer 41 tests
```

## Planification macOS (launchd)

Sur macOS, `launchd` est la méthode recommandée.  
macOS bloque l'accès disque si le code s'exécute directement depuis `Documents` ou `Desktop`.  
`setup_launchd.sh` crée un **runtime autonome** dans `~/Library/Application Support/` pour contourner cette restriction.

```bash
bash setup_launchd.sh
```

**Horaires par défaut :**

| Job | Déclenchement |
|-----|---------------|
| Benchmark Ollama | Tous les jours à 01:30 |
| Run daily | Tous les jours à **02:30** |
| Watchdog daily | Tous les jours à 06:45 |
| Reliability | Lundi à 04:00 |
| Run weekly | Lundi à **07:15** |

**Après chaque modification de code ou de `.env`** :

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

**Vérifier que les 5 jobs sont chargés :**

```bash
launchctl list | grep driveco
# Doit afficher 5 lignes : daily, daily-watchdog, weekly, reliability, benchmark
```

> **Piège** : après un reboot, `com.kev1n.driveco.qa.weekly` peut ne pas être rechargé automatiquement.  
> Si absent : `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kev1n.driveco.qa.weekly.plist`

**Surcharger les horaires :**

```bash
DAILY_HOUR=4 DAILY_MINUTE=0 WEEKLY_HOUR=8 WEEKLY_MINUTE=0 bash setup_launchd.sh
```

Variables disponibles : `BENCH_HOUR`, `BENCH_MINUTE`, `DAILY_HOUR`, `DAILY_MINUTE`, `WATCHDOG_HOUR`, `WATCHDOG_MINUTE`, `WEEKLY_HOUR`, `WEEKLY_MINUTE`.

## Logs

```
# Logs du runtime launchd (source de vérité)
~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_daily.log
~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_weekly.log
~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/pipeline.log
~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_daily.log
```

## Dépannage rapide

| Symptôme | Cause probable | Fix |
|----------|---------------|-----|
| Rien sur Slack | Run non déclenché | Vérifier `launchctl list \| grep driveco` + logs |
| Code changé mais run sur ancienne version | Runtime non resynchronisé | `bash sync_launchd_runtime.sh && bash setup_launchd.sh` |
| Notion : erreur 404 | Intégration "Kev1n Claude" déconnectée | Notion → page → `•••` → Connexions → reconnecter |
| Weekly non lancé lundi | Job weekly non chargé | `launchctl bootstrap gui/$(id -u) .../weekly.plist` |
| Ollama échoue | Modèle absent ou trop lent | Vérifier `ollama list`, `ollama pull gemma4:latest` |

## Structure du repo

```
analysis_pipeline.py    # Orchestrateur (modes: daily/weekly/reliability/test)
call_fetcher.py         # Récupération et enrichissement appels
call_classifier.py      # Classification métier (UCC / Driveco)
metrics_builder.py      # KPIs téléphoniques (answer rate, pics, churn…)
ollama_client.py        # Client Ollama (passe QA + VoC)
llm_client.py           # Client Anthropic (intégré, non opérationnel)
persistence.py          # Écriture Supabase (additif)
report_formatter.py     # Rendu Markdown + actionable_items dédupliqués
notifier.py             # Publication Slack (Block Kit, 1 post/run)
notion_reporter.py      # Publication Notion
gdrive_uploader.py      # Upload Google Drive (optionnel)
health_server.py        # Endpoint /health local
reliability.py          # Gold set scoring
voc_taxonomy.yaml       # Taxonomie VoC versionnée
system_prompt.txt       # Prompt QA agent
prompts/voc_system.txt  # Prompt VoC client (séparé)
config.py               # Chargement .env + constantes
csat_insight.py         # CSAT Call Insight — orchestration (launchd toutes les 3 min)
csat_parser.py          # Parsing posts Sprig → CsatPost
csat_prompting.py       # Prompt Gemma + verdict normalisé (≤ 55 mots)
csat_slack.py           # I/O Slack : historique canal CSAT, post thread, dédup
csat_state.py           # Persistance JSON de l'état CSAT (last_ts + pending)
setup_launchd.sh        # Installation runtime + plists launchd
sync_launchd_runtime.sh # Sync repo source → runtime launchd
run_from_cron.sh        # Wrapper de lancement (lock, log, état)
db/migrations/          # Migrations SQL Supabase
tests/                  # Tests unitaires (pytest)
```

## Sécurité

- Ne jamais committer `.env`, tokens OAuth ou exports QA
- Après exposition d'un `.env` à un tiers, régénérer tous les secrets
- Les IDs Notion / Slack / Cloudflare ne sont pas critiques mais éviter de les hardcoder
