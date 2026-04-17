# Runbook

## But

Ce document sert à exploiter `driveco-qa-pipeline` sans devoir relire tout le code.

Il couvre :
- les commandes utiles
- les checks du matin
- les logs
- les incidents fréquents

## Commandes de base

### Validation Lot 1

Vérifier la rubric et les schémas stricts :

```bash
python3 -m unittest tests.test_schemas
```

Source de vérité du scoring QA :
- `rubric.yaml`
- `schemas.py`
- `prompts/examples/qa_*.json`

### Validation Lot 2

Connectivité légère avec persistance analytique :

```bash
.venv/bin/python analysis_pipeline.py --mode test
python3 -m unittest tests.test_persistence
```

Migration SQL à appliquer côté Supabase :
- `db/migrations/001_init.sql`

### Validation Lot 6

VoC séparée de la QA agent :

```bash
.venv/bin/python -m unittest tests.test_voc
```

Fichiers de référence :
- `voc_taxonomy.yaml`
- `prompts/voc_system.txt`
- `db/migrations/003_voc.sql`

### Validation Lots 3 à 5

```bash
.venv/bin/python -m unittest tests.test_metrics_builder tests.test_reliability
.venv/bin/python analysis_pipeline.py --mode test
```

Migrations SQL à appliquer :
- `db/migrations/004_metrics_agent.sql`
- `db/migrations/005_reliability.sql`
- `db/migrations/002_views.sql`

