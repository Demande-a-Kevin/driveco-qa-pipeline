# Architecture

## Objectif

`driveco-qa-pipeline` est un pipeline local d'analyse qualité des appels Driveco.  
Il tourne en autonomie sur un Mac mini sous macOS (`launchd`).

Ce qu'il fait :
- Récupère les appels depuis un worker Cloudflare connecté à Aircall / D1
- Normalise et classe les appels en deux scopes métier (UCC / Driveco)
- Récupère les transcripts Aircall AI pour un échantillon (~75 %)
- Analyse la qualité agent avec Ollama local (Gemma 4)
- Extrait séparément la voix du client (VoC)
- Calcule des KPIs téléphoniques (inbounds, answer rate, pics, churn…)
- Publie un rapport unique : Slack + Markdown + Notion + Obsidian

---

## Flux de données

```
Aircall (appels entrants/sortants)
  └─► Worker Cloudflare (driveco-aircall-worker)
        └─► call_fetcher.py  ─── récupération par date, mapping lignes
              └─► call_classifier.py  ─── classification métier
                    ├─► metrics_builder.py  ─── KPIs téléphoniques
                    └─► [sélection 75% analysables]
                          └─► Aircall API /v1/calls/{id}/transcription
                                └─► ollama_client.py (Gemma 4)
                                      ├─► passe QA (scoring agent)
                                      └─► passe VoC (topics, churn, verbatims)
                                            └─► persistence.py  ─► Supabase (additif)
                                                  └─► report_formatter.py
                                                        ├─► notifier.py  ─► Slack (1 post)
                                                        ├─► notion_reporter.py  ─► Notion
                                                        ├─► Markdown local (qa-driveco-data/)
                                                        └─► Obsidian vault
```

---

## Briques principales

### 1. Source appels

**Worker Cloudflare** (`driveco-aircall-worker`) : reçoit les webhooks Aircall et expose des endpoints de consultation.

- `d1_client.py` — client HTTP vers le worker
- `call_fetcher.py` — récupération par date, mapping lignes, enrichissement transcripts

> Le code Python ne parle **jamais directement** à D1. Tout passe par `CF_WORKER_URL` + `CF_WORKER_AUTH`.

### 2. Classification métier

`call_classifier.py` identifie le type de chaque appel :

| Type | Description |
|------|-------------|
| `ucc_handled` | Appel traité par l'UCC sur la ligne Assistance |
| `warm_transfer` | Transfert chaud initié par l'UCC |
| `ucc_transfer_handled` | Appel pris par Driveco après transfert UCC |
| `b2b_direct` | Appel entrant direct côté Driveco B2B |
| `driveco_direct` | Appel entrant direct Driveco standard |

**Scopes QA** :
- `UCC` = `ucc_handled` + `warm_transfer`
- `Driveco Care` = `ucc_transfer_handled` + `b2b_direct` + `driveco_direct`
- `global` = union sans doublons

**Deux lignes physiques distinctes** (IDs de numéro Aircall différents) :
- **Ligne Assistance Driveco** — appels UCC + transferts entrants
- **Ligne Driveco UCC transfert** — appels UCC transférés vers Driveco Care

### 3. KPIs téléphoniques (`metrics_builder.py`)

Calculs non-triviaux à connaître :

**Answer rate** ≠ `answered / total_calls`.  
La base est restreinte aux appels "answerables", en excluant :
- Call deflector (`ivr_branch key_3 / "deflect"`)
- Abandons pré-sonnerie : `abandoned_in_ivr`, `short_abandoned`, `out_of_opening_hours`

```
answer_rate = answered / (total - deflected - ivr_pre_ring_abandons)
```

**Abandon rate** : basé sur `total_calls` (tous inbounds), différent de la base answer rate.

**Pics d'appels** : fenêtres horaires top 3, avec call_ids représentatifs pour liens Aircall.

**Churn risk** : agrégé en typologie `{élevé: N, modéré: N, total: N}`.

