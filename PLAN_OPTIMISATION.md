# Plan d'optimisation QA + dashboard

## Cadre

Objectif :
- améliorer la qualité du scoring QA
- rendre les évaluations requêtables et rejouables
- préparer le pilotage manager et le futur dashboard
- ajouter une couche VoC séparée de la QA agent

Contraintes gardées :
- Ollama reste le moteur principal
- `launchd` reste l'orchestrateur
- Anthropic reste optionnel, jamais réactivé par défaut
- architecture modulaire conservée
- D1, Slack, Notion, Google Drive et rapports Markdown restent actifs

Constat repo actuel :
- la grille QA est dupliquée entre `system_prompt.txt` et `ollama_client.py`
- le parsing JSON repose encore sur du nettoyage tolérant et des regex défensives
- l'analyse Ollama est monolithique
- la persistance structurée n'existe pas encore côté dashboard
- `user_name` est déjà disponible dans `call_fetcher.py`, mais la dimension agent n'est pas propagée jusqu'à une base analytique dédiée
- il n'existe ni dossier `tests/` ni dossier `db/` dans le repo actuel

Note de cadrage :
- le prompt initial demandait 5 lots
- un Lot 6 VoC a ensuite été ajouté avec dépendances explicites
- je garde donc 6 lots indépendants, avec ordre recommandé `1 -> 2 -> 6 -> 3 -> 4 -> 5`

## Ordre d'exécution recommandé

1. Lot 1 : fiabiliser la sortie LLM avant toute extension de schéma
2. Lot 2 : poser la persistance structurée et l'idempotence
3. Lot 6 : brancher la VoC une fois schémas + stockage fiables
4. Lot 3 : produire les KPIs et alertes pilotage sur la nouvelle base
5. Lot 4 : mesurer la fiabilité dans le temps
6. Lot 5 : livrer les vues SQL et la doc dashboard en fin de chaîne

## Lot 1 — Qualité du scoring LLM

Objectif :
- supprimer la duplication de grille
- réduire la variance inter-run
- remplacer le parsing tolérant par une validation stricte
- sortir la note globale du LLM et la calculer côté Python

Livrables :
- `rubric.yaml`
- `schemas.py`
- `prompts/examples/qa_low.json`
- `prompts/examples/qa_mid.json`
- `prompts/examples/qa_high.json`
- refactor de `ollama_client.py`
- refactor de `llm_client.py`
- premiers tests dans `tests/`