### Test de connectivité

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
.venv/bin/python analysis_pipeline.py --mode test
```

### Run quotidien manuel

```bash
cd "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python analysis_pipeline.py --mode daily --date 2026-04-10
```

### Run hebdomadaire manuel

```bash
cd "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python analysis_pipeline.py --mode weekly --date 2026-04-13
```

### Resynchroniser le runtime après modif

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

## Routine du matin

### 1. Vérifier que `launchd` a bien déclenché les jobs

```bash
launchctl list | rg 'com\\.kev1n\\.driveco\\.qa'
```

### 2. Vérifier le log du daily

```bash
tail -n 100 "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_daily.log"
```

### 3. Vérifier l'état du run

```bash
cat "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/state/daily_status.env"
```

### 4. Vérifier que Slack a bien été envoyé

Indices dans le log :
- `Slack envoyé`
- `Analyse quotidienne terminée`
- `Supabase désactivé` ou warnings `[persistence]` si la persistance analytique n'est pas branchée

## Fichiers de log utiles

Runtime `launchd` :
- [launchd_daily.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_daily.log)
- [launchd_daily_watchdog.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_daily_watchdog.log)
- [launchd_reliability.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_reliability.log)
- [launchd_weekly.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_weekly.log)
- [launchd_benchmark.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_benchmark.log)

Logs pipeline :
- [cron_daily.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_daily.log)
- [cron_reliability.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_reliability.log)
- [cron_weekly.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_weekly.log)
- [cron_benchmark.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_benchmark.log)
- [pipeline.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/pipeline.log)

État :
- [daily_status.env](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/state/daily_status.env)
- [reliability_status.env](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/state/reliability_status.env)
- [weekly_status.env](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/state/weekly_status.env)
- [benchmark_status.env](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/state/benchmark_status.env)

## Interpréter un run daily

Étapes normales attendues dans `cron_daily.log` :
1. `ANALYSE QUOTIDIENNE`
2. nombre d'appels récupérés
3. `Appels QA scope`
4. `Sélection analyse`
5. `Pre-screening ... via Ollama`
6. `Analyse ... appels risque faible`
7. `Top 5 appels problématiques identifiés`
8. `Analyse quotidienne terminée`
9. `Slack envoyé`
10. `Voix du client` dans le rapport si des transcripts exploitables existent

## Incidents fréquents

### 1. Rien n'est posté sur Slack

Check :
- `launchd_daily.log`
- `cron_daily.log`
- flag `.slack_sent_daily_YYYY-MM-DD.flag`

Causes fréquentes :
- run non lancé
- run trop lent
- runtime non resynchronisé
- plantage Ollama
- erreur Slack

### 2. Le code a changé mais l'automatisation tourne encore sur l'ancienne version

Cause :
- le runtime `launchd` n'a pas été resynchronisé

Fix :

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

### 3. Le repo est déplacé et l'automatisation casse

Cause probable :
- chemins absolus cassés
- scripts lancés depuis l'ancien emplacement

Fix :
- vérifier le repo source
- resynchroniser le runtime
- recharger `launchd`

### 4. Pre-screening ou analyse Ollama tombent en fallback

Regarder dans les logs :
- `Réponse non-JSON`
- `fallback heuristique`
- `Ollama échoué`

Explication :
- modèle trop lent
- réponse tronquée
- JSON invalide

Fix de premier niveau :
- vérifier qu'Ollama répond
- vérifier le modèle chargé
- réduire la taille des batches si besoin
- resynchroniser le runtime après changement config

### 5. La validation stricte JSON casse l'analyse QA

Symptômes typiques :
- `validation Ollama échouée`
- `réponse vide`
- JSON conforme au markdown mais pas au schéma attendu

Checks :
- lancer `python3 -m unittest tests.test_schemas`
- vérifier `rubric.yaml`
- vérifier les few-shots dans `prompts/examples/`
- relire le warning exact dans `pipeline.log`

Fix de premier niveau :
- corriger le schéma attendu plutôt que réintroduire du nettoyage regex
- vérifier que chaque point d'amélioration a une citation réellement présente dans le transcript
- réduire le transcript envoyé si la sortie Ollama devient instable

### 5. Anthropic échoue

Symptôme typique :
- `400 Bad Request`
- message de crédit insuffisant

État attendu actuel :
- pas bloquant
- le fallback local doit prendre le relais

### 6. Google Drive ne publie rien

Cause probable :
- `gdrive_credentials.json` absent
- `gdrive_token.json` absent

Le pipeline peut finir sans Google Drive.

### 7. Supabase n'écrit rien

Checks :
- `SUPABASE_URL` et `SUPABASE_SERVICE_KEY` définis dans `.env`
- migration `db/migrations/001_init.sql` bien appliquée
- migration `db/migrations/003_voc.sql` bien appliquée si la VoC est activée
- `python analysis_pipeline.py --mode test`
- recherche de warnings `[persistence]` dans `pipeline.log`

Comportement attendu actuel :
- non bloquant
- D1 / Markdown / Slack / Notion continuent même si Supabase est absent

### 8. La VoC n'apparaît pas dans le rapport

Checks :
- `ENABLE_VOC_ANALYSIS=true`
- transcript réellement présent sur les appels analysés
- `python -m unittest tests.test_voc`
- présence de `voc_extract` dans `call_evaluations`

Causes fréquentes :
- citations non retrouvées dans le transcript
- taxonomie invalide
- migration `003_voc.sql` absente

Fix de premier niveau :
- relancer le test VoC
- vérifier `voc_taxonomy.yaml`
- vérifier que les quotes renvoyées par le modèle sont bien présentes dans le transcript
- appliquer la migration `003_voc.sql`

### 9. Le mode reliability paraît bloqué

Cause fréquente :
- refresh Notion KB trop long
- Ollama lent sur plusieurs appels gold set

Checks :
- `tail -n 100 qa-driveco-data/logs/cron_reliability.log`
- cache Notion présent dans `qa-driveco-data/cache/notion_kb_cache.json`
- `python analysis_pipeline.py --mode reliability --date 2026-04-14`

Note :
- le mode reliability utilise d'abord le cache KB local pour éviter un refresh complet Notion

## Commandes de diagnostic utiles

### Vérifier les jobs `launchd`

```bash
plutil -p ~/Library/LaunchAgents/com.kev1n.driveco.qa.daily.plist
plutil -p ~/Library/LaunchAgents/com.kev1n.driveco.qa.daily-watchdog.plist
```

### Vérifier le modèle Ollama chargé

```bash
ollama list
ollama show gemma4:latest
```

### Vérifier un process daily en cours

```bash
pgrep -af 'analysis_pipeline.py --mode daily'
```

### Arrêter un run bloqué

```bash
pkill -f 'analysis_pipeline.py --mode daily'
```

## Publication d'une republication daily

Pour republier un jour déjà envoyé sur Slack :
1. archiver le rapport local si besoin
2. supprimer le flag `.slack_sent_daily_YYYY-MM-DD.flag`
3. relancer le `daily --date YYYY-MM-DD`

Exemple :

```bash
rm -f "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/.slack_sent_daily_2026-04-10.flag"
cd "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python analysis_pipeline.py --mode daily --date 2026-04-10
```

## Ce qu'il faut éviter

- ne pas modifier directement le runtime à la main
- ne pas supposer que le repo source est ce qu'exécute `launchd`
- ne pas relancer plusieurs `daily` concurrents sur la même date
- ne pas ignorer les flags `.slack_sent_*`

## En cas de partage du projet

Le minimum à transmettre avec le repo :
- [README.md](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/README.md)
- [ARCHITECTURE.md](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/ARCHITECTURE.md)
- ce document
