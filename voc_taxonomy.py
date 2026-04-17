from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_VOC_TAXONOMY_PATH = Path(__file__).resolve().parent / "voc_taxonomy.yaml"


def _slug(value: str) -> str:
    text = re.sub(r"[^\w]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "autre"


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    payload = yaml.safe_load(_VOC_TAXONOMY_PATH.read_text(encoding="utf-8"))
    for axis in ("topics", "entities", "aspects"):
        items = payload.get(axis) or []
        if not items:
            raise ValueError(f"voc_taxonomy.yaml invalide: axe {axis} vide")
    return payload


def taxonomy_version() -> str:
    return str(load_taxonomy().get("version") or "unknown")


def axis_items(axis: str) -> list[dict[str, Any]]:
    return list(load_taxonomy().get(axis) or [])


def axis_codes(axis: str) -> set[str]:
    return {str(item["code"]) for item in axis_items(axis)}


def axis_label_map(axis: str) -> dict[str, str]:
    return {str(item["code"]): str(item.get("label") or item["code"]) for item in axis_items(axis)}


def product_area_for_topic(code: str) -> str:
    normalized_code, _ = normalize_taxonomy_code("topics", code)
    for item in axis_items("topics"):
        if str(item.get("code")) == normalized_code:
            return str(item.get("product_area") or "other")
    return "other"


def normalize_taxonomy_code(axis: str, value: str) -> tuple[str, bool]:
    code = _slug(value)
    allowed = axis_codes(axis)
    if code in allowed:
        return code, False
    if code.startswith("autre_"):
        return code, True
    if code == "autre":
        return code, True
    return f"autre_{code}", True


def taxonomy_prompt_block() -> str:
    lines = [f"Taxonomy version: {taxonomy_version()}"]
    for axis in ("topics", "entities", "aspects"):
        items = axis_items(axis)
        if axis == "topics":
            labels = ", ".join(
                f"{item['code']} ({item.get('label', item['code'])}, area={item.get('product_area', 'other')})"
                for item in items
            )
        else:
            labels = ", ".join(f"{item['code']} ({item.get('label', item['code'])})" for item in items)
        lines.append(f"- {axis}: {labels}")
    lines.append("Si un item ne rentre pas dans la taxonomie, utilise autre_<texte_court>.")
    return "\n".join(lines)
