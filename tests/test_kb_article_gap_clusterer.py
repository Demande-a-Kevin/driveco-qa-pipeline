"""Tests F-3 Group C — kb_article_gap_clusterer (clustering + cross-check KB + preserve assignee)."""
from unittest.mock import MagicMock, patch

import numpy as np

import kb_article_gap_clusterer as gap


def _q(qid: int, text: str, h: str) -> dict:
    return {"id": qid, "question_text": text, "question_hash": h, "raised_at": "2026-05-15T10:00:00Z"}


def test_a_clusters_similar_questions_into_one_group():
    # 5 distinct questions (5 hashes) with very similar embeddings → 1 cluster.
    questions = [_q(i, f"Q{i}", f"h{i}") for i in range(1, 6)]
    base = np.zeros(768)
    base[0] = 1.0
    embeddings = {f"h{i}": (base + np.random.normal(0, 0.001, 768)).tolist() for i in range(1, 6)}
    clusters = gap._cluster_questions(questions, embeddings)
    assert len(clusters) == 1
    assert sorted(clusters[0]) == [f"h{i}" for i in range(1, 6)]


def test_b_cross_check_status_thresholds():
    # Build 3 clusters with controlled mean embeddings: exists / partial / missing
    e_unit = np.zeros(768); e_unit[0] = 1.0  # baseline article direction
    kb_emb = [("article-1", e_unit.tolist())]

    # Cluster 1 : direction quasi identique → cosine ≈ 1.0 (exists, ≥0.80)
    q1 = [_q(1, "exists q", "he")]
    emb1 = {"he": e_unit.tolist()}

    # Cluster 2 : direction à ~0.65 → partial
    v2 = np.zeros(768)
    v2[0] = 0.65
    v2[1] = np.sqrt(1 - 0.65 ** 2)
    q2 = [_q(2, "partial q", "hp")]
    emb2 = {"hp": v2.tolist()}

    # Cluster 3 : direction à ~0.30 → missing
    v3 = np.zeros(768)
    v3[0] = 0.30
    v3[1] = np.sqrt(1 - 0.30 ** 2)
    q3 = [_q(3, "missing q", "hm")]
    emb3 = {"hm": v3.tolist()}

    rows_exists = gap._build_cluster_rows([["he"]], q1, emb1, kb_emb)
    rows_partial = gap._build_cluster_rows([["hp"]], q2, emb2, kb_emb)
    rows_missing = gap._build_cluster_rows([["hm"]], q3, emb3, kb_emb)

    assert rows_exists[0]["status"] == "exists"
    assert rows_exists[0]["matched_article_id"] == "article-1"
    assert rows_partial[0]["status"] == "partial"
    assert rows_partial[0]["matched_article_id"] == "article-1"
    assert rows_missing[0]["status"] == "missing"
    assert rows_missing[0]["matched_article_id"] is None


def test_c_upsert_preserves_clusters_with_assignee():
    """_upsert_clusters doit DELETE seulement assignee IS NULL AND status != 'closed'."""
    sb = MagicMock()
    # Track filter chain on delete.
    delete_chain = MagicMock()
    is_chain = MagicMock()
    neq_chain = MagicMock()
    is_chain.neq.return_value = neq_chain
    delete_chain.is_.return_value = is_chain
    sb.table.return_value.delete.return_value = delete_chain
    sb.table.return_value.insert.return_value = MagicMock(execute=MagicMock(return_value=MagicMock(data=[])))

    with patch.object(gap.persistence, "client", return_value=sb):
        gap._upsert_clusters([
            {"label": "L", "member_question_ids": [1], "total_frequency": 1,
             "representative_question_id": 1, "status": "missing",
             "matched_article_id": None, "match_similarity": None}
        ])

    # Verify filters applied: .is_("assignee","null") then .neq("status","closed")
    delete_chain.is_.assert_called_once_with("assignee", "null")
    is_chain.neq.assert_called_once_with("status", "closed")
    neq_chain.execute.assert_called_once()
    sb.table.return_value.insert.assert_called_once()
