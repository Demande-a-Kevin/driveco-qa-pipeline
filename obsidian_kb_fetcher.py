"""obsidian_kb_fetcher.py — drop-in replacement de notion_kb_fetcher.

Lit la KB depuis `<vault>/<OBSIDIAN_KB_SUBDIR>/*.md` produits par
`notion_kb_sync.sync()`. Même API que `notion_kb_fetcher` :
    - get_kb_summary_for_prompt(include_content)
    - build_relevant_kb_excerpt(calls, max_chars, max_pages)
    - fetch_article_content(page_id)
    - fetch_kb_index(force_refresh)
    - _load_cache() (pour la compat run_reliability)

Aucun appel réseau, lecture filesystem + cache mémoire par mtime.
"""
from __future__ import annotations

import logging
from pathlib import Path

import config
import notion_kb_fetcher  # réutilise _extract_keywords, _score_page_for_keywords, _render_kb_summary, etc.

log = logging.getLogger(__name__)

_MEM: dict = {}


def _kb_dir() -> Path:
    return Path(config.OBSIDIAN_VAULT_DIR) / config.OBSIDIAN_KB_SUBDIR


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    body = text[end + 5:]
    return fm, body


def _load_pages() -> list[dict]:
    """Retourne la liste des pages au même format que notion_kb_fetcher._build_page_tree."""
    kb_dir = _kb_dir()
    if not kb_dir.exists():
        return []

    # Cache invalidation via somme des mtimes (rapide et précis)
    files = sorted(kb_dir.glob("*.md"))
    signature = tuple((f.name, f.stat().st_mtime_ns) for f in files)
    if _MEM.get("signature") == signature:
        return _MEM.get("pages") or []

    pages: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = _parse_frontmatter(text)
        notion_id = fm.get("notion_id") or f.stem
        title = fm.get("title") or f.stem
        path_str = fm.get("path") or title
        path = [p.strip() for p in path_str.split(">") if p.strip()]
        # Retire l'avertissement d'édition et le H1 pour ne garder que le contenu utile.
        content = body
        if content.startswith("# "):
            content = content.split("\n", 1)[1] if "\n" in content else ""
        content = content.replace(
            "> ⚠️ Fichier généré depuis Notion — éditer l'article sur Notion, pas ici.\n",
            "",
        ).strip()
        pages.append({
            "id": notion_id,
            "title": title,
            "path": path,
            "last_edited_time": fm.get("last_edited_time"),
            "content": content,
        })

    _MEM["signature"] = signature
    _MEM["pages"] = pages
    return pages


def _payload() -> dict:
    pages = _load_pages()
    return {
        "ts": 0,
        "page_id": config.NOTION_KB_PAGE_ID,
        "signature": None,
        "pages": pages,
        "summary_full": notion_kb_fetcher._render_kb_summary(pages, include_content=True),   # type: ignore[attr-defined]
        "summary_titles": notion_kb_fetcher._render_kb_summary(pages, include_content=False),  # type: ignore[attr-defined]
    }


# ---------- API publique (miroir de notion_kb_fetcher) ----------

def get_kb_summary_for_prompt(include_content: bool = True, max_articles: int | None = None,
                              max_chars_per_article: int | None = None) -> str:
    payload = _payload()
    if include_content:
        return payload["summary_full"] or "Knowledge Base Obsidian : aucun article trouvé."
    return payload["summary_titles"] or "Knowledge Base Obsidian : aucun article trouvé."


def build_relevant_kb_excerpt(calls: list[dict], max_chars: int = 12000, max_pages: int = 8) -> str:
    pages = _load_pages()
    if not pages:
        return "Knowledge Base Obsidian : aucun article trouvé."

    query_text = "\n".join(notion_kb_fetcher._extract_call_query_text(c) for c in calls if c)  # type: ignore[attr-defined]
    keywords = notion_kb_fetcher._extract_keywords(query_text)  # type: ignore[attr-defined]
    if not keywords:
        return get_kb_summary_for_prompt(include_content=False)

    scored = []
    for idx, page in enumerate(pages):
        score, matched = notion_kb_fetcher._score_page_for_keywords(page, keywords)  # type: ignore[attr-defined]
        if score <= 0:
            continue
        scored.append((score, idx, page, matched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = scored[:max_pages]
    if not selected:
        return get_kb_summary_for_prompt(include_content=False)

    lines = [
        "=== Knowledge Base Driveco Care (extrait ciblé) ===",
        f"Pages KB retenues : {len(selected)}/{len(pages)}",
        f"Mots-clés batch : {', '.join(keywords[:20])}",
        "",
    ]
    current_chars = len("\n".join(lines))
    for index, (score, _, page, matched) in enumerate(selected):
        path = " > ".join(page.get("path") or [page.get("title") or "Sans titre"])
        content = (page.get("content") or "").strip()
        remaining = max_chars - current_chars
        if remaining <= 200:
            break
        remaining_pages = max(1, len(selected) - index)
        budget = max(500, min(2200, int((remaining - 120) / remaining_pages)))
        snippet = content[:budget].strip()
        lines.append(f"## {path}")
        lines.append(f"score={score} | matches={', '.join(matched[:12])}")
        lines.append(snippet if snippet else "[aucun contenu textuel]")
        lines.append("")
        current_chars = len("\n".join(lines))
        if current_chars >= max_chars:
            break
    return "\n".join(lines).strip()


def fetch_article_content(page_id: str, max_blocks: int | None = None) -> str:
    for p in _load_pages():
        if p.get("id") == page_id:
            return p.get("content", "")
    return ""


def fetch_kb_index(force_refresh: bool = False) -> list[dict]:
    if force_refresh:
        _MEM.clear()
    pages = _load_pages()
    out = []
    for idx, p in enumerate(pages):
        out.append({
            "id": p.get("id"),
            "title": p.get("title"),
            "type": "root_page" if idx == 0 else "child_page",
            "path": p.get("path", []),
            "last_edited_time": p.get("last_edited_time"),
        })
    return out


def _load_cache() -> dict | None:
    """Compat : run_reliability lit cached_payload puis tombe back sur get_kb_summary_for_prompt."""
    pages = _load_pages()
    if not pages:
        return None
    return _payload()
