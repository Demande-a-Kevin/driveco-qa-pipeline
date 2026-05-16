# Obsidian Vault Restructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolider le vault Obsidian fragmenté en une structure unifiée `00/10/20/30`, reconfigurer le pipeline QA pour pointer sur les nouveaux chemins, et créer les fichiers d'orientation humain + LLM.

**Architecture:** Migration pure filesystem (mv/mkdir/rm) + création de 3 fichiers de navigation (HOME, AI-INDEX, templates) + mise à jour de 3 variables `.env`. Aucun changement de code Python requis — `notifier.py` utilise `OBSIDIAN_REPORTS_SUBDIR` qui est configurable.

**Tech Stack:** bash, Python (pipeline QA), Obsidian Markdown

---

## Fichiers impactés

| Action | Chemin |
|--------|--------|
| Créer | `/Users/kev1n/Documents/Obsidian/🏠 HOME.md` |
| Créer | `/Users/kev1n/Documents/Obsidian/AI-INDEX.md` |
| Créer | `/Users/kev1n/Documents/Obsidian/00 - Système/Templates/template-meeting.md` |
| Créer | `/Users/kev1n/Documents/Obsidian/00 - Système/Templates/template-projet.md` |
| Créer | `/Users/kev1n/Documents/Obsidian/00 - Système/Templates/template-perso.md` |
| Créer | `/Users/kev1n/Documents/Obsidian/10 - Pro/Driveco QA/Pipeline.md` |
| Créer | Index stubs (×7) |
| Déplacer | Daily reports (×40+) → `10 - Pro/Driveco QA/Daily/` |
| Déplacer | Weekly reports (×3) → `10 - Pro/Driveco QA/Weekly/` |
| Déplacer | KB articles (×80) → `10 - Pro/Driveco QA/KB/` |
| Déplacer | Thèmes VoC (×5) → `10 - Pro/Driveco QA/Thèmes/` |
| Déplacer | Meetings → `10 - Pro/Meetings/` |
| Déplacer | Cockpit → `10 - Pro/Kev1n Cockpit/` |
| Déplacer | Archives → `00 - Système/Archives/` |
| Modifier | `.env` (source repo + runtime) |
| Supprimer | `Kev1n/`, `Pro - Driveco/`, `Meetings/`, `Perso/` (après migration) |

---

## Task 1 — Créer la structure de dossiers

**Files:**
- Créer : toute l'arborescence cible

- [ ] **Créer tous les dossiers de la structure cible**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
mkdir -p "$VAULT/00 - Système/Templates"
mkdir -p "$VAULT/00 - Système/Archives/Driveco QA"
mkdir -p "$VAULT/10 - Pro/Driveco QA/Daily"
mkdir -p "$VAULT/10 - Pro/Driveco QA/Weekly"
mkdir -p "$VAULT/10 - Pro/Driveco QA/KB"
mkdir -p "$VAULT/10 - Pro/Driveco QA/Thèmes"
mkdir -p "$VAULT/10 - Pro/Kev1n Cockpit/Journal"
mkdir -p "$VAULT/10 - Pro/Meetings/UCC x Driveco"
mkdir -p "$VAULT/10 - Pro/Meetings/Weekly Maui"
mkdir -p "$VAULT/10 - Pro/Meetings/Weekly Care"
mkdir -p "$VAULT/10 - Pro/Meetings/Weekly Mickaël F"
mkdir -p "$VAULT/10 - Pro/Meetings/Weekly Yoann"
mkdir -p "$VAULT/10 - Pro/RH"
mkdir -p "$VAULT/10 - Pro/Projets"
mkdir -p "$VAULT/20 - Perso/Maison"
mkdir -p "$VAULT/20 - Perso/Famille"
mkdir -p "$VAULT/20 - Perso/Voyages"
mkdir -p "$VAULT/20 - Perso/Apprentissage"
mkdir -p "$VAULT/30 - Ressources"
```

- [ ] **Vérifier**

```bash
find "/Users/kev1n/Documents/Obsidian" -type d | grep -E "^/Users/kev1n/Documents/Obsidian/(00|10|20|30)" | sort
```

Attendu : 20+ dossiers listés.

- [ ] **Commit**

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
git add docs/
git commit -m "docs: plan restructuration vault Obsidian"
```

---

## Task 2 — Créer HOME.md

