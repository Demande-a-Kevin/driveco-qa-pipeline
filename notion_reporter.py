"""
notion_reporter.py — Publie les rapports QA comme sous-pages Notion.
Page cible : Analytics — Qualité Assistance Téléphonique (NOTION_REPORTS_PAGE_ID).

Convertit le Markdown généré par report_formatter en blocks Notion valides.
Un rapport = une sous-page avec le titre "Rapport QA — DD/MM/YYYY (quotidien|hebdo)".
"""
import logging
import re
import requests
from datetime import datetime
import config

log = logging.getLogger(__name__)

_BASE = "https://api.notion.com/v1"
_HEADERS = {
    "Authorization": f"Bearer {config.NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

_MAX_BLOCK_TEXT = 1900  # Limite Notion : 2000 chars par rich_text
_NOTION_TIMEOUT_SECONDS = 60


def _rich_text(text: str) -> list[dict]:
    """Crée un tableau rich_text simple depuis une chaîne (tronqué si besoin)."""
    return [{"type": "text", "text": {"content": text[:_MAX_BLOCK_TEXT]}}]


def _rich_text_mrkd(text: str) -> list[dict]:
    """Rich_text avec support bold inline (**...**) et code inline (`...`)."""
    if len(text) > _MAX_BLOCK_TEXT:
        text = text[:_MAX_BLOCK_TEXT]

    # On garde ça simple : on envoie le texte tel quel, Notion ne rend pas le Markdown natif
    # mais le rapport reste lisible. Pour les annotations fines, il faudrait parser.
    return [{"type": "text", "text": {"content": text}}]


# ── Conversion Markdown → Blocks Notion ──────────────────────────────────────

def _md_to_notion_blocks(md: str) -> list[dict]:
    """
    Convertit un rapport Markdown en liste de blocks Notion.
    Supporte : heading_1/2/3, bulleted_list_item, divider, paragraph, table (ignoré → paragraph).
    Max 100 blocks envoyés par appel (limite API Notion).
    """
    blocks = []
    lines = md.split("\n")

    for line in lines:
        # Ligne vide → paragraph vide (espaceur)
        if not line.strip():
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": []},
            })
            continue

        # Headings
        if line.startswith("### "):
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": _rich_text(line[4:].strip())},
            })
        elif line.startswith("## "):
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": _rich_text(line[3:].strip())},
            })
        elif line.startswith("# "):
            blocks.append({
                "object": "block", "type": "heading_1",
                "heading_1": {"rich_text": _rich_text(line[2:].strip())},
            })

        # Séparateur
        elif line.strip() == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Listes à puces (- ou *)
        elif re.match(r"^[-*]\s", line):
            text = line[2:].strip()
            # Transforme les checkboxes Markdown [ ] / [x]
            if re.match(r"^\[[ x]\]", text):
                checked = text.startswith("[x]")
                text = text[4:].strip()
                blocks.append({
                    "object": "block", "type": "to_do",
                    "to_do": {"rich_text": _rich_text(text), "checked": checked},
                })
            else:
                blocks.append({
                    "object": "block", "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": _rich_text_mrkd(text)},
                })

        # Lignes de tableau Markdown → texte plat (Notion tables = complexe, pas utile ici)
        elif line.startswith("|"):
            # Ignore les lignes séparatrices |---|---|
            if re.match(r"^\|[-| :]+\|$", line.strip()):
                continue
            # Convertit en paragraph
            text = " | ".join(
                cell.strip() for cell in line.strip().strip("|").split("|")
            )
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(text)},
            })

        # Paragraph normal
        else:
            text = line.strip()
            if text:
                blocks.append({
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": _rich_text_mrkd(text)},
                })

    return blocks


def _chunk_blocks(blocks: list[dict], size: int = 100) -> list[list[dict]]:
    """Découpe la liste en sous-listes de max `size` éléments (limite Notion)."""
    return [blocks[i:i + size] for i in range(0, len(blocks), size)]


# ── Création / mise à jour des pages Notion ───────────────────────────────────

