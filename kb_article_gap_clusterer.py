"""kb_article_gap_clusterer.py — Cluster les unanswered_questions + cross-check KB articles.

Cycle :
1. Fetch `call_unanswered_questions` sur LOOKBACK_DAYS.
2. Pour chaque question_hash unique : embedding via cache `unanswered_question_embeddings`.
3. Hierarchical clustering scipy single-link cosine, threshold 0.20.
4. Pour chaque cluster : moyenne des embeddings, max similarité cosine vs `kb_articles.embedding`.
5. Statut : exists ≥ 0.80, partial ≥ 0.55, sinon missing.
6. Upsert `kb_article_gap_clusters` : DELETE clusters sans assignee + status != 'closed', puis INSERT.
"""
from __future__ import annotations
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import requests
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

import config
import persistence
from kb_clusterer import _parse_pgvector

logger = logging.getLogger(__name__)

OLLAMA_EMBED_MODEL = "nomic-embed-text"
THRESHOLD_CLUSTER = 0.20
SIM_THRESHOLD_EXISTS = 0.80
SIM_THRESHOLD_PARTIAL = 0.55
LOOKBACK_DAYS = 30


def _question_hash(q: str) -> str:
    return hashlib.sha256((q or "").strip().lower().encode("utf-8")).hexdigest()


