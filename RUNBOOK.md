# Runbook

## But

Ce document sert à exploiter `driveco-qa-pipeline` sans devoir relire tout le code.

Il couvre :
- les commandes utiles
- les checks du matin
- les logs
- les incidents fréquents

## Commandes de base

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

## Fichiers de log utiles

Runtime `launchd` :
- [launchd_daily.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_daily.log)
- [launchd_daily_watchdog.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_daily_watchdog.log)
- [launchd_weekly.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_weekly.log)
- [launchd_benchmark.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_benchmark.log)

Logs pipeline :
- [cron_daily.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_daily.log)
- [cron_weekly.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_weekly.log)
- [cron_benchmark.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_benchmark.log)
- [pipeline.log](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/pipeline.log)

État :
- [daily_status.env](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data/state/daily_status.env)
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
