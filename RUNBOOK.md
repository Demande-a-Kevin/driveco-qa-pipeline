# Runbook

Exploitation quotidienne de `driveco-qa-pipeline` sans devoir relire le code.

---

## Routine du matin

### 1. Vérifier que les 5 jobs launchd sont chargés

```bash
launchctl list | grep driveco
```

Résultat attendu — 5 lignes :
```
-  0  com.kev1n.driveco.qa.benchmark
-  0  com.kev1n.driveco.qa.daily
-  0  com.kev1n.driveco.qa.daily-watchdog
-  0  com.kev1n.driveco.qa.reliability
-  0  com.kev1n.driveco.qa.weekly
```

> Le code de sortie `0` = dernier run terminé sans erreur. Un code non-nul ou une ligne manquante = problème.

Si `weekly` est absent (arrive après certains reboots) :

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kev1n.driveco.qa.weekly.plist
```

### 2. Vérifier le log du daily

```bash
tail -50 "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_daily.log"
```

Séquence normale attendue :
1. `start mode=daily`
2. `ANALYSE QUOTIDIENNE`
3. `appels récupérés`
4. `Appels QA scope`
5. `Pre-screening ... via Ollama`
6. `Analyse ... appels risque faible`
7. `Analyse quotidienne terminée`
8. `Slack envoyé`
9. `done mode=daily ... exit=0`

### 3. Vérifier l'état du run

```bash
cat "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/state/daily_status.env"
```

### 4. Vérifier Slack

Le post Slack contient dans l'ordre : KPIs globaux → lignes → routage IVR → pics → VoC → alertes. Si un bloc est absent, voir la section Incidents.

---

## Commandes de base

### Test de connectivité

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
.venv/bin/python analysis_pipeline.py --mode test
```

### Run quotidien manuel

```bash
cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python analysis_pipeline.py --mode daily --date 2026-04-27
```

### Run hebdomadaire manuel

```bash
cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python analysis_pipeline.py --mode weekly --date 2026-04-28
```

### Rattrapage Notion (pages manquantes)

Si des jours sont manquants dans Notion (erreur 404 passée, intégration déconnectée) :

```python
# Script one-shot depuis le runtime
import sys; sys.path.insert(0, '.')
import notion_reporter
from datetime import datetime
from pathlib import Path

md = Path("qa-driveco-data/2026-04-17_daily_report.md").read_text()
notion_reporter.save_report_to_notion(md, datetime(2026, 4, 17), "daily")
```

### Resynchroniser le runtime après modif

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

### Lancer les tests

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
.venv/bin/python -m pytest -x --tb=short
# Attendu : 41 passed
```

---

## Fichiers de log

| Fichier | Contenu |
|---------|---------|
| `cron_daily.log` | Log complet du run daily (pipeline + Supabase + Slack) |
| `cron_weekly.log` | Log complet du run weekly |
| `cron_reliability.log` | Log du run reliability (gold set) |
| `cron_benchmark.log` | Log benchmark Ollama |
| `pipeline.log` | Log détaillé de l'analyse (warnings LLM, fallbacks) |
| `launchd_daily.log` | stdout/stderr launchd du daily |
| `launchd_weekly.log` | stdout/stderr launchd du weekly |

Tous dans `~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/`.

---

## Incidents fréquents

### 1. Rien n'est posté sur Slack

Vérifications :

```bash
# Le job s'est-il lancé ?
tail -5 "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/launchd_daily.log"

# Le run a-t-il terminé ?
tail -20 "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/cron_daily.log"

# Le flag Slack existe-t-il ?
ls "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/"*.flag 2>/dev/null
```

Causes fréquentes :
- Run non déclenché (5 jobs pas tous chargés)
- Run trop lent (Gemma 4 sur batch difficile → watchdog relance)
- Runtime non resynchronisé après modif de code
- Plantage Ollama
- Erreur token Slack

### 2. Le run weekly n'a pas tourné (lundi matin)

Cause : job `com.kev1n.driveco.qa.weekly` non chargé dans launchd.

Vérifier :
```bash
launchctl list | grep weekly
```

Recharger :
```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kev1n.driveco.qa.weekly.plist
```

Rattrapage manuel :
```bash
cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
bash run_from_cron.sh weekly manual_catchup
```

### 3. Notion : pages quotidiennes plus créées (erreur 404)

Cause : l'intégration Notion **"Kev1n Claude"** a perdu l'accès à la page parent.

Vérifier via l'API :
```bash
cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
import config, requests
r = requests.get(
    f'https://api.notion.com/v1/pages/{config.NOTION_REPORTS_PAGE_ID}',
    headers={'Authorization': f'Bearer {config.NOTION_API_KEY}', 'Notion-Version': '2022-06-28'}
)
print(r.status_code)
"
```

Fix : Notion → ouvrir la page `NOTION_REPORTS_PAGE_ID` → `•••` → **Connexions** → reconnecter "Kev1n Claude".

Puis rattraper les jours manquants avec le script one-shot de rattrapage (voir ci-dessus).

### 4. Code changé mais l'automatisation tourne sur l'ancienne version

Cause : runtime launchd non resynchronisé.

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh
bash setup_launchd.sh
```

