"""kb_articles_indexer.py — Indexe les pages KB Notion dans `kb_articles` avec embeddings.

Cycle :
1. Récupère l'arbre Notion via `notion_kb_fetcher._build_page_tree`.
2. Pour chaque page, compare `last_edited_time` au `last_edited_notion` en base.
3. Si nouveau / modifié : calcule embedding nomic-embed-text sur le contenu (truncate 4000 chars).
4. Upsert `kb_articles` (PK notion_page_id).
"""
from __future__ import annotations
import logging

import config
import notion_kb_fetcher
import persistence
from kb_clusterer import _embed_topic  # reuse F-1 embedding helper (Ollama nomic-embed-text)

log = logging.getLogger(__name__)


def _page_url(notion_page_id: str) -> str:
    # Notion canonical URL pattern : https://www.notion.so/<id-without-dashes>
    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"


def _should_index(existing_last_edited: str | None, page_last_edited: str | None) -> bool:
    if not existing_last_edited:
        return True
    if not page_last_edited:
        return False
    return page_last_edited > existing_last_edited


def _embed_body(body_md: str) -> list[float]:
    text = (body_md or " ")[:4000]
    return _embed_topic(text)


def run_indexing() -> dict:
    sb = persistence.client()
    if sb is None:
        log.warning("kb_articles_indexer: Supabase indisponible, skip.")
        return {"status": "skipped_no_supabase", "synced": 0, "skipped": 0, "total": 0}

    pages = notion_kb_fetcher._build_page_tree(config.NOTION_KB_PAGE_ID)
    log.info("kb_articles_indexer: %d pages Notion à traiter", len(pages))

    existing = sb.table("kb_articles").select("notion_page_id, last_edited_notion").execute()
    existing_map = {r["notion_page_id"]: r.get("last_edited_notion") for r in (existing.data or [])}

    synced = 0
    skipped = 0
    failed = 0
    for p in pages:
        notion_id = p.get("id")
        if not notion_id:
            continue
        page_last_edited = p.get("last_edited_time")
        if not _should_index(existing_map.get(notion_id), page_last_edited):
            skipped += 1
            continue
        title = p.get("title") or "Sans titre"
        body = p.get("content") or ""
        try:
            emb = _embed_body(body)
            if not isinstance(emb, list) or len(emb) != 768:
                log.warning("kb_articles_indexer: embedding invalide pour %s", notion_id)
                failed += 1
                continue
        except Exception as exc:
            log.warning("kb_articles_indexer: embed failed page=%s : %s", notion_id, exc)
            failed += 1
            continue
        row = {
            "notion_page_id": notion_id,
            "title": title,
            "body_md": body,
            "url": _page_url(notion_id),
            "embedding": emb,
            "last_edited_notion": page_last_edited,
        }
        try:
            sb.table("kb_articles").upsert(row, on_conflict="notion_page_id").execute()
            synced += 1
        except Exception as exc:
            log.warning("kb_articles_indexer: upsert failed page=%s : %s", notion_id, exc)
            failed += 1

    log.info("kb_articles_indexer: synced=%d skipped=%d failed=%d total=%d",
             synced, skipped, failed, len(pages))
    return {"synced": synced, "skipped": skipped, "failed": failed, "total": len(pages)}
