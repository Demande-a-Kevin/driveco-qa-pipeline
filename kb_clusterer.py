"""kb_clusterer.py — clustering des kb_gaps via embeddings Ollama nomic-embed-text.

Cycle :
1. Fetch kb_gaps WHERE status != 'closed'
2. Pour chaque gap sans embedding ou topic changé → Ollama embedding
3. Hierarchical clustering scipy single-link cosine, threshold 0.15
4. Upsert kb_gap_clusters (DELETE 'new' rows + INSERT — préserve in_progress/closed)
"""
from __future__ import annotations
import hashlib
import logging
from typing import Any

import numpy as np
import requests
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

import persistence
import config

logger = logging.getLogger(__name__)

OLLAMA_EMBED_MODEL = "nomic-embed-text"
DISTANCE_THRESHOLD = 0.15


def _topic_hash(topic: str) -> str:
    return hashlib.sha256((topic or "").encode("utf-8")).hexdigest()


def _embed_topic(topic: str) -> list[float]:
    base_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
    url = f"{base_url.rstrip('/')}/api/embeddings"
    r = requests.post(
        url,
        json={"model": OLLAMA_EMBED_MODEL, "prompt": (topic or "").replace("_", " ")},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def _parse_pgvector(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [float(x) for x in value]
    if isinstance(value, str):
        try:
            return [float(x.strip()) for x in value.strip("[]").split(",") if x.strip()]
        except Exception:
            return None
    return None


def _compute_embeddings(open_gaps: list[dict[str, Any]]) -> dict[int, list[float]]:
    sb = persistence.client()
    if sb is None:
        return {}
    existing = sb.table("kb_gap_embeddings").select("kb_gap_id, topic_hash, embedding").execute()
    existing_by_id = {row["kb_gap_id"]: row for row in (existing.data or [])}

    embeddings: dict[int, list[float]] = {}
    to_persist: list[dict] = []
    for gap in open_gaps:
        gid = gap["id"]
        topic = gap.get("topic") or ""
        t_hash = _topic_hash(topic)
        cached = existing_by_id.get(gid)
        cached_emb = _parse_pgvector(cached.get("embedding")) if cached else None
        if cached and cached.get("topic_hash") == t_hash and cached_emb:
            embeddings[gid] = cached_emb
            continue
        try:
            emb = _embed_topic(topic)
            if not isinstance(emb, list) or len(emb) != 768:
                logger.warning("Invalid embedding shape for gap %s", gid)
                continue
            embeddings[gid] = emb
            to_persist.append({"kb_gap_id": gid, "embedding": emb, "topic_hash": t_hash})
        except Exception as exc:
            logger.warning("Embed failed for gap %s: %s", gid, exc)

    for row in to_persist:
        try:
            sb.table("kb_gap_embeddings").upsert(row, on_conflict="kb_gap_id").execute()
        except Exception as exc:
            logger.warning("Persist embedding failed gap %s: %s", row["kb_gap_id"], exc)

    return embeddings


def _cluster_gaps(open_gaps: list[dict], embeddings: dict[int, list[float]]) -> list[list[int]]:
    valid_gaps = [g for g in open_gaps if g["id"] in embeddings]
    if not valid_gaps:
        return []
    if len(valid_gaps) == 1:
        return [[valid_gaps[0]["id"]]]
    ids = [g["id"] for g in valid_gaps]
    X = np.array([embeddings[gid] for gid in ids])
    dists = pdist(X, metric="cosine")
    Z = linkage(dists, method="single")
    labels = fcluster(Z, t=DISTANCE_THRESHOLD, criterion="distance")
    clusters_map: dict[int, list[int]] = {}
    for gid, lab in zip(ids, labels):
        clusters_map.setdefault(int(lab), []).append(int(gid))
    return list(clusters_map.values())


def _build_cluster_rows(open_gaps: list[dict], clusters: list[list[int]]) -> list[dict]:
    gaps_by_id = {g["id"]: g for g in open_gaps}
    rows = []
    for member_ids in clusters:
        members = [gaps_by_id[gid] for gid in member_ids if gid in gaps_by_id]
        if not members:
            continue
        rep = max(members, key=lambda g: (g.get("frequency") or 0))
        total_freq = sum((g.get("frequency") or 0) for g in members)
        rows.append({
            "label": rep["topic"],
            "member_gap_ids": [g["id"] for g in members],
            "total_frequency": total_freq,
            "representative_gap_id": rep["id"],
            "status": "new",
        })
    rows.sort(key=lambda r: r["total_frequency"], reverse=True)
    return rows


def run_clustering() -> dict[str, int | str]:
    sb = persistence.client()
    if sb is None:
        return {"status": "skipped_no_supabase"}
    r = sb.table("kb_gaps").select("id, topic, frequency, status").neq("status", "closed").execute()
    open_gaps = r.data or []
    logger.info("kb_clusterer: %d open gaps", len(open_gaps))
    if not open_gaps:
        sb.table("kb_gap_clusters").delete().eq("status", "new").execute()
        return {"open_gaps": 0, "embeddings_computed": 0, "clusters_created": 0}
    embeddings = _compute_embeddings(open_gaps)
    logger.info("kb_clusterer: %d embeddings", len(embeddings))
    clusters = _cluster_gaps(open_gaps, embeddings)
    logger.info("kb_clusterer: %d clusters", len(clusters))
    new_rows = _build_cluster_rows(open_gaps, clusters)
    sb.table("kb_gap_clusters").delete().eq("status", "new").execute()
    for row in new_rows:
        try:
            sb.table("kb_gap_clusters").insert(row).execute()
        except Exception as exc:
            logger.warning("Insert cluster failed (%s): %s", row["label"], exc)
    return {"open_gaps": len(open_gaps), "embeddings_computed": len(embeddings), "clusters_created": len(new_rows)}
