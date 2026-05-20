"""Tests F-3 Group C — kb_articles_indexer (sync incrémental + upsert)."""
from unittest.mock import MagicMock, patch

import kb_articles_indexer


def _fake_supabase(existing_rows: list[dict]):
    sb = MagicMock()
    select_chain = MagicMock()
    select_chain.execute.return_value = MagicMock(data=existing_rows)
    sb.table.return_value.select.return_value = select_chain
    upsert_chain = MagicMock()
    upsert_chain.execute.return_value = MagicMock(data=[])
    sb.table.return_value.upsert.return_value = upsert_chain
    return sb


def test_a_incremental_skip_when_last_edited_unchanged():
    page = {
        "id": "page-123",
        "title": "Article A",
        "content": "Contenu",
        "last_edited_time": "2026-05-20T10:00:00.000Z",
    }
    sb = _fake_supabase([
        {"notion_page_id": "page-123", "last_edited_notion": "2026-05-20T10:00:00.000Z"},
    ])
    with patch.object(kb_articles_indexer.persistence, "client", return_value=sb), \
         patch.object(kb_articles_indexer.notion_kb_fetcher, "_build_page_tree", return_value=[page]), \
         patch.object(kb_articles_indexer, "_embed_body", return_value=[0.0] * 768):
        result = kb_articles_indexer.run_indexing()
    assert result["synced"] == 0
    assert result["skipped"] == 1
    assert result["total"] == 1
    sb.table.return_value.upsert.assert_not_called()


def test_b_upsert_recomputes_embedding_when_modified():
    page = {
        "id": "page-456",
        "title": "Article B",
        "content": "Nouveau contenu",
        "last_edited_time": "2026-05-20T12:00:00.000Z",
    }
    sb = _fake_supabase([
        {"notion_page_id": "page-456", "last_edited_notion": "2026-05-01T08:00:00.000Z"},
    ])
    fake_emb = [0.1] * 768
    with patch.object(kb_articles_indexer.persistence, "client", return_value=sb), \
         patch.object(kb_articles_indexer.notion_kb_fetcher, "_build_page_tree", return_value=[page]), \
         patch.object(kb_articles_indexer, "_embed_body", return_value=fake_emb):
        result = kb_articles_indexer.run_indexing()
    assert result["synced"] == 1
    assert result["skipped"] == 0
    sb.table.return_value.upsert.assert_called_once()
    upsert_arg = sb.table.return_value.upsert.call_args[0][0]
    assert upsert_arg["notion_page_id"] == "page-456"
    assert upsert_arg["embedding"] == fake_emb
    assert upsert_arg["last_edited_notion"] == "2026-05-20T12:00:00.000Z"