### 4. Transcripts

Source : `GET /v1/calls/{id}/transcription` (Aircall AI)  
Format : `transcription.content.utterances` (diarisation speaker/agent)

Le transcript enrichi alimente deux passes LLM distinctes et indépendantes :
- **Passe QA** : scoring rubric, soft skills, procédures, KB compliance
- **Passe VoC** : topics, verbatims client, churn risk, perception produit, besoins non couverts

### 5. Base de connaissances (KB)

Source primaire depuis lot 13 : **vault Obsidian local**

```
OBSIDIAN_VAULT_DIR  = /Users/kev1n/Documents/Obsidian/Kev1n
OBSIDIAN_KB_SUBDIR  = Driveco QA/KB
OBSIDIAN_KB_ENABLED = true
```

Le pipeline lit les `.md` du sous-dossier à chaque run (YAML frontmatter + body).  
Fallback sur Notion si `OBSIDIAN_KB_ENABLED=false`.

Le miroir Notion → Obsidian est maintenu par le pipeline lui-même (synced à chaque run).

### 6. LLM

- `ollama_client.py` — Ollama local (Gemma 4, batch de 3 appels, 2 workers parallèles)
- `llm_client.py` — abstraction Anthropic (intégré, non opérationnel actuellement)
- `system_prompt.txt` — prompt système QA
- `prompts/voc_system.txt` — prompt VoC séparé

> Le fallback local est critique. Si Ollama échoue, le pipeline continue avec une sortie dégradée (`run_degraded=true`) mais reste exploitable.

### 7. Orchestration (`analysis_pipeline.py`)

Modes disponibles :

| Mode | Description |
|------|-------------|
| `daily` | Run principal — appels J-1 |
| `weekly` | Agrégation hebdomadaire — 0 pass LLM, réutilise les évaluations des dailies |
| `reliability` | Gold set scoring — benchmark de qualité sur un set de contrôle |
| `test` | Test de connectivité léger |

**Étapes du `daily`** :
1. Récupération appels J-1
2. Classification métier
3. Persistance calls/agents Supabase (additif)
4. Calcul KPIs globaux + par ligne
5. Sélection ~75 % des appels analysables
6. Enrichissement transcripts
7. Persistance transcripts Supabase
8. Pre-screening Ollama (scoring rapide)
9. Analyse QA batchée Ollama (extraction → scoring)
10. Passe VoC Ollama (séparée)
11. Persistance évaluations / snapshots / llm_runs Supabase
12. Purge rétention verbatims VoC
13. Consolidation locale
14. Génération des sorties (Slack, Notion, Markdown, Obsidian)

**Étapes du `weekly`** (lot 12) :
- Récupère les appels de la semaine (Lun→Dim)
- **Réutilise les évaluations déjà persistées** des dailies correspondants (0 pass LLM)
- Pure agrégation : moyennes, tendances, top problèmes de la semaine
- Abandonne si le daily du dimanche est absent (garde-fou lot 11)

### 8. Reporting

**Slack** (`notifier.py`) : **un seul post par run daily** (règle absolue depuis lot 14).

Contenu du post :
1. Header + date + résumé run
2. KPIs globaux (Inbounds / Answer rate / Durée / Abandon / Escalades)
3. Bloc Ligne Assistance Driveco
4. Bloc Ligne Driveco UCC transfert
5. Éligibles QA / Analysés / Transcripts
6. Routage IVR (répartition touches)
7. Pics d'appels (top 3 fenêtres horaires)
8. Voix du client (top topics, labels humains, max 6)
9. Risque client (élevé N / modéré N)
10. Alertes (appels problématiques avec liens Aircall directs)
11. Clients frustrés / repeat callers (scope Assistance uniquement)

**Markdown** : fichier local `qa-driveco-data/YYYY-MM-DD_daily_report.md`

