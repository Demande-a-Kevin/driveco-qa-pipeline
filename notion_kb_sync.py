"""notion_kb_sync.py — miroir Notion KB → fichiers Markdown Obsidian.

Notion = source de vérité (édition). Obsidian = index local consommé par la
pipeline QA (lecture uniquement). Ce module :
- descend l'arbre de la page racine `config.NOTION_KB_PAGE_ID`
- écrit un `.md` par page sous `<vault>/<OBSIDIAN_KB_SUBDIR>/`
- ne réécrit que les pages dont `last_edited_time` a changé
- supprime les fichiers dont le `notion_id` n'est plus présent dans Notion

Frontmatter YAML inséré dans chaque fichier :
    notion_id, title, path, last_edited_time, synced_at, tags

Le fichier commence par un avertissement "édition via Notion" pour éviter les
modifications accidentelles dans Obsidian.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import config
import notion_kb_fetcher  # réutilise _build_page_tree et helpers

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EDIT_WARNING = "> ⚠️ Fichier généré depuis Notion — éditer l'article sur Notion, pas ici.\n\n"


def _slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = _SLUG_RE.sub("-", text).strip("-")
    return text or "sans-titre"


def _kb_dir() -> Path:
    vault = Path(config.OBSIDIAN_VAULT_DIR)
    target = vault / config.OBSIDIAN_KB_SUBDIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def _parse_frontmatter(text: str) -> dict:
    """Extrait le frontmatter YAML minimal (clé: valeur) sans dépendre de pyyaml."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    fm = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm


def _render_markdown(page: dict) -> str:
    path = " > ".join(page.get("path") or [page.get("title") or "Sans titre"])
    title = page.get("title") or "Sans titre"
    last_edited = page.get("last_edited_time") or ""
    notion_id = page.get("id") or ""
    content = (page.get("content") or "").strip() or "[aucun contenu textuel]"
    synced_at = datetime.now(timezone.utc).isoformat()

    fm = (
        "---\n"
        f"notion_id: {notion_id}\n"
        f"title: {title}\n"
        f"path: {path}\n"
        f"last_edited_time: {last_edited}\n"
        f"synced_at: {synced_at}\n"
        "tags: [driveco, kb, qa]\n"
        "source: notion\n"
        "---\n\n"
    )
    body = f"# {title}\n\n{_EDIT_WARNING}{content}\n"
    return fm + body


def _filename_for(page: dict, index: int) -> str:
    slug = _slugify(page.get("title") or "sans-titre")
    # index évite les collisions de titres homonymes
    return f"{index:03d}-{slug}.md"


def sync(force: bool = False) -> dict:
    """Synchronise la KB Notion vers le vault Obsidian.

    Retourne un résumé `{created, updated, skipped, deleted, total_notion}`.
    """
    if not config.NOTION_API_KEY or not config.NOTION_KB_PAGE_ID:
        log.warning("[kb-sync] NOTION_API_KEY ou NOTION_KB_PAGE_ID absent — sync ignorée.")
        return {"created": 0, "updated": 0, "skipped": 0, "deleted": 0, "total_notion": 0}

    kb_dir = _kb_dir()
    log.info(f"[kb-sync] Lecture arbre Notion depuis page {config.NOTION_KB_PAGE_ID[:8]}…")
    try:
        pages = notion_kb_fetcher._build_page_tree(config.NOTION_KB_PAGE_ID)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        log.error(f"[kb-sync] échec lecture Notion : {exc}")
        return {"created": 0, "updated": 0, "skipped": 0, "deleted": 0, "total_notion": 0}

    existing_by_id: dict[str, Path] = {}
    for f in kb_dir.glob("*.md"):
        try:
            fm = _parse_frontmatter(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        nid = fm.get("notion_id")
        if nid:
            existing_by_id[nid] = f

    created = updated = skipped = 0
    current_ids: set[str] = set()

    for idx, page in enumerate(pages):
        nid = page.get("id")
        if not nid:
            continue
        current_ids.add(nid)
        target_name = _filename_for(page, idx)
        target_path = kb_dir / target_name

        existing = existing_by_id.get(nid)
        if existing and existing.name != target_name:
            # renommage (titre Notion a changé)
            try:
                existing.unlink()
            except Exception:
                pass
            existing = None

        if existing and not force:
            fm = _parse_frontmatter(existing.read_text(encoding="utf-8"))
            if fm.get("last_edited_time") == (page.get("last_edited_time") or ""):
                skipped += 1
                continue

        target_path.write_text(_render_markdown(page), encoding="utf-8")
        if existing:
            updated += 1
        else:
            created += 1

    deleted = 0
    for nid, path in existing_by_id.items():
        if nid not in current_ids:
            try:
                path.unlink()
                deleted += 1
            except Exception as exc:  # noqa: BLE001
                log.warning(f"[kb-sync] suppression {path.name} impossible : {exc}")

    summary = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "deleted": deleted,
        "total_notion": len(pages),
    }
    log.info(
        f"[kb-sync] {len(pages)} page(s) Notion — "
        f"créées={created} maj={updated} inchangées={skipped} supprimées={deleted}"
    )
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = sync(force=False)
    print(result)