**Files:**
- Créer : `/Users/kev1n/Documents/Obsidian/🏠 HOME.md`

- [ ] **Créer le fichier**

```bash
cat > "/Users/kev1n/Documents/Obsidian/🏠 HOME.md" << 'EOF'
---
type: home
area: systeme
tags: [index, navigation]
updated: 2026-05-16
---

# 🏠 Kev1n — Home

Vault personnel et professionnel. Point d'entrée unique pour humains et agents IA.
Pour les agents IA : lire [[AI-INDEX]] en premier.

---

## 🗂️ Navigation

| Zone | Description | Index |
|------|-------------|-------|
| [[10 - Pro/Driveco QA/Pipeline\|🤖 Driveco QA]] | Pipeline QA automatisé — rapports, KB, VoC | [[10 - Pro/Driveco QA/Pipeline]] |
| [[10 - Pro/Meetings/🗺️ INDEX-Meetings\|📅 Réunions]] | Comptes rendus par interlocuteur | [[10 - Pro/Meetings/🗺️ INDEX-Meetings]] |
| [[10 - Pro/Kev1n Cockpit/README\|🛠️ Kev1n Cockpit]] | Dashboard & infra personnelle | [[10 - Pro/Kev1n Cockpit/README]] |
| [[10 - Pro/RH/🗺️ INDEX-RH\|👥 RH]] | Sujets ressources humaines | [[10 - Pro/RH/🗺️ INDEX-RH]] |
| [[10 - Pro/Projets/🗺️ INDEX-Projets\|📦 Projets Pro]] | Autres projets professionnels | [[10 - Pro/Projets/🗺️ INDEX-Projets]] |
| [[20 - Perso/Maison/🗺️ INDEX-Maison\|🏡 Maison]] | Achat immobilier | [[20 - Perso/Maison/🗺️ INDEX-Maison]] |
| [[20 - Perso/Famille/🗺️ INDEX-Famille\|👨‍👩‍👧 Famille]] | Vie familiale | [[20 - Perso/Famille/🗺️ INDEX-Famille]] |
| [[20 - Perso/Voyages/🗺️ INDEX-Voyages\|✈️ Voyages]] | Projets de voyage | [[20 - Perso/Voyages/🗺️ INDEX-Voyages]] |
| [[20 - Perso/Apprentissage/🗺️ INDEX-Apprentissage\|📚 Apprentissage]] | Connaissances & formation | [[20 - Perso/Apprentissage/🗺️ INDEX-Apprentissage]] |
| [[30 - Ressources/🗺️ INDEX-Ressources\|📖 Ressources]] | Références, veille, lectures | [[30 - Ressources/🗺️ INDEX-Ressources]] |

---

## 🚀 Projets actifs

- **Pipeline QA Driveco** — analyse automatique des appels Aircall, rapports daily/weekly → [[10 - Pro/Driveco QA/Pipeline]]
- **Kev1n Cockpit** — dashboard Supabase/Metabase, infra Cloudflare → [[10 - Pro/Kev1n Cockpit/README]]

---

## 📊 Derniers rapports QA

> Les rapports sont auto-générés chaque matin à 02:30 par le pipeline.
> Dossier complet : `10 - Pro/Driveco QA/Daily/`

---

## 🧭 Conventions vault

- `00 - Système` : templates, archives, méta
- `10 - Pro` : tout le professionnel
- `20 - Perso` : vie personnelle
- `30 - Ressources` : références transversales
- KB QA (`10 - Pro/Driveco QA/KB/`) : **lecture seule**, miroir Notion, géré par le pipeline
EOF
```

- [ ] **Vérifier**

```bash
head -5 "/Users/kev1n/Documents/Obsidian/🏠 HOME.md"
```

Attendu : frontmatter YAML visible.

---

## Task 3 — Créer AI-INDEX.md

**Files:**
- Créer : `/Users/kev1n/Documents/Obsidian/AI-INDEX.md`

- [ ] **Créer le fichier**