### 5. Ollama échoue ou répond mal

Symptômes dans les logs : `Réponse non-JSON`, `fallback heuristique`, `Ollama échoué`.

```bash
# Ollama répond-il ?
curl http://localhost:11434/api/tags

# Modèle chargé ?
ollama list | grep gemma4
```

Fix de premier niveau :
- `ollama pull gemma4:latest` si le modèle est absent
- Relancer Ollama si le processus est mort
- Le pipeline continue avec un run dégradé (`run_degraded=true`) — ce n'est pas bloquant

### 6. Supabase n'écrit rien

Checks :
```bash
grep "SUPABASE_URL\|SUPABASE_SERVICE_KEY" "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/.env"
grep "\[persistence\]" "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/pipeline.log" | tail -10
```

Si les variables sont vides → Supabase désactivé (mode dégradé silencieux, pas bloquant).  
Si les variables sont présentes et les erreurs persistent → vérifier que les migrations SQL sont appliquées :
- `db/migrations/001_init.sql`
- `db/migrations/003_voc.sql`
- `db/migrations/004_metrics_agent.sql` → `008_product_area.sql`

### 7. Google Drive ne publie rien

Cause : fichiers OAuth absents.

```bash
ls "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/gdrive_credentials.json" 2>/dev/null
ls "$HOME/Library/Application Support/driveco-qa-pipeline/runtime/gdrive_token.json" 2>/dev/null
```

Le pipeline termine sans Google Drive — ce n'est pas bloquant.

### 8. Blocs manquants dans le post Slack

Depuis lot 14, tous les blocs doivent apparaître dans le post daily :
- KPIs globaux + par ligne
- Routage IVR
- Pics d'appels
- VoC
- Alertes

Si un bloc est absent, vérifier dans `cron_daily.log` qu'il n'y a pas de données vides (ex: 0 appels analysés, 0 transcripts). C'est le cas normal pour les jours fériés ou week-ends.

### 9. Validation JSON Ollama casse l'analyse

Symptômes : `validation Ollama échouée`, `réponse vide`.

```bash
.venv/bin/python -m pytest tests/test_schemas.py -v
```

Fix : corriger le schéma attendu dans `schemas.py` plutôt que d'introduire du regex de nettoyage.

---

## Interpréter le run daily

Un run daily réussi produit :
- Un fichier `qa-driveco-data/YYYY-MM-DD_daily_report.md`
- Un flag `qa-driveco-data/.slack_sent_daily_YYYY-MM-DD.flag`
- Une note Obsidian `Driveco QA/Daily/YYYY-MM-DD — Driveco QA Daily.md`
- Une page Notion sous `NOTION_REPORTS_PAGE_ID`
- Un post Slack dans `SLACK_CHANNEL_ID`