def _list_block_children(block_id: str) -> list[dict]:
    children: list[dict] = []
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        resp = requests.get(
            f"{_BASE}/blocks/{block_id}/children",
            headers=_HEADERS,
            params=params,
            timeout=_NOTION_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            log.warning(
                "[notion_reporter] Lecture children échouée : %s — %s",
                resp.status_code,
                resp.text[:200],
            )
            return children
        payload = resp.json()
        children.extend(payload.get("results") or [])
        if not payload.get("has_more"):
            return children
        cursor = payload.get("next_cursor")


def _find_child_page_by_title(parent_id: str, title: str) -> str | None:
    for child in _list_block_children(parent_id):
        if child.get("type") != "child_page":
            continue
        child_title = ((child.get("child_page") or {}).get("title") or "").strip()
        if child_title == title:
            return child.get("id")
    return None


def _archive_children(page_id: str) -> None:
    for child in _list_block_children(page_id):
        child_id = child.get("id")
        if not child_id:
            continue
        resp = requests.delete(f"{_BASE}/blocks/{child_id}", headers=_HEADERS, timeout=_NOTION_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            log.warning(
                "[notion_reporter] Archivage block échoué : %s — %s",
                resp.status_code,
                resp.text[:200],
            )


def _append_blocks(page_id: str, blocks: list[dict]) -> None:
    for chunk in _chunk_blocks(blocks, 100):
        patch_resp = requests.patch(
            f"{_BASE}/blocks/{page_id}/children",
            headers=_HEADERS,
            json={"children": chunk},
            timeout=_NOTION_TIMEOUT_SECONDS,
        )
        if patch_resp.status_code != 200:
            log.warning(f"[notion_reporter] Patch blocks partiel échoué : {patch_resp.status_code}")
            break


def _create_page(title: str, blocks: list[dict]) -> str | None:
    """
    Crée une sous-page sous NOTION_REPORTS_PAGE_ID.
    Retourne l'URL de la page créée ou None si erreur.
    """
    parent_id = config.NOTION_REPORTS_PAGE_ID

    # Premiers 100 blocks dans la création
    first_chunk = blocks[:100]
    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": first_chunk,
    }

    resp = requests.post(f"{_BASE}/pages", headers=_HEADERS, json=payload, timeout=_NOTION_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        log.error(f"[notion_reporter] Création page échouée : {resp.status_code} — {resp.text[:300]}")
        return None

    page = resp.json()
    page_id = page["id"]
    page_url = page.get("url", f"https://www.notion.so/{page_id.replace('-', '')}")
    log.info(f"[notion_reporter] Page créée : {title} → {page_url}")

    # Blocks suivants en patches si le rapport est long
    _append_blocks(page_id, blocks[100:])

    return page_url


def _update_page(page_id: str, title: str, blocks: list[dict]) -> str | None:
    """Remplace le contenu d'une page de rapport existante."""
    _archive_children(page_id)
    _append_blocks(page_id, blocks)
    url = f"https://www.notion.so/{page_id.replace('-', '')}"
    log.info(f"[notion_reporter] Page mise à jour : {title} → {url}")
    return url


# ── API publique ──────────────────────────────────────────────────────────────

def save_report_to_notion(report_md: str, date: datetime, mode: str, title_prefix: str | None = None) -> str | None:
    """
    Publie le rapport Markdown comme sous-page Notion sous Analytics.

    Args:
        report_md : contenu Markdown complet du rapport
        date      : datetime de référence du rapport
        mode      : "daily" ou "weekly"

    Returns:
        URL de la page Notion créée, ou None si échec/token manquant.
    """
    if config.DISABLE_EXTERNAL_PUBLISH:
        log.info("[notion_reporter] publication Notion désactivée par config")
        return None
    if not config.NOTION_API_KEY:
        log.debug("[notion_reporter] NOTION_API_KEY non défini — export ignoré")
        return None

    if not config.NOTION_REPORTS_PAGE_ID:
        log.warning("[notion_reporter] NOTION_REPORTS_PAGE_ID non défini")
        return None

    label = "Quotidien" if mode == "daily" else "Hebdomadaire"
    title = f"Rapport QA — {date.strftime('%d/%m/%Y')} ({label})"
    if title_prefix:
        title = f"{title_prefix} — {title}"

    try:
        blocks = _md_to_notion_blocks(report_md)
        existing_page_id = _find_child_page_by_title(config.NOTION_REPORTS_PAGE_ID, title)
        if existing_page_id:
            url = _update_page(existing_page_id, title, blocks)
        else:
            url = _create_page(title, blocks)
        if url:
            print(f"[notion_reporter] 📝 Notion → {url}")
        return url
    except Exception as e:
        log.error(f"[notion_reporter] Erreur inattendue : {e}")
        return None
