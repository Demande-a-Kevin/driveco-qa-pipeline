"""kb_draft_generator.py — génération de drafts KB via Ollama Gemma.

Pour un cluster donné + format choisi (coaching / article_kb / faq) :
1. Fetch le cluster + ses kb_gaps membres + 3-5 exemples calls + transcripts résumés
2. Build le prompt template adapté au format
3. Call Ollama → markdown
4. Retourne le markdown (caller persiste dans kb_cluster_drafts)
"""
from __future__ import annotations

import logging
from typing import Any

import persistence
import ollama_client

logger = logging.getLogger(__name__)

GEMMA_MODEL = "gemma4:latest"
MAX_TRANSCRIPT_CHARS = 4000  # 3-5 transcripts truncated total budget


PROMPT_COACHING = """Tu es un manager QA expérimenté pour un centre d'appels Driveco (bornes de recharge).
Tu analyses un pattern de coaching récurrent détecté chez les agents support, et tu rédiges une fiche coaching actionnable.

# Contexte du cluster

Label : {label}
Patterns membres : {members}
Occurrences totales : {total_frequency}

# Extraits d'appels concernés

{transcripts}

# Ta tâche

Rédige une fiche coaching en français, format markdown, structure :

## Pattern observé
(1-2 phrases : ce que les agents font / ne font pas)

## Pourquoi c'est un problème
(impact client, impact business)

## Bonne pratique attendue
(3-5 étapes concrètes, applicables au prochain appel)

## Exemple de phrase / formulation
(2-3 propositions courtes, utilisables tel quel)

## Pour aller plus loin
(1-2 références internes ou ressources)

Reste concis (max 500 mots), pragmatique, orienté action.
"""

PROMPT_ARTICLE_KB = """Tu es un rédacteur de base de connaissances client pour Driveco (bornes de recharge VE).
Tu rédiges un article KB destiné aux clients/utilisateurs, à partir de cas récurrents remontés par le support.

# Cluster détecté

Label : {label}
Patterns membres : {members}
Fréquence : {total_frequency} appels

# Extraits d'appels clients

{transcripts}

# Ta tâche

Rédige un article KB en français, format markdown, structure :

## Symptôme
(comment le problème se manifeste côté client)

## Cause probable
(explication accessible, sans jargon technique excessif)

## Solution étape par étape
(numérotée, claire, testable)

## Si ça ne fonctionne pas
(quoi faire en cas d'échec — escalade, contact support, etc.)

## Liens connexes
(suggérer 2-3 articles KB liés à créer ou mentionner)

Reste concis (max 600 mots), tone amical mais pro, oriente le client vers l'autonomie.
"""

PROMPT_FAQ = """Tu rédiges une Q/R FAQ courte pour Driveco (bornes de recharge VE).

# Sujet

Cluster : {label}
Patterns : {members}
Fréquence : {total_frequency} appels

# Extraits d'appels

{transcripts}

# Ta tâche

Rédige UNE Q/R en français, format markdown, max 200 mots :

**Q : ...**

**R :** ...

Concise, directe, orientée résolution rapide.
"""


def _fetch_cluster_context(cluster_id: str) -> dict[str, Any]:
    """Fetch cluster + membres + exemples appels + transcripts."""
    sb = persistence.client()
    if sb is None:
        raise RuntimeError("Supabase indisponible")

    cluster_r = sb.table("kb_gap_clusters").select("*").eq("id", cluster_id).single().execute()
    cluster = cluster_r.data
    if not cluster:
        raise ValueError(f"Cluster {cluster_id} not found")

    member_ids = cluster.get("member_gap_ids") or []
    members: list[dict] = []
    example_call_ids: list[str] = []
    if member_ids:
        members_r = (
            sb.table("kb_gaps")
            .select("id, topic, frequency, example_call_ids")
            .in_("id", member_ids)
            .order("frequency", desc=True)
            .execute()
        )
        members = members_r.data or []
        for m in members:
            for cid in (m.get("example_call_ids") or []):
                if cid not in example_call_ids and len(example_call_ids) < 5:
                    example_call_ids.append(cid)

    transcripts: list[str] = []
    if example_call_ids:
        t_r = (
            sb.table("transcripts")
            .select("call_id, text")
            .in_("call_id", example_call_ids)
            .limit(5)
            .execute()
        )
        rows = t_r.data or []
        per_chunk = MAX_TRANSCRIPT_CHARS // max(len(rows), 1) if rows else MAX_TRANSCRIPT_CHARS
        for row in rows:
            text = (row.get("text") or "").strip()
            if text:
                snippet = text[:per_chunk]
                cid = row.get("call_id") or ""
                transcripts.append(f"--- Appel {cid[:8]} ---\n{snippet}")

    return {
        "cluster": cluster,
        "members": members,
        "transcripts": transcripts,
    }


def _build_prompt(format: str, ctx: dict[str, Any]) -> str:
    """Build le prompt selon le format."""
    cluster = ctx["cluster"]
    members = ctx["members"]
    transcripts = ctx["transcripts"]
    members_str = ", ".join(m["topic"] for m in members[:10])
    transcripts_str = "\n\n".join(transcripts) if transcripts else "(aucun transcript disponible)"

    template = {
        "coaching": PROMPT_COACHING,
        "article_kb": PROMPT_ARTICLE_KB,
        "faq": PROMPT_FAQ,
    }.get(format)
    if not template:
        raise ValueError(f"Unknown format: {format}")

    return template.format(
        label=cluster.get("label", "—"),
        members=members_str or "—",
        total_frequency=cluster.get("total_frequency", 0),
        transcripts=transcripts_str,
    )


def _call_ollama(prompt: str) -> str:
    """Call Ollama gemma4. Try internal _generate first, fallback HTTP direct."""
    # Try the internal helper (already wraps timeouts, options, etc.)
    if hasattr(ollama_client, "_generate"):
        try:
            return ollama_client._generate(GEMMA_MODEL, prompt, max_tokens=2048)
        except Exception:
            logger.exception("ollama_client._generate failed, falling back to HTTP")

    # Fallback: HTTP direct
    import requests
    import config

    base = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
    r = requests.post(
        f"{base.rstrip('/')}/api/generate",
        json={"model": GEMMA_MODEL, "prompt": prompt, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("response", "")


def generate_draft(cluster_id: str, format: str) -> str:
    """Generate a draft markdown for a cluster + format.

    Retourne le markdown produit par Ollama.
    """
    if format not in ("coaching", "article_kb", "faq"):
        raise ValueError(f"Invalid format: {format}")

    ctx = _fetch_cluster_context(cluster_id)
    prompt = _build_prompt(format, ctx)
    logger.info(
        "kb_draft: generating format=%s cluster=%s prompt_len=%d",
        format,
        cluster_id,
        len(prompt),
    )

    try:
        markdown = _call_ollama(prompt)
    except Exception:
        logger.exception("Ollama generate failed for cluster=%s format=%s", cluster_id, format)
        raise

    return (markdown or "").strip()