Un run `degraded` (peu d'appels, Ollama instable) produit le rapport avec des sections vides mais sans erreur fatale.

---

## Horaires launchd actuels

| Job | Heure | Surcharge via |
|-----|-------|--------------|
| benchmark | 01:30 | `BENCH_HOUR` / `BENCH_MINUTE` |
| daily | **02:30** | `DAILY_HOUR` / `DAILY_MINUTE` |
| watchdog daily | 06:45 | `WATCHDOG_HOUR` / `WATCHDOG_MINUTE` |
| reliability | Lundi 04:00 | — |
| weekly | Lundi **07:15** | `WEEKLY_HOUR` / `WEEKLY_MINUTE` |

Modifier et réinstaller :
```bash
DAILY_HOUR=4 DAILY_MINUTE=0 bash setup_launchd.sh
```

---

## CSAT Call Insight

**But :** Lire automatiquement le canal `#sprig-responses-csat-care` (Slack) toutes les 3 minutes, détecter les nouveaux posts Sprig CSAT, puis poster en thread sous chaque post le lien du transcript Aircall et un verdict Gemma (≤ 55 mots) indiquant si la note vient de l'agent ou de la borne/app.

**Label launchd :** `com.kev1n.driveco.csat-insight`

**Intervalle :** 180 s (StartInterval, pas CalendarInterval — démarre au boot + toutes les 3 min)

**Logs :**

| Fichier | Contenu |
|---------|---------|
| `csat-insight.log` | stdout — logs INFO du pipeline |
| `csat-insight.err.log` | stderr — erreurs Python non capturées |

Dans `~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/`.

**Kill-switch :** `DISABLE_CSAT_INSIGHT=true` dans `.env` (ou en variable d'env) désactive toutes les passes sans toucher au fichier d'état.

**Fichier d'état :** `.csat_insight_state.json` dans le répertoire runtime (non versionné).
- Présent → reprend depuis le dernier `last_ts` connu.
- Absent → au prochain run, initialise la baseline au timestamp courant (go-forward uniquement, pas de backfill de l'historique Slack).
- Supprimer le fichier = ré-initialiser la baseline = ignorer tous les posts antérieurs.

**Prérequis scope Slack :** le bot Kev1n doit avoir le scope `channels:history` (canal public `C0B724V5X4L`). Ce scope est déjà accordé. Si une erreur `missing_scope` apparaît dans les logs, réinstaller l'app Slack depuis le portail développeur Slack.

**Aller en prod (go-live) :**

1. S'assurer que `.csat_insight_state.json` n'existe PAS dans le runtime (premier run posera la baseline).
2. Synchroniser le runtime et (re)charger les jobs :
   ```bash
   cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
   bash sync_launchd_runtime.sh
   bash setup_launchd.sh
   ```
3. Vérifier que le job est chargé :
   ```bash
   launchctl list | grep csat-insight
   ```
4. Forcer un premier run pour poser la baseline (sans poster) :
   ```bash
   cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
   .venv/bin/python csat_insight.py
   # Doit logger : Baseline initialisée à <ts>
   ```

**Forcer un run manuel :**

```bash
cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python csat_insight.py
```

---

## Sentiment Call Insight

**But :** Répondre automatiquement en thread sous chaque post du bot Captain Pingouin dans le canal `#ucc-sentiment-analysis-ai`, avec une analyse Gemma de 4-5 lignes. Pour les appels à score négatif : verdict (Agent/Assistance · Borne/App · Mixte · Autre), moment clé, et si la situation était rattrapable. Pour les appels « non répondus » : analyse adaptative (LLM si transcript disponible, déterministe sinon) + signalement d'incohérence si Aircall indique un décrochage.

**Label launchd :** `com.kev1n.driveco.sentiment-insight`

**Intervalle :** 180 s (StartInterval, pas CalendarInterval — démarre au boot + toutes les 3 min)

**Logs :**

| Fichier | Contenu |
|---------|---------|
| `sentiment-insight.log` | stdout — logs INFO du pipeline |
| `sentiment-insight.err.log` | stderr — erreurs Python non capturées |

Dans `~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/`.

**Kill-switch :** `DISABLE_SENTIMENT_INSIGHT=true` dans `.env` (ou en variable d'env) désactive toutes les passes sans toucher au fichier d'état.

**Cap anti-saturation Ollama :** `SENTIMENT_INSIGHT_MAX_PER_RUN` (défaut 5) — nombre max de nouveaux posts traités par passe. Les posts non traités restent en attente pour la passe suivante.

**Fichier d'état :** `.sentiment_insight_state.json` dans le répertoire runtime (non versionné).
- Présent → reprend depuis le dernier `last_ts` connu.
- Absent → au prochain run, initialise la baseline au timestamp courant (go-forward uniquement, pas de backfill de l'historique Slack).
- Supprimer le fichier = ré-initialiser la baseline = ignorer tous les posts antérieurs.

**Prérequis scope Slack :** le bot Kev1n doit avoir les scopes `channels:history` et `chat:write`. Ces deux scopes sont déjà accordés au bot. Si une erreur `missing_scope` apparaît dans les logs, réinstaller l'app Slack depuis le portail développeur Slack.

**Aller en prod (go-live) :**

1. S'assurer que `.sentiment_insight_state.json` n'existe PAS dans le runtime (premier run posera la baseline).
2. Synchroniser le runtime et (re)charger les jobs :
   ```bash
   cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
   bash sync_launchd_runtime.sh
   bash setup_launchd.sh
   ```
3. Vérifier que le job est chargé :
   ```bash
   launchctl list | grep sentiment-insight
   ```
4. Forcer un premier run pour poser la baseline (sans poster) :
   ```bash
   cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
   .venv/bin/python sentiment_insight.py
   # Doit logger : Baseline initialisée à <ts>
   ```

**Forcer un run manuel :**

```bash
cd "$HOME/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python sentiment_insight.py
```

---

## Configuration depuis le cockpit (depuis 2026-05-07)

Depuis l'intégration QA UCC dans le cockpit, la config (rubric, prompt, sampling)
peut être éditée depuis https://cockpit.kev1ncockpit.com/qa/config.

La pipeline lit la config effective au boot via `runtime_config.load_runtime_config()` :
1. Tables QA-UCC : `pipeline_config`, `rubric_versions`, `prompt_overrides` (active row)
2. Fallback : `system_prompt.txt`, `rubric.yaml`, `config.py` (Git)

Voir :
- `runtime_config.py` — résolution déterministe DB + Git
- `analysis_pipeline.py:91+` — boot wiring
- Spec : `~/workspace/personal/kev1n-cockpit/docs/superpowers/specs/2026-05-05-qa-cockpit-integration-design.md`
