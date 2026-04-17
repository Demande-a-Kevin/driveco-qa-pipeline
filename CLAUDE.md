# CLAUDE.md

This repository contains a local QA pipeline for Driveco customer calls.

## What this project does

- pulls call history from a Cloudflare worker backed by Aircall / D1
- classifies calls into UCC and Driveco scopes
- fetches Aircall AI transcripts for selected calls
- runs local QA analysis through Ollama
- runs a separate VoC extraction pass from the same transcripts
- generates Markdown reports and publishes to Slack / Notion / Google Drive when configured

## Read this first

1. `README.md`
2. `ARCHITECTURE.md`
3. `RUNBOOK.md`

## Key files

- `analysis_pipeline.py`: main orchestration
- `call_fetcher.py`: call retrieval, line mapping, transcript enrichment
- `call_classifier.py`: business classification rules
- `ollama_client.py`: local LLM calls
- `voc_taxonomy.yaml`: versioned VoC taxonomy
- `metrics_builder.py`: KPI computation
- `reliability.py`: gold set scoring and reliability metrics
- `report_formatter.py`: Markdown and Slack-ready rendering
- `notifier.py`: Slack publishing
- `health_server.py`: local `/health` endpoint for ops / dashboard
- `notion_reporter.py`: Notion publishing
- `gdrive_uploader.py`: Google Drive upload when credentials are present
- `setup_launchd.sh`: macOS automation setup
- `sync_launchd_runtime.sh`: sync source repo into launchd runtime

## Important operational fact

The source repo is not the directory executed by macOS automation.

- source repo: `/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline`
- launchd runtime: `~/Library/Application Support/driveco-qa-pipeline/runtime`

After editing code or `.env`, the runtime must be resynced:

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

## Current model and LLM behavior

- primary local model: `gemma4:latest`
- Anthropic integration exists in code but is currently not operational because of billing / credit issues
- local fallback behavior is important and should not be removed casually

## Known project constraints

- macOS blocks automation if code runs directly from protected folders like `Documents`
- `launchd` therefore runs from `~/Library/Application Support/...`
- Gemma 4 improves QA quality but can still be unstable on some batched outputs
- the pipeline should degrade gracefully when LLM steps fail

## How to validate changes

Connectivity test:

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
.venv/bin/python analysis_pipeline.py --mode test
```

Manual daily run from runtime:

```bash
cd "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python analysis_pipeline.py --mode daily --date 2026-04-10
```

Useful logs:

- `~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_daily.log`
- `~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/pipeline.log`

## Change rules for AI agents

- do not edit the launchd runtime directly unless the task is explicitly about runtime debugging
- edit the source repo, then resync the runtime
- do not remove fallback logic unless you have a tested replacement
- preserve reporting outputs for Slack and Markdown together
- preserve the separation between QA agent scoring and client VoC extraction
- be careful with line mappings and call scopes, especially UCC transfer handling
- keep `daily_kpi_snapshot.agent_id = ''` for global snapshots when `scope = 'global'`
- never commit secrets or local credential files

## External dependency

This repo depends on a separate Cloudflare worker repository for call ingestion:

- `driveco-aircall-worker`

The Python code expects worker endpoints through environment variables, not direct database access.
