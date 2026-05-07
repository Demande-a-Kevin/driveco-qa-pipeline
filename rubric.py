from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_RUBRIC_PATH = Path(__file__).resolve().parent / "rubric.yaml"

# Override runtime injecté par analysis_pipeline via set_effective_rubric().
# Si None → fallback sur rubric.yaml (rétrocompat tests / usages directs).
_EFFECTIVE_RUBRIC: dict[str, Any] | None = None


def set_effective_rubric(rubric: dict[str, Any] | None) -> None:
    """Override la rubric active (utilisé par runtime_config).

    `rubric` doit avoir au minimum `criteria` (liste) et idéalement `version`.
    Passer None pour revenir au fichier `rubric.yaml`.
    """
    global _EFFECTIVE_RUBRIC
    _EFFECTIVE_RUBRIC = rubric


@lru_cache(maxsize=1)
def load_rubric() -> dict[str, Any]:
    rubric = yaml.safe_load(_RUBRIC_PATH.read_text(encoding="utf-8"))
    criteria = rubric.get("criteria") or []
    if not criteria:
        raise ValueError("rubric.yaml ne contient aucun critère")
    total_weight = round(sum(float(item.get("weight", 0.0)) for item in criteria), 6)
    if total_weight != 1.0:
        raise ValueError(f"rubric.yaml invalide: somme des poids = {total_weight}, attendu 1.0")
    return rubric


def _active_rubric() -> dict[str, Any]:
    if _EFFECTIVE_RUBRIC is not None:
        return _EFFECTIVE_RUBRIC
    return load_rubric()


def rubric_version() -> str:
    return str(_active_rubric().get("version") or "unknown")


def rubric_criteria() -> list[dict[str, Any]]:
    return list(_active_rubric()["criteria"])


def rubric_keys() -> list[str]:
    return [str(item["key"]) for item in rubric_criteria()]


def criteria_weights() -> dict[str, float]:
    return {str(item["key"]): float(item["weight"]) for item in rubric_criteria()}


def build_rubric_prompt_block() -> str:
    lines = [f"Rubric version: {rubric_version()}"]
    for item in rubric_criteria():
        anchors = item.get("anchors") or {}
        lines.append(
            f"- {item['key']} ({item['label']}) poids={item['weight']} | "
            f"0={anchors.get('0', '')} | 3={anchors.get('3', '')} | "
            f"6={anchors.get('6', '')} | 9={anchors.get('9', '')}"
        )
    return "\n".join(lines)


def compute_weighted_score(scores: dict[str, float | int | None]) -> float | None:
    weights = criteria_weights()
    weighted_total = 0.0
    used_weight = 0.0
    for key, weight in weights.items():
        value = scores.get(key)
        if value is None:
            continue
        numeric = float(value)
        weighted_total += numeric * weight
        used_weight += weight
    if used_weight < 0.6:
        return None
    return round(weighted_total / used_weight, 1)
