# CLAUDE.md

Instructions for AI agents working on this repo. Read this before touching any file.

## What this project does

Local QA pipeline for Driveco customer-support calls, running on a Mac mini under macOS automation:

1. Pulls daily call history from a Cloudflare Worker backed by Aircall / D1
2. Classifies calls into two business scopes: **UCC** (outsourced line) and **Driveco** (internal care line)
3. Fetches Aircall AI transcripts for a sample of analysable calls (~75 %)
4. Runs QA scoring through a local Ollama model (Gemma 4)
5. Runs a separate VoC extraction pass on the same transcripts
6. Computes KPIs: inbounds, answer rate (answerable base), call peaks, churn risk, etc.
7. Publishes a **single Slack post** per daily run + Markdown file + Notion page + Obsidian note

## Read first

1. `README.md` — installation, env vars, commandes
2. `ARCHITECTURE.md` — flux de données, modules, conventions métier
3. `RUNBOOK.md` — exploitation, logs, incidents fréquents

## Key files

| File | Role |
|------|------|
| `analysis_pipeline.py` | Orchestrateur principal (modes: daily, weekly, reliability, test) |
| `call_fetcher.py` | Récupération appels, mapping lignes, enrichissement transcripts |
| `call_classifier.py` | Règles de classification métier (UCC / Driveco / transferts) |
| `ollama_client.py` | Appels LLM locaux (Gemma 4) |
| `metrics_builder.py` | Calcul KPIs : inbounds, answer rate, pics, churn, VoC |
| `report_formatter.py` | Rendu Markdown + registre `actionable_items` dédupliqué |
| `notifier.py` | Publication Slack (Block Kit, un seul post par run daily) |
| `notion_reporter.py` | Publication Notion (sous-page par run) |
| `persistence.py` | Écriture Supabase (additif — ne bloque pas si absent) |
| `voc_taxonomy.yaml` | Taxonomie VoC versionnée |
| `reliability.py` | Gold set scoring et métriques de fiabilité |
| `health_server.py` | Endpoint `/health` local pour ops/dashboard |
| `gdrive_uploader.py` | Upload Google Drive (optionnel, nécessite credentials OAuth) |
| `setup_launchd.sh` | Création du runtime launchd et des plists |
| `sync_launchd_runtime.sh` | Synchronisation repo source → runtime launchd |

## Séparation source repo / runtime launchd

**C'est le point le plus important à comprendre.**

- **Repo source** : `/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline`
  → Tu modifies le code ici.
- **Runtime launchd** : `~/Library/Application Support/driveco-qa-pipeline/runtime`
  → macOS exécute ce répertoire (pas le repo source directement).

Après toute modification de code ou de `.env`, resynchroniser le runtime :

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

Ne jamais éditer le runtime directement sauf debug explicite.

## Horaires launchd actuels

| Job | Déclenchement |
|-----|---------------|
| benchmark | Tous les jours à 01:30 |
| daily | Tous les jours à **02:30** |
| watchdog daily | Tous les jours à 06:45 |
| reliability | Lundi à 04:00 |
| weekly | Lundi à **07:15** |

> **Piège connu** : après un reboot macOS, le job `com.kev1n.driveco.qa.weekly` peut ne pas être rechargé alors que les 4 autres le sont. Vérifier avec `launchctl list | grep driveco` et recharger si besoin :
> ```bash
> launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kev1n.driveco.qa.weekly.plist
> ```

## Garde-fous opérationnels (lot sécurisation 2026-06-07)

Ajoutés après un incident où une modif CSAT/cockpit a écrasé le `.env` (perte
de `SUPABASE_*` / `NOTION_REPORTS_PAGE_ID`) et où un run Ollama a tenu le lock
16h, bloquant 2 jours de reporting **en silence**. But : qu'une modif faite
ailleurs ne puisse plus casser le daily sans qu'on le voie.

