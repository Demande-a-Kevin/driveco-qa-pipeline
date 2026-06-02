# CSAT Call Insight — Design

**Date** : 2026-06-02
**Repo** : `driveco-qa-pipeline` (nouveau sous-module `csat_insight`)
**Statut** : validé en brainstorming, prêt pour plan d'implémentation

## Objectif

Dès qu'une réponse CSAT est publiée dans le canal Slack `#sprig-responses-csat-care`
(`C0B724V5X4L`) par le bot Sprig, poster **automatiquement en thread** sous ce message,
via le **bot Kev1n** :

1. le **lien du transcript** de l'appel Aircall générateur ;
2. une **analyse synthétique (3-4 lignes, ≤ 55 mots)** expliquant ce qui a motivé la note,
   et de **quel côté** vient le motif : `Agent/Assistance`, `Borne/App`, `Mixte`, `Autre`.

Le tout tourne **en local sur le Mac mini (kev1n)** avec **Ollama / Gemma** — aucun cloud
pour le scoring (contrainte projet identique au pipeline QA). Anthropic n'est pas utilisé.

C'est une version **très condensée** de l'analyse du pipeline QA Driveco : pas de note /10,
pas de liste de recommandations, pas de plan d'action — juste *pourquoi cette note, et de
quel côté*.

## Contexte observé (format réel du canal, 2026-06-02)

- Auteur des posts : bot **Sprig** `U0798UDP7U0`. Le bot **Kev1n** `U0AMEHDCDV5` est déjà
  membre du canal.
- Format type :
  `<survey|*CSAT Customer Care - New Version*> received a new response from <mailto:3825857378@driveco.com|3825857378@driveco.com>.`
  puis un blockquote avec les réponses.
- **Call ID** = la partie numérique de l'email `3825857378@driveco.com` → `3825857378`.
- **Score** = première réponse du blockquote (entier 1–5), question
  « Dans quelle mesure notre assistance a-t-elle répondu à vos attentes ? ».
- Champs contextuels utiles (facultatifs au prompt) : « Qu'est-ce qui a le plus influencé
  votre satisfaction… » et « Quelles améliorations suggéreriez-vous… ».
- **Cas limite réel** : certains posts n'ont **pas de call ID** (« received a new response. »
  sans email) → non rattachables.
- Transcript : `fetch_transcript(call_id)` (déjà présent dans `call_fetcher.py`) ;
  lien partagé dans le post = `https://assets.aircall.io/calls/{call_id}/recording/info`.

## Décisions de cadrage (brainstorming)

