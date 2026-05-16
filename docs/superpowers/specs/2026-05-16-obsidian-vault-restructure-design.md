# Design — Restructuration vault Obsidian Kev1n

**Date :** 2026-05-16  
**Statut :** approuvé, en attente d'implémentation  
**Scope :** `/Users/kev1n/Documents/Obsidian/` (vault racine)

---

## Contexte

Le vault Obsidian actuel est fragmenté en plusieurs zones parallèles sans cohérence :

- `Kev1n/` — cible actuelle du pipeline QA (KB 80 articles, Daily mai 7-14)
- `Pro - Driveco/` — zone plus riche (Daily avr 8-mai 6, Meetings, Cockpit, Thèmes VoC) mais non utilisée par le pipeline
- `Meetings/` — 4 notes isolées à la racine
- `Perso/` — vide
- Fichiers orphelins à la racine

**Objectif :** unifier en un vault structuré, navigable par humain et LLM, couvrant pro + perso, avec le pipeline QA correctement reconfiguré.

---

## Structure cible

```
/Documents/Obsidian/                         ← racine vault (inchangée)
  🏠 HOME.md                                 ← hub principal (humain + LLM)
  AI-INDEX.md                                ← index machine-readable pour agents IA

  00 - Système/
    Templates/
      template-meeting.md
      template-projet.md
      template-qa-daily.md                   ← template pour futurs rapports manuels
    Archives/                                ← anciens contenus à conserver

  10 - Pro/
    Driveco QA/
      Pipeline.md                            ← fiche technique pipeline QA (ex-Automatisation QA Pipeline.md)
      Daily/                                 ← rapports quotidiens (destination pipeline)
      Weekly/                                ← rapports hebdo (destination pipeline)
      KB/                                    ← miroir Notion en lecture seule (géré par pipeline)
      Thèmes/                                ← notes VoC par thème (5 fichiers existants)
    Kev1n Cockpit/
      README.md
      Architecture & Infrastructure.md
      🔐 Secrets (Keychain).md
      Journal/
    Meetings/
      UCC x Driveco/
      Weekly Maui/
      Weekly Care/
      Weekly Mickaël F/
      Weekly Yoann/
      🗺️ INDEX-Meetings.md                   ← index réunions existant, conservé
    RH/
      🗺️ INDEX-RH.md                         ← vide, prêt à remplir
    Projets/
      🗺️ INDEX-Projets.md                    ← vide, prêt à remplir

  20 - Perso/
    Maison/
      🗺️ INDEX-Maison.md
    Famille/
      🗺️ INDEX-Famille.md
    Voyages/
      🗺️ INDEX-Voyages.md
    Apprentissage/
      🗺️ INDEX-Apprentissage.md

  30 - Ressources/
    🗺️ INDEX-Ressources.md                   ← veille, lectures, références transversales
```

---

## Règles KB — source Notion, miroir Obsidian

