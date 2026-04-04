# driveco-qa-pipeline

Pipeline Python d'analyse qualité d'appels Driveco.

Le pipeline :
- récupère les appels via un worker Cloudflare / D1
- classe les appels UCC
- enrichit un échantillon avec transcripts Aircall
- analyse via Ollama local puis Anthropic
- génère un rapport Markdown
- publie vers Slack, Notion et Google Drive si configurés

## Structure

- `analysis_pipeline.py` : orchestrateur principal
- `config.py` : chargement du `.env` et constantes
- `call_fetcher.py` / `d1_client.py` : récupération des appels
- `llm_client.py` / `ollama_client.py` : appels LLM
- `notifier.py` / `notion_reporter.py` / `gdrive_uploader.py` : sorties
- `setup.sh` : installation initiale
- `setup_cron.sh` : configuration cron
- `setup_launchd.sh` : configuration `launchd` macOS

## Prérequis

- macOS ou Linux
- Python 3.11+
- accès aux APIs Aircall, Anthropic, Notion, Slack
- accès au worker Cloudflare utilisé par le pipeline
- Ollama local facultatif

## Installation

```bash
cd /chemin/vers/driveco-qa-pipeline
bash setup.sh
```

Le script :
- crée `.venv`
- installe `requirements.txt`
- copie `.env.example` vers `.env` si absent
- prépare `qa-driveco-data/`
- lance un test de connectivité
- ajoute les crons

## Configuration `.env`

Crée le fichier :

```bash
cp .env.example .env
```

Variables indispensables pour un run complet :
- `CF_WORKER_URL`
- `CF_WORKER_AUTH`
- `AIRCALL_API_ID`
- `AIRCALL_API_TOKEN`
- `ANTHROPIC_API_KEY`
- `NOTION_API_KEY`
- `NOTION_KB_PAGE_ID`
- `NOTION_REPORTS_PAGE_ID`
- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`

Variables optionnelles :
- `GDRIVE_*`
- `OLLAMA_*`
- `REPORT_OUTPUT_DIR`
- `LOG_DIR`
- `NOTION_CACHE_PATH`

Note :
- `CF_ACCOUNT_ID` et `CF_D1_DATABASE_ID` sont documentés mais non utilisés par le code Python actuel.
- `CF_API_TOKEN` est conservé pour compatibilité documentaire. Le flux Python s'appuie aujourd'hui sur `CF_WORKER_AUTH`.

## Commandes utiles

Test de connectivité :

```bash
.venv/bin/python analysis_pipeline.py --mode test
```

Run quotidien manuel :

```bash
.venv/bin/python analysis_pipeline.py --mode daily --date 2026-03-31
```

Run hebdomadaire manuel :

```bash
.venv/bin/python analysis_pipeline.py --mode weekly --date 2026-03-31
```

Script de test rapide :

```bash
bash run_daily_test.sh
```

## Planification macOS

Sur macOS, utiliser `launchd` de préférence.
Le `cron` système peut être bloqué par les protections macOS quand le projet vit dans `Documents`.

Installation recommandée :

```bash
bash setup_launchd.sh
```

Par défaut avec `launchd` :
- tous les jours à `01:30` : benchmark Ollama sur vrais transcripts
- tous les jours à `06:40` : run `daily`
- tous les jours à `07:20` : watchdog `daily`
- chaque lundi à `07:15` : run `weekly`

Horaires surchargables :
- `BENCH_HOUR`
- `BENCH_MINUTE`
- `DAILY_HOUR`
- `DAILY_MINUTE`
- `WATCHDOG_HOUR`
- `WATCHDOG_MINUTE`
- `WEEKLY_HOUR`
- `WEEKLY_MINUTE`

Exemple :

```bash
BENCH_HOUR=1 BENCH_MINUTE=30 DAILY_HOUR=6 DAILY_MINUTE=40 bash setup_launchd.sh
```

## Cron installé

Conservé pour compatibilité, mais non recommandé sur macOS quand le repo est dans `Documents`.

Par défaut :
- tous les jours à `01:30` : benchmark Ollama sur vrais transcripts
- tous les jours à `06:40` : démarrage du run `daily` pour viser une publication vers `07:00`
- tous les jours à `07:20` : watchdog `daily` si aucun rapport n'a été produit
- chaque lundi à `07:15` : run `weekly`

Horaires surchargables à l'installation :
- `BENCH_CRON_HOUR`
- `BENCH_CRON_MINUTE`
- `DAILY_CRON_HOUR`
- `DAILY_CRON_MINUTE`
- `WATCHDOG_CRON_HOUR`
- `WATCHDOG_CRON_MINUTE`
- `WEEKLY_CRON_HOUR`
- `WEEKLY_CRON_MINUTE`

Exemple :

```bash
BENCH_CRON_HOUR=1 BENCH_CRON_MINUTE=30 DAILY_CRON_HOUR=6 DAILY_CRON_MINUTE=40 bash setup_cron.sh
```

Logs :
- `qa-driveco-data/logs/cron_benchmark.log`
- `qa-driveco-data/logs/cron_daily.log`
- `qa-driveco-data/logs/cron_weekly.log`
- `qa-driveco-data/logs/pipeline.log`

Résultat benchmark au réveil :
- `qa-driveco-data/bench_ollama_latest_summary.md` : résumé lisible le plus récent
- `qa-driveco-data/bench_ollama_models_...json` : résultat brut complet
- si Google Drive est configuré, le résumé benchmark est aussi uploadé dans le sous-dossier `Benchmarks Ollama`

## Dépannage

Si `--mode test` échoue :
- vérifie `.env`
- vérifie que `.venv` existe et que les deps sont installées
- vérifie que le worker Cloudflare répond
- vérifie que les pages Notion sont bien partagées avec l'intégration
- vérifie que le bot Slack a accès au channel

Si Ollama ne répond pas :
- le pipeline doit continuer avec fallback
- vérifie `OLLAMA_BASE_URL`
- vérifie que le modèle indiqué est bien chargé

Si Google Drive ne marche pas :
- vérifie les fichiers OAuth pointés par `GDRIVE_CREDENTIALS_FILE` et `GDRIVE_TOKEN_FILE`

## Sécurité

- ne jamais committer `.env`, tokens OAuth ou exports QA
- après exposition d'un `.env` à un agent ou à un tiers, considère les secrets comme compromis et régénère-les
- les IDs internes Notion / Slack / Cloudflare ne sont pas des secrets critiques, mais on évite de les hardcoder

## Codex / VS Code

Pour travailler proprement :

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pre-commit install
```

Extensions VS Code recommandées : voir `.vscode/extensions.json`.