Découpage :
1. créer une source unique de vérité pour la rubric QA avec 10 critères max, poids total = `1.0`, descripteurs `0/3/6/9`
2. charger cette rubric depuis Python et injecter sa version dans les sorties d'analyse
3. introduire des modèles `pydantic` pour extraction, scoring, KB compliance, soft skills et issues
4. remplacer `_parse_json`, `_sanitize_call_evaluation` et la logique équivalente par :
   - cleanup minimal des fences ```json
   - validation stricte
   - retry ciblé max 2 tentatives au total si champ manquant / type invalide
5. refactorer l'analyse Ollama en 2 passes :
   - passe extraction factuelle
   - passe scoring à partir de l'extract structuré
6. calculer `score_global` côté Python à partir de la rubric pondérée
7. imposer une citation pour chaque point d'amélioration et rejeter l'item si citation absente ou introuvable
8. ancrer l'échelle avec 3 few-shots anonymisés

Fichiers touchés :
- `system_prompt.txt`
- `ollama_client.py`
- `llm_client.py`
- `analysis_pipeline.py`
- `config.py`
- `requirements.txt`
- `RUNBOOK.md`
- `.env.example`

Critères d'acceptation :
- une seule rubric active
- plus de regex de sanitization métier hors cleanup des fences
- un même transcript varie moins entre deux runs successifs
- `score_global` ne dépend plus d'une note globale renvoyée par le LLM
- 5 fixtures Gemma réelles passent la validation pydantic

Risques / points de friction :
- risque de casse sur les prompts existants si le schéma est trop ambitieux d'un coup
- risque de timeout Ollama avec 2 passes si les batches ne sont pas réduits
- nécessité probable d'ajouter `pydantic` au projet et à la CI

Mergeability :
- lot autonome
- aucune migration DB requise
- compatible avec le reporting existant tant qu'un adaptateur garde le format de sortie attendu

## Lot 2 — Persistance structurée Supabase

Objectif :
- rendre chaque appel, transcript et évaluation requêtables
- permettre le replay et le re-scoring
- garder D1 comme source calls sans casser l'existant

Livrables :
- `db/migrations/001_init.sql`
- `persistence.py`
- intégration pipeline
- documentation d'architecture mise à jour

Découpage :
1. créer l'arborescence `db/migrations/`
2. ajouter la configuration Supabase dans `config.py` et `.env.example`
3. ajouter le client Supabase Python et une couche `persistence.py`
4. implémenter :
   - `upsert_agent()`
   - `upsert_call()`
   - `save_evaluation()`
   - `save_daily_snapshot()`
   - `save_llm_run()`
5. propager `user_id` Aircall si disponible depuis `call_fetcher.py`
6. persister les transcripts bruts pour replay
7. brancher les sauvegardes dans `analysis_pipeline.py` en mode additif par rapport à D1

Décision de design à figer dans ce lot :
- créer `daily_kpi_snapshot` avec `agent_id=''` pour les snapshots globaux et une clé `(date, scope, agent_id)`
- ne remplir la granularité agent qu'au Lot 3

Fichiers touchés :
- `call_fetcher.py`
- `analysis_pipeline.py`
- `config.py`
- `requirements.txt`
- `ARCHITECTURE.md`
- `RUNBOOK.md`
- `.env.example`

Critères d'acceptation :
- UPSERT idempotent sur clés naturelles
- un rerun du même jour ne duplique rien
- les appels évalués ont un agent, un transcript et une évaluation rejouable
- si Supabase tombe, le pipeline continue avec warning sans casser D1 + Markdown + Slack

Risques / points de friction :
- structure exacte des champs Aircall côté worker à confirmer pour `user_id`
- besoin de bien séparer erreurs bloquantes et non bloquantes
- attention à la volumétrie de `raw jsonb` et des transcripts

Mergeability :
- autonome
- additif
- ne dépend que du Lot 1 pour bénéficier d'un schéma d'analyse plus propre, mais peut techniquement être branché avec le format actuel si nécessaire

## Lot 6 — Voice of Customer

Objectif :
- extraire les sujets, perceptions, verbatims et signaux business sans polluer la QA agent
- stocker ces signaux dans une structure dédiée

Pré-requis :
- Lot 1 terminé pour la validation stricte
- Lot 2 terminé pour la persistance structurée

Livrables :
- `voc_taxonomy.yaml`
- `prompts/voc_system.txt`
- `prompts/examples/voc/*`
- extension `schemas.py`
- `db/migrations/003_voc.sql`
- extension `persistence.py`
- extension `metrics_builder.py`
- extension `report_formatter.py`
- extension `notifier.py`
- tests VoC

Découpage :
1. créer une taxonomie versionnée `topics / entities / aspects`
2. ajouter une 3e passe Ollama dédiée VoC, séparée de la QA agent
3. valider chaque item VoC avec citation retrouvable dans le transcript
4. persister :
   - extract global VoC
   - topics
   - perceptions par entity/aspect
   - verbatims
   - competitor mentions
   - signaux agrégés
5. ajouter anonymisation avant publication Slack / Notion
6. respecter l'opt-out RGPD si le signal est disponible dans la source appel
7. ajouter purge quotidienne des verbatims selon `VOC_VERBATIM_RETENTION_DAYS`
8. séparer la section `## Voix du client` dans les rapports Markdown

Fichiers touchés :
- `analysis_pipeline.py`
- `ollama_client.py`
- `schemas.py`
- `persistence.py`
- `metrics_builder.py`
- `report_formatter.py`
- `notifier.py`
- `config.py`
- `ARCHITECTURE.md`
- `RUNBOOK.md`
- `CLAUDE.md`
- `.env.example`

Critères d'acceptation :
- aucune confusion entre QA agent et VoC dans les schémas et les rapports
- toutes les citations publiées sont anonymisées
- la taxonomie est versionnée et stockée avec l'extract
- les verbatims peuvent être purgés sans perdre les agrégats

Risques / points de friction :
- la détection d'opt-out RGPD n'est peut-être pas exposée par le worker actuel
- les citations courtes peuvent être difficiles à matcher de façon robuste
- la VoC peut fortement allonger les temps Ollama si elle n'est pas batchée proprement

Mergeability :
- autonome après Lots 1 et 2
- additif
- aucune dépendance sur le dashboard final

## Lot 3 — KPIs pilotage & anomalies

Objectif :
- produire des métriques actionnables par agent
- détecter automatiquement les dérives opérationnelles

Pré-requis :
- Lot 2
- Lot 6 recommandé avant ce lot pour réutiliser les structures de signaux, mais non obligatoire pour les KPIs QA

Livrables :
- extension `metrics_builder.py`
- éventuelle migration `004_metrics.sql` si le schéma Lot 2 doit être complété
- alertes Slack enrichies
- tests sur fixtures

Découpage :
1. calculer les KPIs par agent sur 30 jours
2. écrire les snapshots quotidiens globaux et par agent
3. détecter les anomalies via rolling z-score 14 jours
4. produire la cohorte repeat callers J+7
5. agréger les KB gaps structurés
6. enrichir les alertes Slack avec 3 appels représentatifs

Décision de design :
- si `daily_kpi_snapshot.agent_id` n'a pas été posé au Lot 2, le faire ici par migration additive
- stocker les appels représentatifs sous forme d'IDs, pas de verbatim complet

Fichiers touchés :
- `metrics_builder.py`
- `analysis_pipeline.py`
- `notifier.py`
- `persistence.py`
- `db/migrations/*`
- `RUNBOOK.md`

Critères d'acceptation :
- requêtes possibles du type "évolution agent X sur 30 jours"
- alertes anomalies compréhensibles et non bruitées
- snapshot quotidien calculé une fois puis relu

Risques / points de friction :
- besoin de données historiques suffisantes pour les z-scores
- attention au biais d'échantillonnage de `select_calls_for_analysis`
- le repeat caller rate doit être défini clairement pour éviter des faux signaux

Mergeability :
- autonome après Lot 2
- ne modifie pas le cœur du scoring

## Lot 4 — Reliability QA & dérive modèle

Objectif :
- mesurer objectivement la qualité du scoring dans le temps
- détecter la dérive sémantique d'Ollama

Pré-requis :
- Lot 1
- Lot 2 recommandé pour stocker les runs

Livrables :
- `tests/gold_set/`
- `gold_set.yaml`
- mode `--mode reliability`
- planification `launchd` hebdo
- shadow run Anthropic optionnel
- benchmark Ollama enrichi

Découpage :
1. créer le gold set et le format d'annotation humaine
2. ajouter le mode `reliability` dans `analysis_pipeline.py`
3. calculer MAE + Pearson, puis écrire les résultats dans `llm_runs`
4. brancher une alerte Slack si seuil dépassé
5. ajouter `ENABLE_CLAUDE_SHADOW=true` sur 10% du trafic si activé
6. enrichir `bench_ollama_models.py` avec score sémantique

Fichiers touchés :
- `analysis_pipeline.py`
- `bench_ollama_models.py`
- `config.py`
- `notifier.py`
- `RUNBOOK.md`
- `ARCHITECTURE.md`
- `.env.example`
- `setup_launchd.sh`
- éventuellement `sync_launchd_runtime.sh`

Critères d'acceptation :
- un run reliability hebdo peut tourner seul
- alerte si `MAE > 1.0`
- comparaison sémantique disponible dans le bench, pas seulement la latence

Risques / points de friction :
- le gold set demande un vrai effort manuel initial
- Pearson est peu robuste si le gold set est trop petit ou trop resserré
- la shadow run ne doit jamais bloquer le daily

Mergeability :
- autonome après Lot 1
- lot de contrôle, pas de dépendance sur le dashboard

## Lot 5 — Préparation dashboard

Objectif :
- rendre la base directement consommable par Metabase puis par un futur front
- exposer un point de santé simple

Pré-requis :
- Lot 2
- Lot 3
- Lot 4 recommandé
- Lot 6 si la VoC doit être visible dès la phase 1 dashboard

Livrables :
- `db/migrations/006_views.sql`
- rôle `dashboard_reader`
- doc `DASHBOARD.md`
- endpoint local `GET /health`

Découpage :
1. créer les vues SQL QA
2. y ajouter les vues VoC si le Lot 6 est déjà mergé
3. documenter le rôle de lecture seule et la clé dédiée
4. exposer un endpoint santé minimal
5. documenter les dashboards cibles Metabase

Fichiers touchés :
- `db/migrations/006_views.sql`
- `DASHBOARD.md`
- `.env.example`
- `ARCHITECTURE.md`
- `RUNBOOK.md`
- nouveau module de santé si nécessaire

Critères d'acceptation :
- Metabase peut se brancher sur des vues stables sans parser du Markdown
- l'état du dernier run est visible via une route simple
- la doc suffit pour une phase 1 self-hosted

Risques / points de friction :
- bien gérer l'ordre des migrations si le Lot 6 arrive avant les vues
- éviter de coupler le health endpoint au runtime `launchd` de façon fragile

Mergeability :
- lot final de préparation
- n'impacte pas le scoring en prod

## Stratégie de validation transversale

Après chaque lot :
1. lancer `python analysis_pipeline.py --mode test` dans le repo source
2. resynchroniser le runtime `launchd`
3. lancer un `--mode daily --date <hier>` dans le runtime
4. vérifier :
   - pas de régression Slack
   - pas de régression Notion
   - pas de casse du Markdown
   - pas de duplication de données sur rerun
5. documenter le résultat dans la PR

## Risques transverses à surveiller

- biais d'échantillonnage : la logique actuelle favorise les appels problématiques
- coût temps : les passes Ollama supplémentaires peuvent rallonger le daily
- dépendance worker : certains champs Aircall requis pour agent / RGPD / replay peuvent manquer
- dette de compatibilité : plusieurs modules supposent encore le format JSON actuel
- publication externe : Slack / Notion / Drive doivent rester non bloquants

## Proposition de découpe PR

- PR 1 : rubric unique + schémas + extraction/scoring + tests
- PR 2 : Supabase + persistance + transcripts + agent dimension
- PR 3 : VoC + taxonomie + stockage + reporting séparé
- PR 4 : KPIs manager + snapshots + anomalies
- PR 5 : reliability + benchmark sémantique + launchd hebdo
- PR 6 : vues SQL + rôle reader + health + doc dashboard

## Points à confirmer avant Lot 1

- la source exacte des vrais transcripts anonymisés pour les few-shots
- la disponibilité réelle de `user_id` dans les payloads worker / Aircall
- le niveau de tolérance acceptable sur la durée du run quotidien avec 2 puis 3 passes Ollama
- le dossier Google Drive cible pour les nouveaux documents projet si une publication automatique est attendue hors rapports QA