```bash
cat > "/Users/kev1n/Documents/Obsidian/AI-INDEX.md" << 'EOF'
---
type: ai-index
area: systeme
tags: [llm, navigation, index]
updated: 2026-05-16
---

# AI-INDEX — Vault Kev1n

> Fichier machine-readable pour agents IA et LLMs. Lire en premier avant toute navigation.

---

## Structure du vault

```
/Documents/Obsidian/
  🏠 HOME.md              ← hub navigation principal
  AI-INDEX.md             ← ce fichier
  00 - Système/           ← templates, archives, méta-vault
  10 - Pro/               ← tout le professionnel
    Driveco QA/           ← pipeline QA automatisé Driveco/UCC
      Pipeline.md         ← documentation technique du pipeline
      Daily/              ← rapports quotidiens (auto-générés par pipeline)
      Weekly/             ← rapports hebdo (auto-générés par pipeline)
      KB/                 ← base de connaissances (miroir Notion — LECTURE SEULE)
      Thèmes/             ← notes VoC par thème (éditable)
    Kev1n Cockpit/        ← infra dashboard perso (Supabase, Cloudflare, Metabase)
    Meetings/             ← tous les comptes rendus de réunion
    RH/                   ← sujets ressources humaines
    Projets/              ← autres projets professionnels
  20 - Perso/             ← vie personnelle
    Maison/               ← projet achat immobilier
    Famille/              ← vie familiale
    Voyages/              ← projets de voyage
    Apprentissage/        ← connaissances, formation, veille
  30 - Ressources/        ← références transversales, lectures
```

---

## Où trouver quoi

| Besoin | Chemin |
|--------|--------|
| Procédures support Driveco | `10 - Pro/Driveco QA/KB/NNN-*.md` |
| Rapport QA d'un jour précis | `10 - Pro/Driveco QA/Daily/YYYY-MM-DD — Driveco QA Daily.md` |
| Rapport hebdo QA | `10 - Pro/Driveco QA/Weekly/YYYY-MM-DD — Driveco QA Weekly.md` |
| Documentation pipeline | `10 - Pro/Driveco QA/Pipeline.md` |
| Tendances VoC par thème | `10 - Pro/Driveco QA/Thèmes/` |
| Réunion UCC x Driveco | `10 - Pro/Meetings/UCC x Driveco/` |
| Réunion équipe Care | `10 - Pro/Meetings/Weekly Care/` |
| Infra & secrets cockpit | `10 - Pro/Kev1n Cockpit/` |
| Templates de notes | `00 - Système/Templates/` |

---

## Conventions frontmatter

```yaml
---
type: home | ai-index | template | qa-daily | qa-weekly | qa-theme | meeting | project-note | cockpit | perso | resource | index
area: systeme | pro | perso | ressources
project: driveco-qa | cockpit | meetings | rh | maison | famille | voyages | apprentissage | transversal
date: YYYY-MM-DD
tags: []
---
```

---

## Règles d'édition

| Zone | Éditable ? | Raison |
|------|-----------|--------|
| `10 - Pro/Driveco QA/KB/` | ❌ NON | Miroir Notion — éditer sur Notion, le pipeline resynchronise |
| `10 - Pro/Driveco QA/Daily/` | ⚠️ Lecture seule | Auto-généré par pipeline à 02:30 chaque matin |
| `10 - Pro/Driveco QA/Weekly/` | ⚠️ Lecture seule | Auto-généré par pipeline chaque lundi à 07:15 |
| `10 - Pro/Driveco QA/Thèmes/` | ✅ OUI | Notes VoC manuelles |
| `10 - Pro/Driveco QA/Pipeline.md` | ✅ OUI | Documentation pipeline |
| Tout le reste | ✅ OUI | Contenu manuel |

---

## Pipeline QA — informations clés

- **Fréquence** : daily à 02:30, weekly lundi 07:15
- **Source appels** : Worker Cloudflare → Aircall API
- **Modèle LLM** : Gemma 4 via Ollama local
- **Sorties** : Slack (1 post) + Markdown local + Notion + Obsidian
- **Repo GitHub** : https://github.com/Demande-a-Kevin/driveco-qa-pipeline
- **Runtime** : `~/Library/Application Support/driveco-qa-pipeline/runtime`
- **Logs** : `~/Library/Application Support/driveco-qa-pipeline/runtime/qa-driveco-data/logs/`

---

## Nommage des fichiers

- Daily QA : `YYYY-MM-DD — Driveco QA Daily.md`
- Weekly QA : `YYYY-MM-DD — Driveco QA Weekly.md`
- Réunions : `YYYY-MM-DD - [Participants] - [Sujet].md`
- KB articles : `NNN-slug-court.md` (numérotés, source Notion)
- Thèmes VoC : `[Emoji] Nom du thème.md`
- Index : `🗺️ INDEX-[Zone].md`
EOF
```

