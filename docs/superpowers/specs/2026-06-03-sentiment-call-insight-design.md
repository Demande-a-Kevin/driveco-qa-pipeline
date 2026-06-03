# Sentiment Call Insight — Design

**Date** : 2026-06-03
**Repo** : `driveco-qa-pipeline` (nouveau module `sentiment_insight`)
**Statut** : validé en brainstorming, prêt pour plan d'implémentation

## Objectif

Sur le canal Slack `#ucc-sentiment-analysis-ai` (`C0B7PA2EZQ8`), le bot **Captain
Pingouin** (`bot_id B0B6V282D5Y`) poste automatiquement deux types d'appels :

1. **Appels critiques** (score de sentiment < -0,6) : lien d'accès + bloc JSON de scores.
2. **Appels « non répondus »** : `[Call not answered]` + lien d'accès.

Ouvrir chaque lien pour écouter/analyser l'appel est pénible. On veut que le **bot Kev1n**
réponde **en thread**, en **4-5 lignes max**, avec les éléments clés :

- pour un **score négatif** : pourquoi ce score (verdict côté agent vs borne/app, moment de
  bascule, rattrapé ou non) ;
- pour un **« non répondu »** : ce qui s'est réellement passé (souvent l'appel a été décroché).

Tourne **en local sur le Mac mini** avec **Ollama / Gemma**. C'est un **second instance du
mécanisme [CSAT Call Insight]** : on réutilise au maximum ses briques.

## Contexte observé (formats réels, 2026-06-03)

Auteur = bot `B0B6V282D5Y` (filtrage par `bot_id`, pas `user`).

**Type `negative`** :
```
Access link : <https://assets.aircall.io/calls/3827871596/recording/info>
Score [-1 to +1]  :  -0.6  (confidance : 95%)
--------------
{ "overall_score": -0.88, "initial_score": -0.45, "peak_negative_score": -1,
  "final_score": -0.6, "label": "negative_unresolved", "confidence": 0.95 }
```

**Type `unanswered`** :
```
[Call not answered]
Access link : <https://assets.aircall.io/calls/3827393590/recording/info>
```

- **call_id** = capture de `assets.aircall.io/calls/(\d+)/recording/info` (après `html.unescape`).
- ⚠️ **Découverte clé** : « [Call not answered] » est le label du bot Pingouin, **pas** la
  réalité Aircall. Vérifié : `3828790042` (marqué non répondu) est en fait **décroché 273s**,
  tagué `SUCCESS`, et `missed_call_reason` est vide. Donc un « pourquoi pas répondu » naïf
  serait faux ; il faut s'adapter à la réalité Aircall et **un transcript existe souvent**.
- Canal **à fort volume** (plusieurs posts/heure).

## Décisions de cadrage (brainstorming 2026-06-03)

| Sujet | Décision |
|---|---|
| Type `unanswered` | **Analyser comme les autres** : transcript si dispo → analyse contenu ; sinon → faits Aircall. Pas de raison inventée. |
| Incohérence label | **Signaler** quand « non répondu » est en fait décroché (note explicite, fiabilise le bot). |
| Périmètre | **Tout** (le bot filtre déjà < -0,6). |
| Sortie négatif | **Verdict + moment de bascule + rattrapé ?** (réutilise le verdict CSAT). |
| Emplacement | **Nouveau module parallèle** `sentiment_insight` (pas de refonte du moteur CSAT). |
| Backlog | **Go-forward only** (baseline au 1er run). |
| Charge Ollama | **Cap N posts/passe** (déf. 5) pour ne pas concurrencer le QA daily déjà lent. |

## Architecture

Point d'entrée `sentiment_insight.py`, lancé par launchd (`StartInterval` 180s). Une passe
calquée sur `csat_insight.run_once` :

```
launchd (180s)
  └─ sentiment_insight.run_once()
       1. state = csat_state.load_state(.sentiment_insight_state.json)   # last_ts, pending[]
          1er run -> baseline = now, return (go-forward)
       2. msgs = fetch_new_posts(CHANNEL, oldest=last_ts, author=PINGOUIN_BOT_ID)  # cap 5
       3. pour chaque post (+ pending) :
            a. parsed = parse_pingouin(msg)         # call_id, kind, scores
            b. pas de call_id      -> skip
            c. déjà répondu en thread -> skip
            d. transcript = fetch_transcript(call_id) ; facts = fetch_call_facts(call_id)
            e. insight = analyze(kind, transcript, facts, scores)   # Gemma -> JSON
               transcript indispo + négatif -> pending (retry, budget ~1h) puis lien-seul
            f. post_thread(post.ts, render(insight, ...))
       4. csat_state.save_state(...)
```

### Modules / responsabilités

