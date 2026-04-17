from __future__ import annotations

from dataclasses import dataclass
import logging
from math import sqrt
from pathlib import Path

import yaml

import llm_client
import ollama_client
import qa_prompting


GOLD_SET_PATH = Path(__file__).resolve().parent / "tests" / "gold_set" / "gold_set.yaml"
log = logging.getLogger(__name__)


@dataclass
class ReliabilityMetrics:
    entries_used: int
    mae: float | None
    pearson: float | None
    topic_f1: float | None
    entity_sentiment_mae: float | None
    verbatim_recall: float | None

    def as_dict(self) -> dict:
        return {
            "entries_used": self.entries_used,
            "mae": self.mae,
            "pearson": self.pearson,
            "topic_f1": self.topic_f1,
            "entity_sentiment_mae": self.entity_sentiment_mae,
            "verbatim_recall": self.verbatim_recall,
        }


def load_gold_set() -> list[dict]:
    payload = yaml.safe_load(GOLD_SET_PATH.read_text(encoding="utf-8")) or {}
    return list(payload.get("entries") or [])


def usable_gold_entries() -> list[dict]:
    entries = []
    for entry in load_gold_set():
        if entry.get("status") == "pending_annotation":
            continue
        if not entry.get("transcript") or entry.get("human_score") is None:
            continue
        entries.append(entry)
    return entries


def build_call(entry: dict) -> dict:
    return {
        "call_id_internal": entry["call_id"],
        "call_id": entry["call_id"],
        "classified_type": entry.get("classified_type") or "ucc_handled",
        "duration_in_call": int(entry.get("duration_seconds") or 0),
        "user_name": entry.get("agent") or "gold_set",
        "transcript": entry["transcript"],
        "answered": "Yes",
    }


def _score_entry_ollama(entry: dict, kb_summary: str = "") -> dict | None:
    rows = ollama_client.analyze_batch(
        system_prompt=qa_prompting.load_base_system_prompt(),
        batch_calls=[build_call(entry)],
        kb_summary=kb_summary,
        date_str=entry.get("call_id") or "gold",
        batch_num=1,
        total_batches=1,
    )
    return rows[0] if rows else None


def _score_entry_claude(entry: dict, kb_summary: str = "") -> dict | None:
    rows = llm_client.analyze_batch([build_call(entry)], kb_summary, model=llm_client.get_model_standard())
    return rows[0] if rows else None


def score_gold_set(mode: str = "ollama", kb_summary: str = "") -> list[dict]:
    outputs = []
    entries = usable_gold_entries()
    for index, entry in enumerate(entries, start=1):
        log.info("[reliability] scoring %s %s/%s", entry.get("call_id"), index, len(entries))
        if mode == "claude":
            evaluation = _score_entry_claude(entry, kb_summary=kb_summary)
        else:
            evaluation = _score_entry_ollama(entry, kb_summary=kb_summary)
        outputs.append({"entry": entry, "evaluation": evaluation})
    return outputs


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x <= 0 or den_y <= 0:
        return None
    return round(num / (den_x * den_y), 3)


def _multi_label_f1(rows: list[tuple[set[str], set[str]]]) -> float | None:
    if not rows:
        return None
    tp = fp = fn = 0
    for expected, predicted in rows:
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    if tp <= 0:
        return 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall <= 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 3)


def _sentiment_to_value(value: str | None) -> float | None:
    mapping = {"très_négatif": -2.0, "négatif": -1.0, "neutre": 0.0, "positif": 1.0, "très_positif": 2.0}
    return mapping.get(str(value or "").strip())


def compute_reliability_metrics(scored_rows: list[dict]) -> ReliabilityMetrics:
    human_scores = []
    predicted_scores = []
    topic_rows = []
    sentiment_errors = []
    verbatim_hits = 0
    verbatim_total = 0

    for row in scored_rows:
        entry = row["entry"]
        evaluation = row.get("evaluation") or {}
        if evaluation.get("score_global") is None:
            continue
        human_scores.append(float(entry["human_score"]))
        predicted_scores.append(float(evaluation["score_global"]))

        expected_topics = {item["topic_code"] for item in entry.get("voc_topics") or [] if item.get("topic_code")}
        predicted_topics = {
            item.get("topic_code")
            for item in ((evaluation.get("voc_extract") or {}).get("topics") or [])
            if item.get("topic_code")
        }
        if expected_topics:
            topic_rows.append((expected_topics, predicted_topics))

        expected_entities = {item["entity_code"]: _sentiment_to_value(item.get("sentiment")) for item in entry.get("voc_entities") or []}
        predicted_entities = {
            item.get("entity_code"): _sentiment_to_value(item.get("sentiment"))
            for item in ((evaluation.get("voc_extract") or {}).get("entity_perceptions") or [])
            if item.get("entity_code")
        }
        for entity_code, expected_value in expected_entities.items():
            predicted_value = predicted_entities.get(entity_code)
            if expected_value is None or predicted_value is None:
                continue
            sentiment_errors.append(abs(expected_value - predicted_value))

        predicted_quotes = [
            str(item.get("quote") or "").strip().lower()
            for item in ((evaluation.get("voc_extract") or {}).get("verbatim_quotes") or [])
        ]
        for expected_quote in entry.get("key_verbatims") or []:
            expected_norm = str(expected_quote).strip().lower()
            verbatim_total += 1
            if any(expected_norm in candidate or candidate in expected_norm for candidate in predicted_quotes):
                verbatim_hits += 1

    mae = round(sum(abs(h - p) for h, p in zip(human_scores, predicted_scores)) / len(human_scores), 3) if human_scores else None
    pearson = _pearson(human_scores, predicted_scores)
    topic_f1 = _multi_label_f1(topic_rows)
    entity_sentiment_mae = round(sum(sentiment_errors) / len(sentiment_errors), 3) if sentiment_errors else None
    verbatim_recall = round(verbatim_hits / verbatim_total, 3) if verbatim_total else None
    return ReliabilityMetrics(
        entries_used=len(human_scores),
        mae=mae,
        pearson=pearson,
        topic_f1=topic_f1,
        entity_sentiment_mae=entity_sentiment_mae,
        verbatim_recall=verbatim_recall,
    )