def _embed_question(text: str) -> list[float]:
    base_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
    url = f"{base_url.rstrip('/')}/api/embeddings"
    r = requests.post(
        url,
        json={"model": OLLAMA_EMBED_MODEL, "prompt": (text or " ")[:2000]},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def _fetch_unanswered_questions(lookback_days: int = LOOKBACK_DAYS) -> list[dict[str, Any]]:
    sb = persistence.client()
    if sb is None:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    r = (
        sb.table("call_unanswered_questions")
        .select("id, question_text, question_hash, raised_at")
        .gte("raised_at", since)
        .execute()
    )
    return r.data or []


def _compute_embeddings(questions: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Map question_hash → embedding. Reuse cache `unanswered_question_embeddings`."""
    sb = persistence.client()
    if sb is None:
        return {}
    unique_hashes = {q["question_hash"]: q for q in questions}
    if not unique_hashes:
        return {}

    existing = sb.table("unanswered_question_embeddings").select("question_hash, embedding").execute()
    cache = {row["question_hash"]: _parse_pgvector(row.get("embedding")) for row in (existing.data or [])}

    embeddings: dict[str, list[float]] = {}
    to_persist: list[dict] = []
    for h, q in unique_hashes.items():
        cached = cache.get(h)
        if cached and len(cached) == 768:
            embeddings[h] = cached
            continue
        try:
            emb = _embed_question(q["question_text"])
            if not isinstance(emb, list) or len(emb) != 768:
                logger.warning("kb_article_gap_clusterer: bad embedding shape for %s", h)
                continue
            embeddings[h] = emb
            to_persist.append({"question_hash": h, "embedding": emb})
        except Exception as exc:
            logger.warning("kb_article_gap_clusterer: embed failed hash=%s : %s", h, exc)

    for row in to_persist:
        try:
            sb.table("unanswered_question_embeddings").upsert(row, on_conflict="question_hash").execute()
        except Exception as exc:
            logger.warning("kb_article_gap_clusterer: persist embedding failed %s : %s", row["question_hash"], exc)
    return embeddings


def _cluster_questions(questions: list[dict[str, Any]], embeddings: dict[str, list[float]]) -> list[list[str]]:
    """Cluster question_hashes via single-link cosine (threshold 0.20). Returns list of hash-groups."""
    unique = {q["question_hash"]: q for q in questions if q["question_hash"] in embeddings}
    hashes = list(unique.keys())
    if not hashes:
        return []
    if len(hashes) == 1:
        return [hashes]
    X = np.array([embeddings[h] for h in hashes])
    dists = pdist(X, metric="cosine")
    Z = linkage(dists, method="single")
    labels = fcluster(Z, t=THRESHOLD_CLUSTER, criterion="distance")
    groups: dict[int, list[str]] = {}
    for h, lab in zip(hashes, labels):
        groups.setdefault(int(lab), []).append(h)
    return list(groups.values())


def _fetch_kb_embeddings() -> list[tuple[str, list[float]]]:
    sb = persistence.client()
    if sb is None:
        return []
    r = sb.table("kb_articles").select("notion_page_id, embedding").execute()
    out = []
    for row in (r.data or []):
        emb = _parse_pgvector(row.get("embedding"))
        if emb and len(emb) == 768:
            out.append((row["notion_page_id"], emb))
    return out


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _status_for_similarity(sim: float) -> str:
    if sim >= SIM_THRESHOLD_EXISTS:
        return "exists"
    if sim >= SIM_THRESHOLD_PARTIAL:
        return "partial"
    return "missing"


def _build_cluster_rows(
    clusters: list[list[str]],
    questions: list[dict[str, Any]],
    q_embeddings: dict[str, list[float]],
    kb_embeddings: list[tuple[str, list[float]]],
) -> list[dict[str, Any]]:
    # Group questions per hash for frequency + representative selection.
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for q in questions:
        by_hash.setdefault(q["question_hash"], []).append(q)

    rows: list[dict[str, Any]] = []
    kb_matrix = np.array([emb for _, emb in kb_embeddings]) if kb_embeddings else None
    kb_ids = [pid for pid, _ in kb_embeddings]

    for hashes in clusters:
        member_ids: list[int] = []
        total_freq = 0
        hash_freqs: list[tuple[str, int]] = []
        for h in hashes:
            occ = by_hash.get(h, [])
            freq = len(occ)
            total_freq += freq
            hash_freqs.append((h, freq))
            for q in occ:
                member_ids.append(int(q["id"]))
        if not member_ids:
            continue
        # Representative = first occurrence of the most frequent hash.
        rep_hash = max(hash_freqs, key=lambda x: x[1])[0]
        rep_q = by_hash[rep_hash][0]
        label = (rep_q["question_text"] or "")[:200]

        # Mean embedding across cluster hashes.
        mean_emb = np.mean(np.array([q_embeddings[h] for h in hashes]), axis=0)

        status = "missing"
        matched_article_id = None
        max_sim = 0.0
        if kb_matrix is not None and len(kb_matrix) > 0:
            sims = np.array([_cosine(mean_emb, row) for row in kb_matrix])
            best_idx = int(np.argmax(sims))
            max_sim = float(sims[best_idx])
            status = _status_for_similarity(max_sim)
            if status in ("partial", "exists"):
                matched_article_id = kb_ids[best_idx]

        rows.append({
            "label": label,
            "member_question_ids": sorted(set(member_ids)),
            "total_frequency": int(total_freq),
            "representative_question_id": int(rep_q["id"]),
            "status": status,
            "matched_article_id": matched_article_id,
            "match_similarity": round(max_sim, 3) if max_sim else None,
        })
    rows.sort(key=lambda r: r["total_frequency"], reverse=True)
    return rows


def _upsert_clusters(rows: list[dict[str, Any]]) -> None:
    """Delete clusters sans assignee + status != 'closed', puis INSERT les nouveaux."""
    sb = persistence.client()
    if sb is None:
        return
    # Supabase REST : .is_("assignee", "null") + .neq("status", "closed")
    try:
        sb.table("kb_article_gap_clusters").delete().is_("assignee", "null").neq("status", "closed").execute()
    except Exception as exc:
        logger.warning("kb_article_gap_clusterer: delete failed : %s", exc)
    for row in rows:
        try:
            sb.table("kb_article_gap_clusters").insert(row).execute()
        except Exception as exc:
            logger.warning("kb_article_gap_clusterer: insert failed (%s) : %s", row.get("label"), exc)


def run_clustering() -> dict[str, int | str]:
    sb = persistence.client()
    if sb is None:
        return {"status": "skipped_no_supabase"}
    questions = _fetch_unanswered_questions(LOOKBACK_DAYS)
    logger.info("kb_article_gap_clusterer: %d unanswered questions (lookback=%dd)", len(questions), LOOKBACK_DAYS)
    if not questions:
        try:
            sb.table("kb_article_gap_clusters").delete().is_("assignee", "null").neq("status", "closed").execute()
        except Exception:
            pass
        return {"clusters": 0, "missing": 0, "partial": 0, "exists": 0}
    embeddings = _compute_embeddings(questions)
    clusters = _cluster_questions(questions, embeddings)
    kb_emb = _fetch_kb_embeddings()
    rows = _build_cluster_rows(clusters, questions, embeddings, kb_emb)
    _upsert_clusters(rows)
    missing = sum(1 for r in rows if r["status"] == "missing")
    partial = sum(1 for r in rows if r["status"] == "partial")
    exists = sum(1 for r in rows if r["status"] == "exists")
    logger.info("kb_article_gap_clusterer: clusters=%d missing=%d partial=%d exists=%d",
                len(rows), missing, partial, exists)
    return {"clusters": len(rows), "missing": missing, "partial": partial, "exists": exists}
