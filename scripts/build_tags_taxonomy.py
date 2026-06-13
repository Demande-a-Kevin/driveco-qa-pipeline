#!/usr/bin/env python3
"""build_tags_taxonomy.py — Régénère tags_taxonomy.yaml depuis le CSV Aircall V2 (chantier E.1).

Le CSV source (`Aircall Tags V2 (Tag_Call_reason_Mapping).csv`, encodage cp1252)
n'est JAMAIS committé (données métier). Ce script le convertit en
`tags_taxonomy.yaml` (versionné) : la taxonomie officielle des tags V3 actifs,
référentiel pour l'auto-catégorisation des appels (chantier E).

Usage :
    python scripts/build_tags_taxonomy.py [chemin_csv] [chemin_yaml_sortie]

Défauts : CSV via $AIRCALL_TAGS_CSV, sortie tags_taxonomy.yaml à la racine du repo.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "tags_taxonomy.yaml"
_RC_RE = re.compile(r"\b(RC\d{2})\b")


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _split_root_cause(raw: str) -> tuple[str | None, str | None]:
    """'RC01 – Payment / Transaction Issue' → ('RC01', 'Payment / Transaction Issue')."""
    raw = _clean(raw)
    if not raw:
        return None, None
    m = _RC_RE.search(raw)
    code = m.group(1) if m else None
    label = raw
    if code:
        # retire le préfixe "RCxx – " du label
        label = _clean(re.sub(rf"^{code}\s*[–-]\s*", "", raw))
    return code, label or None


def build(csv_path: Path) -> list[dict]:
    with open(csv_path, encoding="cp1252", newline="") as fh:
        rows = list(csv.reader(fh))
    header = [_clean(h) for h in rows[0]]
    idx = {name: i for i, name in enumerate(header)}

    def cell(row: list[str], name: str) -> str:
        i = idx.get(name)
        return _clean(row[i]) if i is not None and i < len(row) else ""

    tags: list[dict] = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        if cell(row, "IsActive").lower() != "active":
            continue  # on ne garde que les tags V3 actifs
        code = cell(row, "Tag Code")
        name_v3 = cell(row, "Tag Name V3")
        if not code and not name_v3:
            continue
        rc_code, rc_label = _split_root_cause(cell(row, "Root Cause (à mapper)"))
        tags.append({
            "tag_code": code or None,
            "name_v3": name_v3 or None,
            "category": cell(row, "Category") or None,
            "subcategory": cell(row, "Subcategory") or None,
            "root_cause": rc_code,
            "root_cause_label": rc_label,
            "complexity_level": cell(row, "Complexity Level") or None,
            "problem_category": cell(row, "Problem Category") or None,
            "is_active": True,
        })
    # tri stable : catégorie puis code
    tags.sort(key=lambda t: (t["category"] or "", t["tag_code"] or t["name_v3"] or ""))
    return tags


def _yaml_dump(tags: list[dict], csv_name: str) -> str:
    """Dump YAML déterministe sans dépendance (ruamel/pyyaml non requis)."""
    def q(v) -> str:
        if v is None:
            return "null"
        s = str(v)
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    cats: dict[str, int] = {}
    for t in tags:
        cats[t["category"] or "—"] = cats.get(t["category"] or "—", 0) + 1
    lines = [
        "# tags_taxonomy.yaml — taxonomie officielle des tags d'appel V3 (chantier E.1).",
        f"# Généré par scripts/build_tags_taxonomy.py depuis {csv_name}.",
        "# NE PAS éditer à la main — régénérer depuis le CSV source (jamais committé).",
        f"version: V3",
        f"active_tags_count: {len(tags)}",
        "categories:",
    ]
    for cat, n in sorted(cats.items()):
        lines.append(f"  - {q(cat)}: {n}")
    lines.append("tags:")
    for t in tags:
        lines.append(f"  - tag_code: {q(t['tag_code'])}")
        for key in ("name_v3", "category", "subcategory", "root_cause",
                    "root_cause_label", "complexity_level", "problem_category"):
            lines.append(f"    {key}: {q(t[key])}")
        lines.append(f"    is_active: true")
    return "\n".join(lines) + "\n"


def main() -> int:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.getenv("AIRCALL_TAGS_CSV", ""))
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    if not csv_path or not csv_path.exists():
        print(f"❌ CSV source introuvable : {csv_path!s}\n"
              f"   Passe le chemin en argument ou via $AIRCALL_TAGS_CSV.", file=sys.stderr)
        return 1
    tags = build(csv_path)
    out_path.write_text(_yaml_dump(tags, csv_path.name), encoding="utf-8")
    print(f"✅ {len(tags)} tags V3 actifs → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