- **Notion = source de vérité** pour les 80 articles KB
- Les fichiers `KB/` dans Obsidian sont **générés et mis à jour par le pipeline** à chaque run
- L'avertissement `> ⚠️ Fichier généré depuis Notion — éditer l'article sur Notion, pas ici.` est **conservé**
- Les champs frontmatter `notion_id`, `last_edited_time`, `synced_at`, `source: notion` sont **conservés**
- **Aucun lien wiki sortant** n'est ajouté manuellement dans les articles KB
- Les liens wiki dans les rapports daily/weekly **vers** les articles KB sont autorisés (lecture seule)

---

## Frontmatter unifié (hors KB)

Tous les fichiers non-KB reçoivent ce frontmatter minimal :

```yaml
---
type: home | ai-index | template | qa-daily | qa-weekly | qa-theme | meeting | project-note | cockpit | perso | resource | index
area: systeme | pro | perso | ressources
project: driveco-qa | cockpit | meetings | rh | maison | famille | voyages | apprentissage | transversal
date: YYYY-MM-DD          # pour les notes datées
tags: []
---
```

Le pipeline QA continue à générer ses propres frontmatters sur Daily/Weekly (déjà en place).

---

## Liens wiki à ajouter

### Dans les rapports Daily
- Les appels listés sous "Appels problématiques" référencent des rubriques KB → lien `[[NNN-nom-article]]`
- Exemple : si un appel cite "Charger Disconnected" → ajouter `[[010-charger-disconnected-ac-dc-assistance-process-en-fr]]`
- Lien vers le rapport Weekly de la semaine concernée (quand il existe)

### Dans Pipeline.md
- Liens vers `[[🏠 HOME]]`, `[[AI-INDEX]]`, et les derniers rapports Daily/Weekly

### Dans HOME.md
- Navigation vers toutes les zones principales
- Liens vers `Pipeline.md`, `🗺️ INDEX-Meetings`, les Thèmes VoC

### Dans AI-INDEX.md
- Carte complète de tous les dossiers
- Convention de nommage
- Où trouver quoi

---

## Migration des fichiers existants

| Source | Destination | Action |
|--------|-------------|--------|
| `Kev1n/Driveco QA/Daily/*.md` (mai 7-14) | `10 - Pro/Driveco QA/Daily/` | déplacer |
| `Pro - Driveco/Driveco x UCC QA/Daily/*.md` (avr 8-mai 6) | `10 - Pro/Driveco QA/Daily/` | déplacer |
| `Kev1n/Driveco QA/Weekly/*.md` | `10 - Pro/Driveco QA/Weekly/` | déplacer |
| `Pro - Driveco/Driveco x UCC QA/Weekly/*.md` | `10 - Pro/Driveco QA/Weekly/` | déplacer |
| `Kev1n/Driveco QA/KB/` (80 articles, source principale) | `10 - Pro/Driveco QA/KB/` | déplacer |
| `Pro - Driveco/Driveco x UCC QA/KB/` (doublon partiel) | — | supprimer après vérif doublons |
| `Kev1n/Driveco QA/Thèmes/` (si existant) | `10 - Pro/Driveco QA/Thèmes/` | déplacer |
| `Pro - Driveco/Driveco x UCC QA/Thèmes/` (5 notes VoC) | `10 - Pro/Driveco QA/Thèmes/` | déplacer |
| `Kev1n/Driveco QA/Automatisation QA Pipeline.md` | `10 - Pro/Driveco QA/Pipeline.md` | déplacer + renommer |
| `Pro - Driveco/Driveco Meetings/` (réunions + INDEX) | `10 - Pro/Meetings/` | déplacer |
| `Meetings/*.md` (4 notes isolées) | `10 - Pro/Meetings/` (sous-dossier adapté) | déplacer |
| `Pro - Driveco/Kev1n Cockpit/` | `10 - Pro/Kev1n Cockpit/` | déplacer |
| `Kev1n/Driveco QA/archives/` | `00 - Système/Archives/Driveco QA/` | déplacer |
| `Pro - Driveco/Kev1n/` (dossier Claude Code parasite) | — | supprimer |
| `Pro - Driveco/2026-04-29.md` (orphelin) | `10 - Pro/Driveco QA/Daily/` | déplacer |
| `2026-04-29.md 09-39-21-998.md` (racine) | `00 - Système/Archives/` | déplacer |
| `Sans titre.base` (racine) | — | supprimer si vide |
| `Kev1n/` (dossier vide après migration) | — | supprimer |
| `Pro - Driveco/` (dossier vide après migration) | — | supprimer |
| `Perso/` (vide) | — | remplacé par `20 - Perso/` |

---

## Reconfiguration pipeline QA

Après migration, mettre à jour `.env` (source repo + resync runtime) :

```
# Avant
OBSIDIAN_VAULT_DIR=/Users/kev1n/Documents/Obsidian/Kev1n
OBSIDIAN_KB_SUBDIR=Driveco QA/KB

# Après
OBSIDIAN_VAULT_DIR=/Users/kev1n/Documents/Obsidian
OBSIDIAN_KB_SUBDIR=10 - Pro/Driveco QA/KB
```

Mettre à jour dans `notifier.py` le chemin de publication des notes daily/weekly :
- Daily : `10 - Pro/Driveco QA/Daily/YYYY-MM-DD — Driveco QA Daily.md`
- Weekly : `10 - Pro/Driveco QA/Weekly/YYYY-MM-DD — Driveco QA Weekly.md`

Resynchroniser le runtime après modification :
```bash
bash sync_launchd_runtime.sh && bash setup_launchd.sh
```

Valider avec :
```bash
.venv/bin/python analysis_pipeline.py --mode test
```

---

## Fichiers clés à créer

### `🏠 HOME.md`
- Description du vault et de son propriétaire
- Navigation par zone (Pro / Perso / Ressources)
- Projets actifs avec lien direct
- Derniers rapports QA (liens)
- Mises à jour récentes

### `AI-INDEX.md`
- Carte complète des dossiers avec description
- Convention de nommage des fichiers
- Frontmatter types et leurs valeurs
- Où trouver : KB QA, réunions, cockpit, perso
- Règles d'édition (KB = lecture seule, reste = éditable)
- Pipeline QA : fréquence, format, chemin de sortie

### `00 - Système/Templates/`
- `template-meeting.md` : frontmatter + sections standard (participants, décisions, actions)
- `template-projet.md` : frontmatter + contexte, objectif, état, prochaines étapes
- `template-perso.md` : frontmatter + structure légère

---

## Critères de succès

1. Un agent IA qui ouvre `AI-INDEX.md` peut naviguer vers n'importe quelle zone en moins de 2 sauts
2. Le pipeline QA publie correctement dans `10 - Pro/Driveco QA/Daily/` sans erreur
3. La KB Notion est toujours correctement mirrorée dans `10 - Pro/Driveco QA/KB/`
4. `HOME.md` liste les projets actifs et les derniers rapports QA
5. Aucun doublon de Daily/Weekly entre anciennes zones
6. Les dossiers `Kev1n/`, `Pro - Driveco/`, `Meetings/`, `Perso/` n'existent plus à la racine

---

## Contraintes

- Ne pas modifier les fichiers KB directement (source Notion)
- Ne pas supprimer les archives sans vérification manuelle préalable
- Le pipeline doit rester fonctionnel pendant la migration (tester en mode test avant et après)
- `notion_reporter.py` n'est pas concerné par cette migration (publie vers Notion, pas Obsidian)