| Sujet | Décision |
|---|---|
| Détection | **Polling launchd** toutes les ~3 min (pas de Socket Mode, pas d'endpoint public) |
| Emplacement | **Module dans `driveco-qa-pipeline`** (réutilise l'existant, repo déjà en place) |
| Persistance | **Slack uniquement** — pas de Supabase ni table dédiée |
| Verdict | **Trancher franc** un côté dominant ; `Mixte` seulement si vraiment 50/50 |
| Périmètre | **Toutes** les CSAT avec call ID (positives ET négatives) |
| Backfill | **Go-forward only** : baseline = dernier ts au premier run, pas de rattrapage du backlog |

## Architecture

Un seul point d'entrée `csat_insight.py` exécuté périodiquement par launchd. Une passe :

```
launchd (StartInterval 180s)
  └─ csat_insight.run_once()
       1. state = load_state()                      # .csat_insight_state.json : last_ts, pending[]
       2. msgs = slack_history(CHANNEL, oldest=last_ts, author=SPRIG)  # chrono, plafonné 30
       3. pour chaque msg (+ les pending en retry) :
            a. parsed = parse_sprig(msg)             # call_id, score, contexte
            b. si pas de call_id  -> skip (avance ts)
            c. transcript = fetch_transcript(call_id)
                 - None/404 -> pending (retry), budget ~1h, puis fallback lien-seul
            d. si déjà répondu en thread -> skip (idempotence)
            e. insight = analyze(transcript, score, contexte)   # Gemma one-shot -> JSON
            f. post_thread(msg.ts, render(insight, call_id, score))
       4. save_state()  # avance last_ts, met à jour pending
```

### Modules / responsabilités

- **`csat_insight.py`** — orchestration d'une passe (`run_once`), gestion d'état, boucle.
- **`csat_parser.py`** (ou fonctions dans le module) — `parse_sprig(message) -> CsatPost | None`
  (call_id, score, texte contexte). Pur, testable sans réseau.
- **`csat_prompting.py`** — construction du prompt Gemma + parsing de la sortie JSON en
  `Insight{verdict, sentiment, synthese}`. Pur sauf l'appel `ollama_client`.
- **Réutilisé tel quel** : `call_fetcher.fetch_transcript`, `ollama_client`, `config`.
- **Slack** : petite fonction d'envoi avec `thread_ts` + lecture du thread (idempotence).
  Le `notifier._post_to_slack` actuel ne gère pas `thread_ts` → on ajoute un helper dédié
  (ne pas régresser le notifier existant).

### État (`.csat_insight_state.json`)

```json
{
  "last_ts": "1780404011.283339",
  "pending": [
    {"ts": "1780396448.966269", "call_id": "3825013786", "first_seen": 1780396500, "attempts": 3}
  ]
}
```

- `last_ts` : avance de façon monotone une fois un message traité ou skippé.
- `pending` : messages dont le transcript n'était pas prêt ; retentés à chaque passe jusqu'au
  budget (`first_seen + ~1h` ou `attempts >= 20`), puis post fallback « lien seul » et sortie
  du pending.

## Prompt & format de sortie

### Contraintes du prompt (dures)

- Sortie **JSON strict** : `{"verdict": "...", "sentiment": "...", "synthese": "..."}`.
- `verdict` ∈ `Agent/Assistance | Borne/App | Mixte | Autre` (trancher un dominant).
- `sentiment` ∈ `positif | négatif | mitigé`.
- `synthese` : **≤ 55 mots**, **une seule** explication (pourquoi la note + de quel côté),
  **pas de liste**, **pas de note /10**, **pas de recommandation**, **pas de plan d'action**.
- Si le transcript est trop dégradé pour conclure : le dire en une phrase, ne pas inventer.

### Rendu Slack (thread reply)

```
🔎 *Analyse appel* · CSAT {score}/5 · <https://assets.aircall.io/calls/{call_id}/recording/info|transcript>
*Verdict : {verdict}* ({sentiment})
{synthese}
```

Exemple (CSAT 3/5, borne Carrefour Rives-sur-Fure) :

> 🔎 *Analyse appel* · CSAT 3/5 · <transcript>
> *Verdict : Borne/App* (mitigé)
> Le client salue l'écoute de l'agent mais note bas car la borne n°4 reste hors service et
> son QR code de paiement est manquant : le motif est matériel/terrain, pas l'assistance.

## Configuration

- `SLACK_CSAT_CHANNEL_ID` (défaut `C0B724V5X4L`).
- `SLACK_BOT_TOKEN` : déjà présent (bot Kev1n).
- `DISABLE_CSAT_INSIGHT` (flag on/off, défaut off), aligné sur `DISABLE_SLACK_NOTIFICATIONS`.
- Modèle Ollama : réutilise la config Gemma existante du pipeline.

> ⚠️ **Prérequis scope Slack** : le bot poste déjà (`chat:write`) mais doit pouvoir **lire**
> l'historique du canal → scopes `channels:history` (canal public). À vérifier/ajouter dans
> la config de l'app Slack avant la prod ; sinon `conversations.history` renverra
> `missing_scope`.

## Ordonnancement (launchd)

- Label `com.kev1n.driveco.csat-insight`, `StartInterval = 180`.
- Logs dans le dossier de logs du pipeline.
- Ajout au script `setup_launchd.sh` existant (ou plist dédié documenté dans le RUNBOOK).

## Cas limites & robustesse

| Cas | Comportement |
|---|---|
| Post sans call ID | Skip, avance `last_ts`, rien posté |
| Transcript pas prêt (404) | `pending` + retry ; budget ~1h puis fallback « lien seul » |
| Réponse du bot déjà dans le thread | Skip (idempotence : relecture du thread avant post) |
| Ollama indisponible | Log, message non consommé, retry à la passe suivante |
| Aircall API erreur transitoire | `fetch_transcript` retente déjà ; sinon `pending` |
| Volume | Plafond de messages traités par passe (ex. 30) |
| Premier run | Baseline `last_ts` = maintenant, pas de backfill |

## Tests (pytest, TDD)

- `parse_sprig` : avec call ID / sans call ID / score absent / contexte multi-lignes.
- Budget de retry `pending` (transcript indisponible → fallback après seuil).
- Idempotence : message déjà répondu → pas de double post.
- Parsing de la sortie Gemma (JSON valide / JSON bruité → dégradation propre).
- Rendu Slack (format, troncature ≤ 55 mots respectée côté validation).
- Avance monotone de `last_ts`.

(Appels réseau Slack/Aircall/Ollama mockés, comme dans la suite de tests existante.)

## Livrables

1. Module `csat_insight` + tests.
2. Helper Slack `thread_ts` + lecture de thread.
3. Entrée launchd + section RUNBOOK.
4. Section README.
5. Doc Obsidian (vault Kev1n Cockpit) + page Notion (via MCP) décrivant le module.
6. Mise à jour mémoire projet.

## Hors scope (YAGNI)

- Pas de persistance Supabase / table CSAT↔call (décidé).
- Pas de Socket Mode / endpoint public.
- Pas de backfill du backlog historique.
- Pas de dashboard dédié (le pilotage reste celui du pipeline/cockpit).
- Pas de write-back vers Sprig.