- [ ] **Vérifier**

```bash
wc -l "/Users/kev1n/Documents/Obsidian/AI-INDEX.md"
```

Attendu : 100+ lignes.

---

## Task 4 — Créer les templates

**Files:**
- Créer : `00 - Système/Templates/template-meeting.md`
- Créer : `00 - Système/Templates/template-projet.md`
- Créer : `00 - Système/Templates/template-perso.md`

- [ ] **template-meeting.md**

```bash
cat > "/Users/kev1n/Documents/Obsidian/00 - Système/Templates/template-meeting.md" << 'EOF'
---
type: meeting
area: pro
project: meetings
date: YYYY-MM-DD
participants: []
tags: []
---

# YYYY-MM-DD - [Participants] - [Sujet]

## Contexte
<!-- Pourquoi cette réunion -->

## Participants
- 

## Points abordés
- 

## Décisions prises
- 

## Actions
- [ ] [Qui] [Quoi] — deadline : YYYY-MM-DD

## Notes libres

EOF
```

- [ ] **template-projet.md**

```bash
cat > "/Users/kev1n/Documents/Obsidian/00 - Système/Templates/template-projet.md" << 'EOF'
---
type: project-note
area: pro
project: 
date: YYYY-MM-DD
status: en-cours | en-attente | terminé | abandonné
tags: []
---

# [Nom du projet]

## Objectif
<!-- Une phrase -->

## Contexte
<!-- Pourquoi ce projet existe -->

## État actuel
**Statut :** en-cours

## Prochaines étapes
- [ ] 

## Historique
### YYYY-MM-DD
- 

## Ressources & liens
- 
EOF
```

- [ ] **template-perso.md**

```bash
cat > "/Users/kev1n/Documents/Obsidian/00 - Système/Templates/template-perso.md" << 'EOF'
---
type: perso
area: perso
project: 
date: YYYY-MM-DD
tags: []
---

# [Titre]

## Notes

## Actions
- [ ] 

## Liens utiles
- 
EOF
```

- [ ] **Vérifier**

```bash
ls "/Users/kev1n/Documents/Obsidian/00 - Système/Templates/"
```

Attendu : 3 fichiers.

---

## Task 5 — Créer les index stubs

**Files:**
- Créer : 7 fichiers `🗺️ INDEX-*.md`

- [ ] **Créer tous les index**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"

for zone in \
  "10 - Pro/Meetings/🗺️ INDEX-Meetings" \
  "10 - Pro/RH/🗺️ INDEX-RH" \
  "10 - Pro/Projets/🗺️ INDEX-Projets" \
  "20 - Perso/Maison/🗺️ INDEX-Maison" \
  "20 - Perso/Famille/🗺️ INDEX-Famille" \
  "20 - Perso/Voyages/🗺️ INDEX-Voyages" \
  "20 - Perso/Apprentissage/🗺️ INDEX-Apprentissage" \
  "30 - Ressources/🗺️ INDEX-Ressources"; do
  
  name=$(basename "$zone" | sed 's/🗺️ INDEX-//')
  cat > "$VAULT/$zone.md" << STUB
---
type: index
area: $(echo "$zone" | grep -q "Perso" && echo "perso" || echo "pro")
tags: [index]
updated: 2026-05-16
---

# 🗺️ $name

## Contenu

