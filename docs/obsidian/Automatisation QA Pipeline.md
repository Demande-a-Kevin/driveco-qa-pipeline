# Automatisation QA Pipeline Driveco

Dernière mise à jour : 2026-05-14

## Rôle

Cette automatisation analyse les appels Aircall Driveco / UCC, produit un rapport QA quotidien, puis publie les résultats dans Slack, Notion, Obsidian et Google Drive.

Repo GitHub : https://github.com/Demande-a-Kevin/driveco-qa-pipeline

## État actuel

- Couverture d'analyse configurée à 100 % des appels éligibles.
- Fallback Aircall direct activé quand la source D1 / call-history renvoie 0 appel ou échoue.
- Publication vide bloquée par défaut via `ALLOW_EMPTY_DAILY_REPORT=false`.
- Liens Aircall corrigés vers `https://assets.aircall.io/calls/.../recording/info`.
- Bloc Slack `Risque client détecté` retiré du reporting principal car non actionnable tel quel.
- Bloc `Voix du client` renommé en `Raisons d'appel`.
- Les raisons d'appel sont maintenant détaillées avec sous-motifs : localisation, panne, interruption, indisponibilité, paiement, bug app.

## Incident 11/05/2026

Cause : le pipeline s'est déclenché mais la source D1 / call-history a renvoyé 0 appel pour le 11/05. Le pipeline a ensuite publié un rapport vide parce qu'il n'avait pas de garde-fou bloquant les publications sans appels.

Correctifs appliqués :

- fallback Aircall direct sur `fetch_calls_range`;
- garde-fou anti-publication vide dans `run_daily`;
- rattrapage complet du 11/05 via Aircall direct;
- mise à jour Slack / Notion / Obsidian du rapport 11/05;
- ajout de tests de non-régression.

## Format Slack attendu

Le post daily contient désormais :

1. KPIs et couverture d'analyse.
2. Routage IVR et pics d'appels.
3. Raisons d'appel avec sous-motifs.
4. Opportunités, bonnes pratiques et concurrents si détectés.
5. Appels longs, appels problématiques, alertes et KB gaps.

Le bloc `Risque client détecté` ne doit pas être publié tant qu'il ne donne pas une action claire, par exemple une liste qualifiée de cas à rappeler, rembourser, escalader ou suivre.

## Runbook court

- Vérifier les runs : `qa-driveco-data/logs/pipeline.log`.
- Vérifier le rapport local : `qa-driveco-data/YYYY-MM-DD_daily_report.md`.
- Vérifier Obsidian : `Driveco QA/Daily/YYYY-MM-DD — Driveco QA Daily.md`.
- En cas de source vide : contrôler D1 / call-history, puis fallback Aircall direct.
- En cas de publication Slack vide : vérifier que `ALLOW_EMPTY_DAILY_REPORT=false` est actif.
- Après correction de formatter : republier Notion / Obsidian / Slack pour la date concernée.