**Notion** (`notion_reporter.py`) : sous-page quotidienne sous `NOTION_REPORTS_PAGE_ID`

**Obsidian** : note daily dans `Driveco QA/Daily/`

**Google Drive** (`gdrive_uploader.py`) : optionnel, nécessite credentials OAuth locaux

### 9. Persistance analytique (`persistence.py`)

Supabase (PostgreSQL) — totalement additif, le pipeline fonctionne sans.

Tables principales :
- `calls`, `agents` — données Aircall normalisées
- `transcripts` — transcripts enrichis
- `evaluations` — résultats QA par appel
- `soft_skills`, `issues` — détail rubric
- `daily_kpi_snapshot` — snapshot KPIs par date / scope / agent
- `llm_runs` — traçabilité des appels LLM

Tables VoC :
- `voc_extracts`, `topic_mentions`, `verbatims`
- `entity_perceptions`, `competitor_mentions`
- `voc_signals` (tendances agrégées)

Tables pilotage :
- `anomaly_events`, `shadow_runs`
- `agent_best_practices`, `kb_gaps`
- `caller_hash` (hachage pour cohérence analytique sans exposer numéros bruts)

---

## Runtime local vs repo source

### Repo source
`/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline`  
→ Point de travail. Toutes les modifications de code se font ici.

### Runtime launchd
`~/Library/Application Support/driveco-qa-pipeline/runtime`  
→ Répertoire exécuté par macOS. C'est une copie synchronisée du repo source.

**Règle** : après toute modification de code ou de `.env`, resynchroniser :

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

---

## Automatisation launchd

Jobs installés dans `~/Library/LaunchAgents/` :

| Job | Déclenchement | Label |
|-----|---------------|-------|
| benchmark | Tous les jours 01:30 | `com.kev1n.driveco.qa.benchmark` |
| daily | Tous les jours **02:30** | `com.kev1n.driveco.qa.daily` |
| watchdog daily | Tous les jours 06:45 | `com.kev1n.driveco.qa.daily-watchdog` |
| reliability | Lundi 04:00 | `com.kev1n.driveco.qa.reliability` |
| weekly | Lundi **07:15** | `com.kev1n.driveco.qa.weekly` |

Scripts :
- `setup_launchd.sh` — crée le runtime + installe les plists
- `sync_launchd_runtime.sh` — synchronise repo → runtime
- `run_from_cron.sh` — wrapper de lancement (lock, log, état)
- `run_daily_watchdog.sh` — relance le daily si absent ou bloqué

> **Piège connu** : après un reboot, `com.kev1n.driveco.qa.weekly` peut ne pas être chargé alors que les 4 autres le sont. Toujours vérifier avec `launchctl list | grep driveco` (5 jobs attendus).

---

## Séparation QA agent vs VoC client

Principe fondamental — ne jamais mélanger ces deux dimensions :

| QA agent | VoC client |
|----------|-----------|
| Juge la qualité de traitement de l'agent | Décrit ce que le client dit du produit / service |
| Rubric, soft skills, KB compliance | Topics, verbatims, churn risk, perception |
| `evaluations`, `soft_skills`, `issues` | `voc_extracts`, `topic_mentions`, `verbatims` |
| Passe LLM QA (`system_prompt.txt`) | Passe LLM VoC (`prompts/voc_system.txt`) |

Les résultats QA et VoC sont rendus **ensemble** dans le post Slack/rapport Markdown mais restent **séparés côté données**.

---

## Limites connues

- Gemma 4 améliore la finesse QA mais produit parfois des réponses JSON instables (batches longs)
- Anthropic non opérationnel actuellement (billing) — le fallback Ollama reste la voie unique
- Google Drive ne publie rien sans les fichiers OAuth locaux
- Le job launchd `weekly` peut se décrocher après un reboot macOS

---

## Lecture recommandée pour débuter

1. `README.md` — installation et commandes
2. Ce document
3. `RUNBOOK.md` — exploitation et incidents fréquents