- **`sentiment_parser.py`** — `parse_pingouin(msg) -> SentimentPost`. Pur, testable.
  `SentimentPost{ts, call_id, kind ('negative'|'unanswered'), scores (dict|None), raw_text}`.
  Extraction call_id (regex sur le lien, `html.unescape` d'abord) ; pour `negative`, parse du
  bloc JSON (`json.loads` tolérant) → `initial/peak/final/label/confidence`.
- **`sentiment_prompting.py`** — `analyze(kind, transcript, facts, scores) -> SentimentInsight`
  + `build_prompt(...)`. Prompt **adaptatif** :
  - `negative` : transcript + faits + trajectoire → JSON
    `{verdict, moment, recoverable, synthese}` (verdict ∈ Agent/Assistance·Borne/App·Mixte·Autre ;
    recoverable ∈ oui·non·partiel ; synthese ≤ ~50 mots).
  - `unanswered` **avec** transcript → analyse de contenu (même schéma, verdict possible).
  - `unanswered` **sans** transcript → pas d'appel LLM : insight déterministe depuis les faits.
  Normalisation/troncature comme CSAT.
- **`sentiment_insight.py`** — orchestration `run_once` (baseline, pending, idempotence,
  rendu, post) + entrée CLI. Constantes `PINGOUIN_BOT_ID = "B0B6V282D5Y"`, cap passe.
- **Réutilisé tel quel** : `call_fetcher.fetch_transcript`, `csat_aircall.fetch_call_facts`,
  `csat_state.load_state/save_state`.
- **Généralisé (petit)** : `csat_slack` — ajouter une fonction de lecture filtrant l'auteur
  par `user` **ou** `bot_id` (Pingouin poste en `bot_id`). `thread_has_bot_reply` et
  `post_thread` sont réutilisés tels quels.

### Rendu Slack (thread, ≤ 4-5 lignes)

Négatif :
```
🔎 *Analyse appel* · score final {final} · <transcript>
⏱ décroché après {tta}s · durée {d}
*Verdict : {verdict}* · {moment} · {rattrapé}
{synthese}
```

« Non répondu » réellement décroché :
```
🔎 *Analyse appel* · <transcript>
ℹ️ marqué « non répondu » mais décroché {durée}s
{analyse de ce qui s'est passé}
```

« Non répondu » vraiment sans décrochage :
```
🔎 *Analyse appel* · <transcript>
⏱ non décroché · {faits Aircall : sens, attente, rappel éventuel}
```

## Configuration

- `SLACK_SENTIMENT_CHANNEL_ID` (défaut `C0B7PA2EZQ8`).
- `SLACK_BOT_TOKEN` / `SLACK_BOT_USER_ID` : déjà présents (bot Kev1n, pour poster + dédup).
- `DISABLE_SENTIMENT_INSIGHT` (flag on/off).
- `SENTIMENT_INSIGHT_MAX_PER_RUN` (défaut 5) — cap anti-saturation Ollama.
- Modèle Ollama : config Gemma existante ; timeout = `OLLAMA_ANALYSIS_TIMEOUT`.

## Ordonnancement (launchd)

- Label `com.kev1n.driveco.sentiment-insight`, `StartInterval` 180s, ajouté à
  `setup_launchd.sh` (même conventions que `csat-insight`). Logs `sentiment-insight*.log`.

## Cas limites & robustesse

| Cas | Comportement |
|---|---|
| Pas de call_id | skip, avance `last_ts` |
| Négatif, transcript pas prêt | `pending` + retry (budget ~1h) puis fallback lien-seul |
| « Non répondu » sans transcript | insight déterministe (faits), pas de pending |
| Déjà répondu en thread | skip (idempotence) |
| Ollama / Aircall KO | log, retry passe suivante |
| Volume | cap `SENTIMENT_INSIGHT_MAX_PER_RUN` par passe |
| 1er run | baseline = maintenant, pas de backlog |

## Tests (pytest, TDD)

- `parse_pingouin` : negative (avec JSON) / unanswered / sans call_id / JSON bruité.
- `analyze` : negative (mock Gemma) → verdict/moment/recoverable normalisés + tronqués ;
  unanswered sans transcript → insight déterministe sans appel LLM.
- Filtre auteur `bot_id` dans la lecture Slack généralisée.
- Orchestration : baseline, cap par passe, pending/budget, idempotence, note d'incohérence
  « non répondu mais décroché ».
- Rendu : 3 variantes (négatif / non-répondu-décroché / non-répondu-sec).

(Slack/Aircall/Ollama mockés.)

## Livrables

1. Modules `sentiment_parser` / `sentiment_prompting` / `sentiment_insight` + tests.
2. Généralisation lecture Slack par `bot_id`.
3. Entrée launchd + section RUNBOOK + README.
4. Doc Obsidian/Notion + mémoire.

## Hors scope v1 (YAGNI)

- **Dédoublonnage cross-systèmes** (CSAT + QA daily + ce module analysent parfois le même
  appel, 3× Ollama) — vrai gain mais nécessite un cache/refonte → **v2**.
- **Lookup multi-appels** « rappelé / repeat caller / quelle borne » pour les non-répondus
  → **v2** si valeur confirmée.
- Pas de généralisation du moteur CSAT en moteur multi-sources (décidé : module parallèle).
- Pas de seuil/sampling (on traite tout ce que le bot poste).
