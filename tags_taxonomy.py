"""tags_taxonomy.py — Accès à la taxonomie de tags V3 + mapping déterministe (chantier E).

Charge `tags_taxonomy.yaml` (généré par scripts/build_tags_taxonomy.py). Expose :
- les catégories / sous-catégories (forme compacte pour le prompt one-shot — on
  N'injecte PAS les 96 tags dans le prompt, seulement les ~6 catégories et leurs
  sous-catégories) ;
- `map_to_tag()` : mapping fin (catégorie, sous-catégorie, texte libre) → tag_code
  V3, fait en Python DÉTERMINISTE (fuzzy sur name_v3 dans la sous-catégorie choisie),
  avec un niveau de confiance. Aucune invention par le LLM.
"""
from __future__ import annotations

import functools
from difflib import SequenceMatcher
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_TAXONOMY_PATH = Path(__file__).resolve().parent / "tags_taxonomy.yaml"
# Seuil de similarité au-dessus duquel un match name_v3 est jugé fiable.
_FUZZY_HIGH = 0.82


def _norm(s: str | None) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


@functools.lru_cache(maxsize=1)
def load_taxonomy(path: str | None = None) -> list[dict]:
    p = Path(path) if path else _TAXONOMY_PATH
    if yaml is None or not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return list(data.get("tags") or [])


def categories() -> list[str]:
    seen, out = set(), []
    for t in load_taxonomy():
        cat = t.get("category")
        if cat and cat not in seen:
            seen.add(cat)
            out.append(cat)
    return out


def subcategories(category: str) -> list[str]:
    cat_n = _norm(category)
    seen, out = set(), []
    for t in load_taxonomy():
        if _norm(t.get("category")) == cat_n:
            sub = t.get("subcategory")
            if sub and sub not in seen:
                seen.add(sub)
                out.append(sub)
    return out


def compact_for_prompt() -> str:
    """Bloc compact catégories → sous-catégories pour le prompt one-shot."""
    lines = []
    for cat in categories():
        subs = subcategories(cat)
        subs_txt = "; ".join(subs) if subs else "—"
        lines.append(f"- {cat}: {subs_txt}")
    return "\n".join(lines)


def map_to_tag(category: str | None, subcategory: str | None,
               free_text: str | None) -> dict:
    """Mappe une intention (catégorie/sous-catégorie/texte libre du LLM) vers un
    tag_code V3 déterministe. Retourne {tag_code, name_v3, confidence}.

    confidence='high' si match fuzzy fort sur name_v3 dans la sous-catégorie
    choisie ; 'low' sinon (suggestion seulement, jamais réinjectée automatiquement)."""
    tags = load_taxonomy()
    if not tags or not category:
        return {"tag_code": None, "name_v3": None, "confidence": "low"}

    cat_n = _norm(category)
    sub_n = _norm(subcategory) if subcategory else None
    probe = _norm(free_text) or sub_n or cat_n

    # Pool de candidats : même catégorie, et même sous-catégorie si fournie.
    pool = [t for t in tags if _norm(t.get("category")) == cat_n]
    if sub_n:
        sub_pool = [t for t in pool if _norm(t.get("subcategory")) == sub_n]
        if sub_pool:
            pool = sub_pool
    if not pool:
        return {"tag_code": None, "name_v3": None, "confidence": "low"}

    best, best_ratio = None, 0.0
    for t in pool:
        ratio = SequenceMatcher(None, probe, _norm(t.get("name_v3"))).ratio()
        if ratio > best_ratio:
            best, best_ratio = t, ratio

    # Un seul candidat dans la sous-catégorie ciblée → match direct (confiance haute).
    direct = sub_n is not None and len(pool) == 1
    confidence = "high" if (direct or best_ratio >= _FUZZY_HIGH) else "low"
    return {
        "tag_code": (best or {}).get("tag_code"),
        "name_v3": (best or {}).get("name_v3"),
        "confidence": confidence,
    }