*À compléter.*
STUB
done
```

- [ ] **Vérifier**

```bash
find "/Users/kev1n/Documents/Obsidian" -name "🗺️ INDEX-*.md" | sort
```

Attendu : 8 fichiers listés.

---

## Task 6 — Migrer les Daily reports

**Files:**
- Déplacer : `Pro - Driveco/Driveco x UCC QA/Daily/*.md` → `10 - Pro/Driveco QA/Daily/`
- Déplacer : `Kev1n/Driveco QA/Daily/*.md` → `10 - Pro/Driveco QA/Daily/`

- [ ] **Déplacer depuis Pro - Driveco (avr 8 → mai 6)**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
SRC="$VAULT/Pro - Driveco/Driveco x UCC QA/Daily"
DEST="$VAULT/10 - Pro/Driveco QA/Daily"
for f in "$SRC"/*.md; do
  [ -f "$f" ] && mv "$f" "$DEST/"
done
echo "Migré depuis Pro - Driveco : $(ls "$DEST" | wc -l) fichiers"
```

- [ ] **Déplacer depuis Kev1n (mai 7 → 14 + plus récents)**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
SRC="$VAULT/Kev1n/Driveco QA/Daily"
DEST="$VAULT/10 - Pro/Driveco QA/Daily"
for f in "$SRC"/*.md; do
  name=$(basename "$f")
  if [ ! -f "$DEST/$name" ]; then
    mv "$f" "$DEST/"
  else
    echo "Doublon ignoré : $name"
  fi
done
echo "Total daily : $(ls "$DEST" | wc -l) fichiers"
```

- [ ] **Vérifier**

```bash
ls "/Users/kev1n/Documents/Obsidian/10 - Pro/Driveco QA/Daily/" | sort | head -5
ls "/Users/kev1n/Documents/Obsidian/10 - Pro/Driveco QA/Daily/" | sort | tail -5
ls "/Users/kev1n/Documents/Obsidian/10 - Pro/Driveco QA/Daily/" | wc -l
```

Attendu : fichiers du 2026-04-08 au dernier disponible, 40+ fichiers.

---

## Task 7 — Migrer Weekly, KB, Thèmes, archives Kev1n

**Files:**
- Déplacer : Weekly (×3), KB (×80), Thèmes (×5), archives Kev1n

- [ ] **Weekly reports**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
DEST="$VAULT/10 - Pro/Driveco QA/Weekly"
for src in \
  "$VAULT/Pro - Driveco/Driveco x UCC QA/Weekly" \
  "$VAULT/Kev1n/Driveco QA/Weekly"; do
  [ -d "$src" ] && for f in "$src"/*.md; do
    name=$(basename "$f")
    [ -f "$f" ] && ([ ! -f "$DEST/$name" ] && mv "$f" "$DEST/" || echo "Doublon : $name")
  done
done
ls "$DEST"
```

- [ ] **KB articles (source : Kev1n — 80 articles, la plus complète)**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
mv "$VAULT/Kev1n/Driveco QA/KB/"* "$VAULT/10 - Pro/Driveco QA/KB/"
echo "KB migrés : $(ls "$VAULT/10 - Pro/Driveco QA/KB/" | wc -l) articles"
```

- [ ] **Thèmes VoC**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
mv "$VAULT/Pro - Driveco/Driveco x UCC QA/Thèmes/"*.md "$VAULT/10 - Pro/Driveco QA/Thèmes/"
ls "$VAULT/10 - Pro/Driveco QA/Thèmes/"
```

- [ ] **Archives Kev1n**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
[ -d "$VAULT/Kev1n/Driveco QA/archives" ] && \
  mv "$VAULT/Kev1n/Driveco QA/archives" "$VAULT/00 - Système/Archives/Driveco QA"
```

- [ ] **Vérifier KB**

```bash
ls "/Users/kev1n/Documents/Obsidian/10 - Pro/Driveco QA/KB/" | wc -l
```

Attendu : 80.

---

## Task 8 — Migrer Meetings et Cockpit

**Files:**
- Déplacer : réunions de `Pro - Driveco/Driveco Meetings/` et `Meetings/` → `10 - Pro/Meetings/`
- Déplacer : `Pro - Driveco/Kev1n Cockpit/` → `10 - Pro/Kev1n Cockpit/`

- [ ] **Réunions depuis Pro - Driveco**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
SRC="$VAULT/Pro - Driveco/Driveco Meetings"
DEST="$VAULT/10 - Pro/Meetings"

# INDEX-Meetings existant
[ -f "$SRC/🗺️ INDEX-Meetings.md" ] && mv "$SRC/🗺️ INDEX-Meetings.md" "$DEST/"

# Sous-dossiers réunions
for subdir in "Meeting UCC" "Weekly Maui" "Weekly Care" "Weekly Mickaël F" "Weekly Yoann"; do
  [ -d "$SRC/$subdir" ] && mv "$SRC/$subdir/"* "$DEST/$subdir/" 2>/dev/null || true
done
```

- [ ] **4 réunions isolées depuis Meetings/**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
SRC="$VAULT/Meetings"
# Classer par contenu du nom
for f in "$SRC"/*.md; do
  name=$(basename "$f")
  if echo "$name" | grep -qi "UCC\|Weekly Call"; then
    mv "$f" "$VAULT/10 - Pro/Meetings/UCC x Driveco/"
  elif echo "$name" | grep -qi "Maui\|Antoine"; then
    mv "$f" "$VAULT/10 - Pro/Meetings/Weekly Maui/"
  elif echo "$name" | grep -qi "1-1\|Mic F"; then
    mv "$f" "$VAULT/10 - Pro/Meetings/Weekly Mickaël F/"
  else
    mv "$f" "$VAULT/10 - Pro/Meetings/"
  fi
done
```

- [ ] **Cockpit**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
SRC="$VAULT/Pro - Driveco/Kev1n Cockpit"
DEST="$VAULT/10 - Pro/Kev1n Cockpit"
cp -r "$SRC/." "$DEST/"
```

- [ ] **Vérifier**

```bash
echo "=== Meetings ===" && ls "/Users/kev1n/Documents/Obsidian/10 - Pro/Meetings/"
echo "=== Cockpit ===" && ls "/Users/kev1n/Documents/Obsidian/10 - Pro/Kev1n Cockpit/"
```

---

## Task 9 — Créer Pipeline.md

**Files:**
- Créer : `10 - Pro/Driveco QA/Pipeline.md` (depuis `Kev1n/Driveco QA/Automatisation QA Pipeline.md`)

- [ ] **Déplacer et enrichir**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
SRC="$VAULT/Kev1n/Driveco QA/Automatisation QA Pipeline.md"
DEST="$VAULT/10 - Pro/Driveco QA/Pipeline.md"

# Ajouter frontmatter propre en tête, conserver le contenu existant
{
cat << 'FRONT'
---
type: project-note
area: pro
project: driveco-qa
date: 2026-05-16
tags: [pipeline, qa, automatisation, driveco]
---

FRONT
cat "$SRC"
} > "$DEST"
echo "Pipeline.md créé : $(wc -l < "$DEST") lignes"
```

- [ ] **Ajouter liens wiki en bas du fichier**

```bash
cat >> "/Users/kev1n/Documents/Obsidian/10 - Pro/Driveco QA/Pipeline.md" << 'EOF'

---

## Liens

- [[🏠 HOME]]
- [[AI-INDEX]]
- KB : `10 - Pro/Driveco QA/KB/`
- Rapports : `10 - Pro/Driveco QA/Daily/` · `10 - Pro/Driveco QA/Weekly/`
- Repo : https://github.com/Demande-a-Kevin/driveco-qa-pipeline
EOF
```

---

## Task 10 — Orphelins et nettoyage

**Files:**
- Déplacer : fichiers racine orphelins
- Supprimer : dossier Claude Code parasite

- [ ] **Orphelins à la racine**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
# Fichier date mal nommé
[ -f "$VAULT/2026-04-29.md 09-39-21-998.md" ] && \
  mv "$VAULT/2026-04-29.md 09-39-21-998.md" "$VAULT/00 - Système/Archives/"
# Sans titre.base si vide
[ -f "$VAULT/Sans titre.base" ] && rm "$VAULT/Sans titre.base"
# Orphelin Pro - Driveco racine
[ -f "$VAULT/Pro - Driveco/2026-04-29.md" ] && \
  mv "$VAULT/Pro - Driveco/2026-04-29.md" "$VAULT/10 - Pro/Driveco QA/Daily/2026-04-29 — Driveco QA Daily.md" 2>/dev/null || true
```

- [ ] **Supprimer dossier Claude Code parasite**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
# Pro - Driveco/Kev1n contient .claude/skills — supprimer
rm -rf "$VAULT/Pro - Driveco/Kev1n"
```

- [ ] **Supprimer KB doublon (Pro - Driveco)**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
# Les articles KB de Pro - Driveco sont un sous-ensemble de Kev1n/KB déjà migré
# Vérifier qu'il ne reste rien d'unique
diff_count=$(diff <(ls "$VAULT/10 - Pro/Driveco QA/KB/" | sort) \
                  <(ls "$VAULT/Pro - Driveco/Driveco x UCC QA/KB/" 2>/dev/null | sort) \
             | grep "^>" | wc -l)
echo "Articles uniques dans Pro-Driveco/KB non encore migrés : $diff_count"
# Si 0, supprimer
[ "$diff_count" -eq 0 ] && rm -rf "$VAULT/Pro - Driveco/Driveco x UCC QA/KB" || echo "⚠️ Migrer les $diff_count manquants avant de supprimer"
```

---

## Task 11 — Supprimer les anciennes zones

**Files:**
- Supprimer : `Kev1n/`, `Pro - Driveco/`, `Meetings/`, `Perso/` (après vérification vide)

- [ ] **Vérifier que les anciennes zones sont vides avant suppression**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
echo "=== Fichiers restants dans Kev1n/ ==="
find "$VAULT/Kev1n" -name "*.md" 2>/dev/null
echo "=== Fichiers restants dans Pro - Driveco/ ==="
find "$VAULT/Pro - Driveco" -name "*.md" 2>/dev/null | grep -v "\.claude"
echo "=== Fichiers restants dans Meetings/ ==="
find "$VAULT/Meetings" -name "*.md" 2>/dev/null
```

- [ ] **Supprimer si vides**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
# Supprimer uniquement si aucun .md restant
for zone in "Kev1n" "Pro - Driveco" "Meetings" "Perso"; do
  count=$(find "$VAULT/$zone" -name "*.md" 2>/dev/null | grep -v "\.claude" | wc -l)
  if [ "$count" -eq 0 ]; then
    rm -rf "$VAULT/$zone"
    echo "✅ Supprimé : $zone/"
  else
    echo "⚠️ $zone/ contient encore $count fichier(s) .md — vérifier manuellement"
  fi
done
```

- [ ] **Vérifier structure finale**

```bash
find "/Users/kev1n/Documents/Obsidian" -type d | grep -v "\.obsidian" | sort
```

Attendu : uniquement `00 - Système/`, `10 - Pro/`, `20 - Perso/`, `30 - Ressources/` + sous-dossiers.

---

## Task 12 — Reconfigurer le pipeline QA

**Files:**
- Modifier : `/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline/.env`

- [ ] **Mettre à jour les variables Obsidian dans .env**

```bash
ENV="/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline/.env"

# OBSIDIAN_VAULT_DIR
sed -i '' 's|OBSIDIAN_VAULT_DIR=.*|OBSIDIAN_VAULT_DIR=/Users/kev1n/Documents/Obsidian|' "$ENV"

# OBSIDIAN_REPORTS_SUBDIR (nouvelle variable)
if grep -q "OBSIDIAN_REPORTS_SUBDIR" "$ENV"; then
  sed -i '' 's|OBSIDIAN_REPORTS_SUBDIR=.*|OBSIDIAN_REPORTS_SUBDIR=10 - Pro/Driveco QA|' "$ENV"
else
  echo "OBSIDIAN_REPORTS_SUBDIR=10 - Pro/Driveco QA" >> "$ENV"
fi

# OBSIDIAN_KB_SUBDIR
sed -i '' 's|OBSIDIAN_KB_SUBDIR=.*|OBSIDIAN_KB_SUBDIR=10 - Pro/Driveco QA/KB|' "$ENV"
```

- [ ] **Vérifier les 3 variables**

```bash
grep "OBSIDIAN_VAULT_DIR\|OBSIDIAN_REPORTS_SUBDIR\|OBSIDIAN_KB_SUBDIR" \
  "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline/.env"
```

Attendu :
```
OBSIDIAN_VAULT_DIR=/Users/kev1n/Documents/Obsidian
OBSIDIAN_REPORTS_SUBDIR=10 - Pro/Driveco QA
OBSIDIAN_KB_SUBDIR=10 - Pro/Driveco QA/KB
```

- [ ] **Vérifier que config.py lit bien OBSIDIAN_REPORTS_SUBDIR**

```bash
grep "OBSIDIAN_REPORTS_SUBDIR" "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline/config.py"
```

Attendu : `OBSIDIAN_REPORTS_SUBDIR = os.getenv("OBSIDIAN_REPORTS_SUBDIR", "Driveco QA")...`
→ La variable est déjà lue par config.py. Aucun changement de code requis.

- [ ] **Resynchroniser le runtime**

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
bash sync_launchd_runtime.sh && bash setup_launchd.sh
```

Attendu : `Runtime launchd synchronisé`.

---

## Task 13 — Valider le pipeline

- [ ] **Test de connectivité**

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
.venv/bin/python analysis_pipeline.py --mode test
```

Attendu : `✅ Connectivité OK` sans erreur sur le chemin Obsidian.

- [ ] **Vérifier que la KB Obsidian se charge correctement**

```bash
cd "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
import config
from obsidian_kb_fetcher import load_kb_from_obsidian
pages = load_kb_from_obsidian(config.OBSIDIAN_VAULT_DIR, config.OBSIDIAN_KB_SUBDIR)
print(f'KB chargée : {len(pages)} articles depuis {config.OBSIDIAN_VAULT_DIR}/{config.OBSIDIAN_KB_SUBDIR}')
" 2>/dev/null || echo "Module obsidian_kb_fetcher absent du runtime — vérifier après resync"
```

Attendu : `KB chargée : 80 articles depuis /Users/kev1n/Documents/Obsidian/10 - Pro/Driveco QA/KB`

- [ ] **Vérifier le chemin de sortie daily (simulation)**

```bash
cd "/Users/kev1n/Library/Application Support/driveco-qa-pipeline/runtime"
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
import config
from pathlib import Path
vault = Path(config.OBSIDIAN_VAULT_DIR)
subdir = config.OBSIDIAN_REPORTS_SUBDIR
target = vault / subdir / 'Daily'
print(f'Sortie daily → {target}')
print(f'Dossier existe : {target.exists()}')
"
```

Attendu : `Sortie daily → /Users/kev1n/Documents/Obsidian/10 - Pro/Driveco QA/Daily` + `Dossier existe : True`

- [ ] **Tests unitaires**

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
.venv/bin/python -m pytest -x --tb=short
```

Attendu : 41 passed.

- [ ] **Commit**

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
git add .env
git commit -m "config: reconfiguration Obsidian vault — nouveau chemin unifié

OBSIDIAN_VAULT_DIR=/Users/kev1n/Documents/Obsidian
OBSIDIAN_REPORTS_SUBDIR=10 - Pro/Driveco QA
OBSIDIAN_KB_SUBDIR=10 - Pro/Driveco QA/KB

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 14 — Liens wiki dans les notes clés

**Files:**
- Modifier : `10 - Pro/Driveco QA/Thèmes/*.md` (ajouter liens KB)
- Modifier : `10 - Pro/Kev1n Cockpit/README.md` (ajouter lien HOME)

- [ ] **Ajouter lien HOME dans les Thèmes VoC**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
for f in "$VAULT/10 - Pro/Driveco QA/Thèmes/"*.md; do
  grep -q "HOME" "$f" || echo -e "\n---\n\n[[🏠 HOME]] · [[AI-INDEX]] · [[10 - Pro/Driveco QA/Pipeline|Pipeline QA]]" >> "$f"
done
```

- [ ] **Ajouter lien HOME dans Cockpit README**

```bash
VAULT="/Users/kev1n/Documents/Obsidian"
README="$VAULT/10 - Pro/Kev1n Cockpit/README.md"
grep -q "HOME" "$README" || echo -e "\n---\n\n[[🏠 HOME]] · [[AI-INDEX]]" >> "$README"
```

- [ ] **Vérifier la structure finale du vault**

```bash
find "/Users/kev1n/Documents/Obsidian" -name "*.md" | grep -v "\.obsidian\|\.claude" | wc -l
echo "---"
find "/Users/kev1n/Documents/Obsidian" -name "*.md" | grep -v "\.obsidian\|\.claude" | grep "HOME\|AI-INDEX\|INDEX-\|Pipeline" | sort
```

Attendu : 140+ fichiers total, les fichiers clés de navigation visibles.

- [ ] **Push GitHub**

```bash
cd "/Users/kev1n/Desktop/Kev1n IA/Codex/driveco-qa-pipeline"
git push origin codex/refonte-qa-voc-pilotage
```

---

## Critères de succès (checklist finale)

- [ ] `🏠 HOME.md` et `AI-INDEX.md` existent à la racine du vault
- [ ] `10 - Pro/Driveco QA/KB/` contient 80 articles
- [ ] `10 - Pro/Driveco QA/Daily/` contient tous les rapports (avr 8 → aujourd'hui)
- [ ] Aucun dossier `Kev1n/`, `Pro - Driveco/`, `Meetings/`, `Perso/` à la racine
- [ ] Pipeline `--mode test` passe sans erreur
- [ ] KB se charge depuis le nouveau chemin (80 articles)
- [ ] Chemin sortie daily = `10 - Pro/Driveco QA/Daily/`
- [ ] 41 tests pytest passent
- [ ] `.env` source et runtime à jour
