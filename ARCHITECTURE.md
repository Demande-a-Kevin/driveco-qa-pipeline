# Architecture

## Objectif

`driveco-qa-pipeline` est une pipeline locale de QA d'appels Driveco.

Elle sert à :
- récupérer les appels depuis un worker Cloudflare connecté à Aircall / D1
- normaliser et classifier les appels
- récupérer les transcripts Aircall AI pour un sous-ensemble d'appels
- analyser la qualité des appels avec Ollama local
- produire un rapport Markdown, Slack et Notion

## Vue d'ensemble

```text
Aircall
  -> Worker Cloudflare
  -> D1 / endpoints export
  -> call_fetcher.py / d1_client.py
  -> classification + métriques
  -> enrichissement transcripts Aircall AI
  -> analysis_pipeline.py
  -> Ollama local (Gemma 4)
  -> consolidation fallback local
  -> report_formatter.py / notifier.py / notion_reporter.py
  -> Markdown local + Slack + Notion
```

## Briques principales

### 1. Source appels

- [worker Cloudflare externe](https://github.com/Demande-a-Kevin/driveco-aircall-worker) : collecte les appels Aircall et les expose
- [d1_client.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/d1_client.py) : client HTTP vers le worker
- [call_fetcher.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/call_fetcher.py) : récupération des appels par date, mapping des lignes, enrichissement transcript

Le code Python ne parle pas directement à D1. Il passe par les endpoints du worker via :
- `CF_WORKER_URL`
- `CF_WORKER_AUTH`

### 2. Classification métier

- [call_classifier.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/call_classifier.py)

Types importants :
- `ucc_handled` : appel traité par l'UCC sur la ligne assistance
- `warm_transfer` : transfert initié depuis l'UCC
- `ucc_transfer_handled` : appel pris par Driveco après transfert
- `b2b_direct` / `driveco_direct` : appels reçus directement côté Driveco

Scopes QA :
- `UCC` : `ucc_handled` + `warm_transfer`
- `Driveco Care` : `ucc_transfer_handled` + `b2b_direct` + `driveco_direct`
- `QA global` : union des deux, sans doublons

### 3. Transcripts

- source transcript retenue : `GET /v1/calls/{id}/transcription`
- parsing Aircall AI : `transcription.content.utterances`
- nettoyage / diarisation : dans [call_fetcher.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/call_fetcher.py)

Le transcript enrichi est utilisé pour :
- la raison d'appel
- les soft skills
- l'évaluation procédure / KB

Le champ `Call Timeline` est conservé comme trace, mais ce n'est pas la source transcript principale.

### 4. Orchestration

- [analysis_pipeline.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/analysis_pipeline.py)

Modes :
- `daily`
- `weekly`
- `test`
- `benchmark` via [run_from_cron.sh](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/run_from_cron.sh)

Étapes du `daily` :
1. récupération des appels du jour
2. classification métier
3. calcul des KPIs globaux
4. sélection de `75%` des appels analysables
5. enrichissement transcript
6. pre-screening Ollama
7. analyse batchée Ollama
8. consolidation locale
9. génération des sorties

### 5. LLM

- [ollama_client.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/ollama_client.py)
- [llm_client.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/llm_client.py)
- [system_prompt.txt](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/system_prompt.txt)

État actuel :
- modèle local principal : `gemma4:latest`
- pre-screening : Ollama local
- analyse : Ollama local
- Anthropic : présent dans le code, mais actuellement désactivé en pratique par manque de crédit

Important :
- le fallback local reste critique
- si Ollama ne répond pas correctement, le pipeline doit continuer avec une sortie dégradée mais exploitable

### 6. Reporting

- [metrics_builder.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/metrics_builder.py)
- [report_formatter.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/report_formatter.py)
- [notifier.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/notifier.py)
- [notion_reporter.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/notion_reporter.py)
- [gdrive_uploader.py](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/gdrive_uploader.py)

Sorties possibles :
- Markdown local dans `qa-driveco-data/`
- Slack
- Notion
- Google Drive si les credentials existent

## Runtime local vs repo source

Il y a deux emplacements importants.

### Repo source

Chemin de travail :
- [repo source](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline)

Tu modifies le code ici.

### Runtime launchd

Chemin exécuté par l'automatisation :
- [runtime launchd](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime)

`launchd` exécute le runtime, pas directement le repo.

Conséquence :
- après une modif de code ou de `.env`, il faut resynchroniser le runtime

Commande :

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

## Automatisation

Scripts principaux :
- [setup_launchd.sh](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/setup_launchd.sh)
- [sync_launchd_runtime.sh](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/sync_launchd_runtime.sh)
- [run_from_cron.sh](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/run_from_cron.sh)
- [run_daily_watchdog.sh](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/run_daily_watchdog.sh)

Jobs `launchd` :
- benchmark : `01:30`
- daily : `05:15`
- watchdog daily : `06:45`
- weekly : lundi `07:15`

## Données locales

Répertoires importants :
- [qa-driveco-data](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/qa-driveco-data)
- [runtime data](/Users/kev1n/Library/Application%20Support/driveco-qa-pipeline/runtime/qa-driveco-data)

Contenu typique :
- `logs/`
- `state/`
- `cache/`
- rapports quotidiens / hebdo

Le repo n'est pas censé contenir les données runtime lourdes ou les archives locales de production.

## Limites connues

- `Gemma 4` améliore la finesse QA mais reste encore instable sur certains batches
- le pre-screening Gemma 4 a été adapté, mais le modèle n'est pas encore parfaitement prévisible
- Anthropic n'est pas opérationnel tant que le sujet billing n'est pas réglé
- Google Drive ne publiera rien sans les fichiers OAuth locaux

## Lecture recommandée

Pour quelqu'un qui découvre le projet :
1. lire [README.md](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/README.md)
2. lire ce document
3. lire [RUNBOOK.md](/Users/kev1n/Desktop/Kev1n%20IA/Codex/driveco-qa-pipeline/RUNBOOK.md)