| Garde-fou | Fichier | Effet |
|-----------|---------|-------|
| **Preflight publish-config** | `ops_guards.py` + `.env.qa.required` | `run_daily` vérifie les clés requises AVANT tout calcul ; clé manquante = abort en secondes + alerte Slack. |
| **Manifeste des clés requises** | `.env.qa.required` | Liste versionnée des clés dont dépend le daily. Si tu ajoutes une dépendance de publication, ajoute-la ici. |
| **Garde anti-marathon** | `config.DAILY_MAX_WALL_SECONDS` (défaut 5400s/90min) | Budget temps sur l'analyse LLM du daily : au-delà, rapport dégradé publié + lock libéré, au lieu de tenir le lock des heures. |
| **Watchdog qui alerte vraiment** | `run_daily_watchdog.sh` | Alertes Slack via le **venv** (plus via `python3` système qui n'a pas `requests`/`dotenv` → muet). Escalade : lock tenu + run bloqué = kill + relance + alerte critique. |
| **Détecteur de dérive** | `check_runtime_drift.sh` | Compare source ↔ runtime et alerte si divergence. Lancé par le watchdog. |
| **Gate test+deploy** | `deploy.sh` | Lance `pytest` et ne synchronise le runtime QUE si vert. |

**Règle d'or** : ne JAMAIS éditer le `.env` partagé pour CSAT/cockpit sans
vérifier que les clés de `.env.qa.required` restent présentes. Idéalement, les
jobs CSAT/cockpit utilisent leurs propres variables et ne touchent pas aux clés
QA.

## Modèle LLM et comportement

- **Modèle local principal** : `gemma4:latest` via Ollama
- **Anthropic** : intégré dans le code mais non opérationnel actuellement (problème billing). **Ne pas supprimer le fallback local.**
- Le pipeline doit toujours produire une sortie exploitable, même si Ollama échoue partiellement.

## Source KB (base de connaissances)

Depuis lot 13, le pipeline utilise le vault **Obsidian local** comme source KB principale :

- `OBSIDIAN_VAULT_DIR=/Users/kev1n/Documents/Obsidian`
- `OBSIDIAN_KB_SUBDIR=10 - Pro/Driveco QA/KB`
- `OBSIDIAN_REPORTS_SUBDIR=10 - Pro/Driveco QA`
- `OBSIDIAN_KB_ENABLED=true`

Le miroir Notion vers Obsidian est maintenu par le pipeline lui-même. Si `OBSIDIAN_KB_ENABLED=false`, le pipeline se rabat sur la source Notion.

> **Vigilance répertoires** : `REPORT_OUTPUT_DIR` (rapports, flags, cache, logs)
> est lu par le `.env` actif. Il a été repointé vers
> `/Users/kev1n/Documents/Claude/workspace/driveco/qa/qa-driveco-data` lors de
> modifs CSAT/cockpit, alors que d'anciens rapports vivent encore dans
> `runtime/qa-driveco-data`. Le watchdog ET le notifier lisent tous deux
> `REPORT_OUTPUT_DIR` (cohérents entre eux), mais garde en tête que l'état est
> éparpillé sur 2 racines : pour retrouver un rapport, vérifie d'abord
> `config.REPORT_OUTPUT_DIR`.

## Architecture Slack (depuis lot 14)

**Un seul post Slack par run daily.** Plus de doubles posts.

Le post contient dans l'ordre :
1. Header date + résumé run
2. KPIs globaux (Inbounds, Answer rate sur base answerable, Durée moy, Abandon, Escalades)
3. Ligne Assistance Driveco (Inbounds, Answer rate, Durée moy, Transférés UCC IVR)
4. Ligne Driveco UCC transfert (Inbounds, Answer rate, Durée moy)
5. Éligibles QA / Analysés / Transcripts
6. Routage IVR
7. Pics d'appels (top 3 fenêtres)
8. Raisons d'appel (catégories + sous-motifs actionnables)
9. Opportunités / bonnes pratiques / concurrents si détectés
10. Alertes (appels problématiques avec liens Aircall)
11. Clients frustrés / repeat callers (ligne Assistance uniquement)

**Answer rate** = appels répondus / appels "answerables" (exclut call deflector `ivr_branch key_3 / "deflect"` + abandons pré-sonnerie : `abandoned_in_ivr`, `short_abandoned`, `out_of_opening_hours`).

## Notion : point de vigilance

L'intégration Notion **"Kev1n Claude"** doit rester connectée à la page parent des rapports (`NOTION_REPORTS_PAGE_ID`). Si elle perd l'accès, les pages quotidiennes ne sont plus créées (erreur 404). Vérifier dans Notion → page → `•••` → Connexions.

## Variables `.env` clés

```
# Source appels
CF_WORKER_URL
CF_WORKER_AUTH

# Aircall
AIRCALL_API_ID
AIRCALL_API_TOKEN

# LLM local
OLLAMA_BASE_URL        # défaut: http://localhost:11434
OLLAMA_FIXED_MODEL     # ex: gemma4:latest

# Persistance analytique (optionnel)
SUPABASE_URL
SUPABASE_SERVICE_KEY

# Notion
NOTION_API_KEY
NOTION_KB_PAGE_ID
NOTION_REPORTS_PAGE_ID

# KB Obsidian (prioritaire sur Notion si ENABLED=true)
OBSIDIAN_VAULT_DIR
OBSIDIAN_KB_SUBDIR
OBSIDIAN_KB_ENABLED    # true / false

# Slack
SLACK_BOT_TOKEN
SLACK_CHANNEL_ID

# Google Drive (optionnel)
GDRIVE_CREDENTIALS_FILE
GDRIVE_TOKEN_FILE
GDRIVE_FOLDER_ID
```

## Règles pour agents IA

### Ne pas casser
- Le fallback local Ollama — toujours présent même si Anthropic est activé
- La séparation QA agent / VoC client (deux passes LLM distinctes)
- Le principe `actionable_items` : déduplication avant rendu Slack / Markdown
- `daily_kpi_snapshot.agent_id = ''` pour les snapshots globaux (`scope = 'global'`)
- `RUN_DEGRADED_THRESHOLD` configurable — marquer les runs vides/sous-rétention comme `degraded`
- Le **preflight** `ops_guards.run_preflight_or_abort` en tête de `run_daily` — ne pas le contourner
- Le **manifeste** `.env.qa.required` — le tenir à jour quand une dépendance de publication change
- La **garde anti-marathon** `DAILY_MAX_WALL_SECONDS` — ne pas la mettre à 0 en prod
- Le **watchdog** doit alerter via `$PYTHON_BIN` (venv), jamais `python3` nu
- `caller_hash` pour la cohérence analytique — ne pas exposer les numéros bruts
- `resolution_status` et VoC `product_area` additifs — ne pas les mélanger dans la rubric QA

### Workflow obligatoire après chaque modif
1. Modifier le **repo source**
2. **`bash deploy.sh`** — lance `pytest` (146 tests) et ne synchronise le runtime
   QUE si tout est vert. Remplace l'appel manuel à `sync_launchd_runtime.sh` +
   `setup_launchd.sh` (qui restent utilisables pour un sync forcé sans tests).

> Ne jamais pousser vers le runtime sans tests verts : c'est ce qui a laissé du
> code non testé atteindre la prod. `deploy.sh` est le garde-fou.

### Ne jamais committer
- `.env`, tokens OAuth, exports QA locaux, fichiers credentials Google Drive
- Données de production dans `qa-driveco-data/`

## Dépendance externe

Ce repo dépend du worker Cloudflare `driveco-aircall-worker` pour l'ingestion des appels. Le code Python accède uniquement aux endpoints du worker via `CF_WORKER_URL` / `CF_WORKER_AUTH` — jamais directement à D1.
