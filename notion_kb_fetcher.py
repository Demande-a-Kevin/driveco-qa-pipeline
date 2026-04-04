"""
notion_kb_fetcher.py — Récupère la KB Notion complète pour le QA.

Objectif :
- prendre uniquement la page racine Notion configurée et ses vraies sous-pages
- ne rien injecter en dur
- garder un cache local complet
- ne reconstruire le corpus que si la KB a changé, sinon au plus une fois par semaine
"""
import hashlib
import json
import logging
import re
import time

import requests

import config

log = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {config.NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
}

_MEM_CACHE: dict = {}
_STOP_WORDS = {
    "a", "ai", "alors", "apres", "au", "aux", "avec", "car", "ce", "cet", "cette",
    "comme", "dans", "de", "des", "du", "elle", "en", "est", "et", "etre", "il",
    "je", "la", "le", "les", "leur", "ma", "mais", "me", "mes", "mon", "ne",
    "nos", "notre", "nous", "on", "ou", "par", "pas", "pour", "qu", "que", "qui",
    "sa", "se", "ses", "si", "son", "sur", "ta", "te", "tes", "toi", "ton", "tu",
    "un", "une", "vos", "votre", "vous", "y",
}


def _get(url: str, timeout: int = 20) -> dict | None:
    """GET Notion API — retourne le JSON ou None si erreur."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        log.warning(f"[notion] GET {url} -> {resp.status_code}")
    except Exception as exc:
        log.warning(f"[notion] GET {url} -> exception : {exc}")
    return None


def _get_page(page_id: str) -> dict | None:
    return _get(f"https://api.notion.com/v1/pages/{page_id}")


def _list_block_children(block_id: str) -> list[dict]:
    items = []
    next_cursor = None
    while True:
        url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
        if next_cursor:
            url += f"&start_cursor={next_cursor}"
        data = _get(url)
        if not data:
            break
        items.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            break
    return items


def _text_from_rich_text(rich_text: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def _extract_page_title(page: dict | None, fallback: str | None = None) -> str:
    if not page:
        return fallback or "Sans titre"
    props = page.get("properties") or {}
    for value in props.values():
        if isinstance(value, dict) and value.get("type") == "title":
            title = _text_from_rich_text(value.get("title", [])).strip()
            if title:
                return title
    return fallback or "Sans titre"


def _extract_block_text(block: dict, depth: int = 0) -> str:
    btype = block.get("type", "")
    content = block.get(btype, {})
    indent = "  " * depth
    text_types = (
        "paragraph", "heading_1", "heading_2", "heading_3",
        "bulleted_list_item", "numbered_list_item", "toggle",
        "quote", "callout", "to_do",
    )
    if btype in text_types:
        raw = _text_from_rich_text(content.get("rich_text", [])).strip()
        if not raw:
            return ""
        prefix = ""
        if btype == "heading_1":
            prefix = "# "
        elif btype == "heading_2":
            prefix = "## "
        elif btype == "heading_3":
            prefix = "### "
        elif btype == "bulleted_list_item":
            prefix = f"{indent}- "
        elif btype == "numbered_list_item":
            prefix = f"{indent}• "
        elif btype == "to_do":
            checked = content.get("checked", False)
            prefix = f"{indent}[{'x' if checked else ' '}] "
        elif btype == "quote":
            prefix = f"{indent}> "
        return f"{prefix}{raw}"
    if btype == "code":
        raw = _text_from_rich_text(content.get("rich_text", [])).strip()
        if not raw:
            return ""
        lang = content.get("language", "")
        return f"```{lang}\n{raw}\n```"
    if btype == "divider":
        return "---"
    return ""


def _walk_block_tree(block_id: str, seen_blocks: set[str] | None = None, depth: int = 0) -> tuple[list[str], list[dict]]:
    if seen_blocks is None:
        seen_blocks = set()
    if block_id in seen_blocks:
        return [], []
    seen_blocks.add(block_id)

    lines = []
    child_pages = []
    for block in _list_block_children(block_id):
        block_id_value = block.get("id")
        btype = block.get("type")

        if btype == "child_page":
            child_pages.append({
                "id": block_id_value,
                "title": block.get("child_page", {}).get("title", "Sans titre"),
            })
            continue

        text = _extract_block_text(block, depth=depth)
        if text:
            lines.append(text)

        if block.get("has_children") and block_id_value:
            child_lines, nested_pages = _walk_block_tree(block_id_value, seen_blocks, depth + 1)
            lines.extend(child_lines)
            child_pages.extend(nested_pages)

    return lines, child_pages


def _collect_child_pages(block_id: str, seen_blocks: set[str] | None = None) -> list[dict]:
    if seen_blocks is None:
        seen_blocks = set()
    if block_id in seen_blocks:
        return []
    seen_blocks.add(block_id)

    child_pages = []
    for block in _list_block_children(block_id):
        block_id_value = block.get("id")
        btype = block.get("type")
        if btype == "child_page":
            child_pages.append({
                "id": block_id_value,
                "title": block.get("child_page", {}).get("title", "Sans titre"),
            })
            continue
        if block.get("has_children") and block_id_value:
            child_pages.extend(_collect_child_pages(block_id_value, seen_blocks))
    return child_pages


def _build_page_tree(page_id: str, title_hint: str | None = None, path: list[str] | None = None,
                     seen_pages: set[str] | None = None) -> list[dict]:
    if seen_pages is None:
        seen_pages = set()
    if path is None:
        path = []
    if page_id in seen_pages:
        return []
    seen_pages.add(page_id)

    page = _get_page(page_id)
    title = _extract_page_title(page, fallback=title_hint)
    page_path = [*path, title]
    lines, child_pages = _walk_block_tree(page_id, seen_blocks=set(), depth=0)
    content = "\n".join(line for line in lines if line and line.strip()).strip()
    nodes = [{
        "id": page_id,
        "title": title,
        "path": page_path,
        "last_edited_time": page.get("last_edited_time") if page else None,
        "content": content,
    }]

    for child in child_pages:
        child_id = child.get("id")
        if not child_id:
            continue
        nodes.extend(_build_page_tree(child_id, title_hint=child.get("title"), path=page_path, seen_pages=seen_pages))
    return nodes


def _build_page_signature_tree(page_id: str, title_hint: str | None = None, path: list[str] | None = None,
                               seen_pages: set[str] | None = None) -> list[dict]:
    if seen_pages is None:
        seen_pages = set()
    if path is None:
        path = []
    if page_id in seen_pages:
        return []
    seen_pages.add(page_id)

    page = _get_page(page_id)
    title = _extract_page_title(page, fallback=title_hint)
    page_path = [*path, title]
    nodes = [{
        "id": page_id,
        "title": title,
        "path": page_path,
        "last_edited_time": page.get("last_edited_time") if page else None,
    }]

    for child in _collect_child_pages(page_id, seen_blocks=set()):
        child_id = child.get("id")
        if not child_id:
            continue
        nodes.extend(
            _build_page_signature_tree(
                child_id,
                title_hint=child.get("title"),
                path=page_path,
                seen_pages=seen_pages,
            )
        )
    return nodes


def _compute_signature(pages: list[dict]) -> str:
    material = [
        {
            "id": page.get("id"),
            "title": page.get("title"),
            "path": page.get("path"),
            "last_edited_time": page.get("last_edited_time"),
        }
        for page in pages
    ]
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _render_kb_summary(pages: list[dict], include_content: bool = True) -> str:
    if not pages:
        return "Knowledge Base Notion : non accessible (vérifier NOTION_API_KEY)"

    root = pages[0]
    lines = [
        "=== Knowledge Base Driveco Care ===",
        "Source : page racine Notion configurée + sous-pages réelles uniquement",
        f"Page racine : {root.get('title', 'Sans titre')}",
        f"Pages incluses : {len(pages)}",
        "",
    ]

    if not include_content:
        lines.append("Arborescence incluse :")
        for page in pages:
            lines.append(f"- {' > '.join(page.get('path') or [page.get('title', 'Sans titre')])}")
        return "\n".join(lines).strip()

    lines.append("Contenu complet :")
    for page in pages:
        lines.append("")
        lines.append(f"## {' > '.join(page.get('path') or [page.get('title', 'Sans titre')])}")
        content = (page.get("content") or "").strip()
        lines.append(content if content else "[aucun contenu textuel]")

    return "\n".join(lines).strip()


def _normalize_token(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿœæ]+", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _extract_keywords(text: str) -> list[str]:
    normalized = _normalize_token(text)
    if not normalized:
        return []
    tokens = []
    seen = set()
    for token in normalized.split():
        if len(token) < 3 or token in _STOP_WORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _build_page_text(page: dict) -> str:
    path = " > ".join(page.get("path") or [page.get("title") or "Sans titre"])
    content = page.get("content") or ""
    return f"{path}\n{content}".strip()


def _extract_call_query_text(call: dict) -> str:
    parts = [
        call.get("classified_type"),
        call.get("ivr_branch"),
        call.get("tags"),
        call.get("missed_call_reason"),
        call.get("user_name"),
        (call.get("transcript") or "")[:1200],
    ]
    return "\n".join(str(part).strip() for part in parts if part)


def _score_page_for_keywords(page: dict, keywords: list[str]) -> tuple[int, list[str]]:
    if not keywords:
        return 0, []
    title_tokens = set(_extract_keywords(page.get("title") or ""))
    path_tokens = set(_extract_keywords(" ".join(page.get("path") or [])))
    content_tokens = set(_extract_keywords(page.get("content") or ""))
    matched = []
    score = 0
    for keyword in keywords:
        matched_here = False
        if keyword in title_tokens:
            score += 6
            matched_here = True
        if keyword in path_tokens:
            score += 4
            matched_here = True
        if keyword in content_tokens:
            score += 2
            matched_here = True
        if matched_here:
            matched.append(keyword)
    return score, matched


def build_relevant_kb_excerpt(calls: list[dict], max_chars: int = 12000, max_pages: int = 8) -> str:
    """
    Sélectionne un extrait pertinent de la KB à partir des appels du batch.
    On conserve la KB complète en cache, mais on n'injecte qu'un sous-ensemble ciblé.
    """
    payload = _get_kb_payload()
    pages = payload.get("pages", [])
    if not pages:
        return "Knowledge Base Notion : non accessible (vérifier NOTION_API_KEY)"

    query_text = "\n".join(_extract_call_query_text(call) for call in calls if call)
    keywords = _extract_keywords(query_text)
    if not keywords:
        return get_kb_summary_for_prompt(include_content=False)

    scored_pages = []
    for idx, page in enumerate(pages):
        score, matched = _score_page_for_keywords(page, keywords)
        if score <= 0:
            continue
        scored_pages.append((score, idx, page, matched))
    scored_pages.sort(key=lambda item: (-item[0], item[1]))

    selected = scored_pages[:max_pages]
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
        content = _build_page_text(page)
        remaining = max_chars - current_chars
        if remaining <= 200:
            break
        remaining_pages = max(1, len(selected) - index)
        # Répartit le budget pour éviter qu'une seule page géante prenne toute la place.
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


def _load_cache() -> dict | None:
    cache_path = config.NOTION_CACHE_PATH
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        if "pages" in raw and "summary_full" in raw and "summary_titles" in raw:
            return raw
        # Ancien format : {"ts": ..., "articles": [...]}
        if "articles" in raw:
            return {
                "ts": float(raw.get("ts", 0) or 0),
                "page_id": config.NOTION_KB_PAGE_ID,
                "signature": None,
                "pages": [],
                "summary_full": "Knowledge Base Notion : cache ancien format, reconstruction requise",
                "summary_titles": "Knowledge Base Notion : cache ancien format, reconstruction requise",
            }
        return None
    except Exception:
        return None


def _write_cache(payload: dict) -> None:
    config.NOTION_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_payload() -> dict:
    pages = _build_page_tree(config.NOTION_KB_PAGE_ID)
    signature = _compute_signature(pages)
    return {
        "ts": time.time(),
        "page_id": config.NOTION_KB_PAGE_ID,
        "signature": signature,
        "pages": pages,
        "summary_full": _render_kb_summary(pages, include_content=True),
        "summary_titles": _render_kb_summary(pages, include_content=False),
    }


def _get_kb_payload(force_refresh: bool = False) -> dict:
    mem_key = f"kb_payload:{config.NOTION_KB_PAGE_ID}"
    cache_ttl = int(config.NOTION_CACHE_TTL or 604800)
    if not force_refresh and mem_key in _MEM_CACHE:
        return _MEM_CACHE[mem_key]

    cached = _load_cache()
    now = time.time()
    if (
        not force_refresh and cached
        and cached.get("page_id") == config.NOTION_KB_PAGE_ID
        and now - float(cached.get("ts", 0)) < cache_ttl
    ):
        _MEM_CACHE[mem_key] = cached
        return cached

    if not config.NOTION_API_KEY or not config.NOTION_KB_PAGE_ID:
        fallback = cached or {
            "ts": now,
            "page_id": config.NOTION_KB_PAGE_ID,
            "signature": None,
            "pages": [],
            "summary_full": "Knowledge Base Notion : non accessible (vérifier NOTION_API_KEY)",
            "summary_titles": "Knowledge Base Notion : non accessible (vérifier NOTION_API_KEY)",
        }
        _MEM_CACHE[mem_key] = fallback
        return fallback

    try:
        if cached and cached.get("signature"):
            signature_pages = _build_page_signature_tree(config.NOTION_KB_PAGE_ID)
            signature = _compute_signature(signature_pages)
            if cached.get("signature") == signature:
                cached["ts"] = now
                _write_cache(cached)
                _MEM_CACHE[mem_key] = cached
                return cached

        rebuilt = _build_payload()
        _write_cache(rebuilt)
        _MEM_CACHE[mem_key] = rebuilt
        return rebuilt
    except Exception as exc:
        log.warning(f"[notion] rebuild KB impossible -> {exc}")
        fallback = cached or {
            "ts": now,
            "page_id": config.NOTION_KB_PAGE_ID,
            "signature": None,
            "pages": [],
            "summary_full": "Knowledge Base Notion : non accessible (vérifier NOTION_API_KEY)",
            "summary_titles": "Knowledge Base Notion : non accessible (vérifier NOTION_API_KEY)",
        }
        _MEM_CACHE[mem_key] = fallback
        return fallback


def fetch_article_content(page_id: str, max_blocks: int | None = None) -> str:
    """
    Retourne le contenu complet d'une page présente dans le cache KB.
    max_blocks est gardé pour compatibilité mais n'est plus utilisé.
    """
    payload = _get_kb_payload()
    for page in payload.get("pages", []):
        if page.get("id") == page_id:
            return page.get("content", "")
    return ""


def fetch_kb_index(force_refresh: bool = False) -> list[dict]:
    """
    Retourne l'index complet de la KB :
    page racine + vraies sous-pages Notion détectées dans l'arborescence.
    """
    payload = _get_kb_payload(force_refresh=force_refresh)
    pages = payload.get("pages", [])
    out = []
    for idx, page in enumerate(pages):
        out.append({
            "id": page.get("id"),
            "title": page.get("title"),
            "type": "root_page" if idx == 0 else "child_page",
            "path": page.get("path", []),
            "last_edited_time": page.get("last_edited_time"),
        })
    return out


def get_kb_summary_for_prompt(include_content: bool = True, max_articles: int | None = None,
                              max_chars_per_article: int | None = None) -> str:
    """
    Retourne le corpus KB injecté dans les prompts.
    max_articles et max_chars_per_article sont conservés pour compatibilité,
    mais la version par défaut n'est plus tronquée.
    """
    payload = _get_kb_payload()
    if include_content:
        return payload.get("summary_full") or "Knowledge Base Notion : non accessible (vérifier NOTION_API_KEY)"
    return payload.get("summary_titles") or "Knowledge Base Notion : non accessible (vérifier NOTION_API_KEY)"
