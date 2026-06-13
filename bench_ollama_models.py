import json
import os
import signal
import time
from datetime import datetime
from pathlib import Path

import analysis_pipeline
import call_classifier
import call_fetcher
import config
import ollama_client
import reliability


BENCH_DATES = [datetime(2026, 4, 1), datetime(2026, 4, 2)]
BENCH_SAMPLE_SIZE = int(os.getenv("BENCH_SAMPLE_SIZE", "15"))
BENCH_BATCH_SIZE = 1
TRANSCRIPT_CANDIDATES_PER_DAY = 20
MIN_TRANSCRIPT_LINES = 6
# Chantier 0.4 : comparer plusieurs modèles (qualité MAE vs gold set). Configurable
# via BENCH_MODEL_NAMES="gemma4:12b,gemma3:4b". Défaut = le modèle de prod seul.
MODEL_NAMES = [
    m.strip() for m in os.getenv("BENCH_MODEL_NAMES", config.OLLAMA_FIXED_MODEL).split(",") if m.strip()
]
# Override num_ctx pour toute la passe (mesure 13/06 : sans effet sur le débit en
# mono-locataire ; utile pour vérifier l'impact qualité d'une fenêtre plus courte).
_BENCH_NUM_CTX = os.getenv("BENCH_NUM_CTX", "").strip()
if _BENCH_NUM_CTX.isdigit():
    config.OLLAMA_NUM_CTX = int(_BENCH_NUM_CTX)
BENCH_MODEL_TIMEOUT_SECONDS = int(os.getenv("BENCH_MODEL_TIMEOUT_SECONDS", "1800"))
BENCH_STOP_ON_FIRST_FAILED_BATCH = os.getenv("BENCH_STOP_ON_FIRST_FAILED_BATCH", "true").strip().lower() in {"1", "true", "yes", "on"}
BENCH_WARMUP_TIMEOUT_SECONDS = int(os.getenv("BENCH_WARMUP_TIMEOUT_SECONDS", "600"))
BENCH_OUTPUT_PATH = Path(config.REPORT_OUTPUT_DIR) / "bench_ollama_models_2026-04-01_2026-04-02.json"


def _chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def _load_sample_calls():
    sample: list[dict] = []
    seen_ids: set[str] = set()

    for bench_date in BENCH_DATES:
        calls = call_fetcher.fetch_calls_for_date(bench_date)
        for call in calls:
            call["classified_type"] = call_classifier.classify_call(call)
        eligible = [
            call for call in calls
            if call.get("classified_type") == "ucc_handled"
            and not (call.get("answered") == "Yes" and (call.get("duration_in_call") or 0) < 60)
        ]
        candidates = [dict(call) for call in eligible[:TRANSCRIPT_CANDIDATES_PER_DAY]]
        candidates = call_fetcher.enrich_with_transcripts(
            candidates,
            max_with_transcript=TRANSCRIPT_CANDIDATES_PER_DAY,
        )
        for call in candidates:
            call_id = str(call.get("call_id") or call.get("call_id_internal") or "").strip()
            if not call_id or call_id in seen_ids:
                continue
            transcript = call.get("transcript") or ""
            if len(transcript.splitlines()) < MIN_TRANSCRIPT_LINES:
                continue
            call["bench_date"] = bench_date.strftime("%Y-%m-%d")
            sample.append(call)
            seen_ids.add(call_id)
            if len(sample) >= BENCH_SAMPLE_SIZE:
                return sample

    if len(sample) < BENCH_SAMPLE_SIZE:
        raise RuntimeError(
            f"benchmark_sample_insufficient: {len(sample)}/{BENCH_SAMPLE_SIZE} appels avec transcript exploitable"
        )
    return sample
def _score_model_result(batches, elapsed_seconds, expected_total_calls):
    total_batches = len(batches)
    batch_successes = sum(1 for batch in batches if batch["success"])
    all_evals = [ev for batch in batches for ev in batch["evaluations"]]
    expected_rows = [row for batch in batches for row in batch["expected_rows"]]
    input_by_call = {
        str(row["call_id"]): row for row in expected_rows
        if row.get("call_id") is not None
    }

    type_matches = 0
    kb_present = 0
    reason_present = 0
    soft_present = 0
    for ev in all_evals:
        call_id = str(ev.get("call_id") or "")
        source = input_by_call.get(call_id)
        if source and ev.get("classified_type") == source.get("type"):
            type_matches += 1
        if ev.get("kb_compliance") in {"conforme", "partiel", "non_conforme"}:
            kb_present += 1
        if str(ev.get("customer_call_reason") or "").strip():
            reason_present += 1
        soft = ev.get("soft_skills") or {}
        if isinstance(soft, dict) and soft.get("note_globale") is not None:
            soft_present += 1

    evaluation_count = len(all_evals)
    expected_count = expected_total_calls
    timed_out_batches = sum(1 for batch in batches if batch.get("status") == "timed_out")
    failed_batches = sum(1 for batch in batches if batch.get("status") == "error")
    return {
        "batch_success_rate": round((batch_successes / total_batches) * 100, 1) if total_batches else 0.0,
        "evaluation_recall_rate": round((evaluation_count / expected_count) * 100, 1) if expected_count else 0.0,
        "classified_type_fidelity_rate": round((type_matches / evaluation_count) * 100, 1) if evaluation_count else 0.0,
        "kb_field_completion_rate": round((kb_present / evaluation_count) * 100, 1) if evaluation_count else 0.0,
        "reason_field_completion_rate": round((reason_present / evaluation_count) * 100, 1) if evaluation_count else 0.0,
        "softskills_completion_rate": round((soft_present / evaluation_count) * 100, 1) if evaluation_count else 0.0,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "evaluations_returned": evaluation_count,
        "expected_evaluations": expected_count,
        "timed_out_batches": timed_out_batches,
        "failed_batches": failed_batches,
    }


def _semantic_gold_metrics(model_name: str) -> dict:
    original_model = config.OLLAMA_MODEL_ANALYSIS
    config.OLLAMA_MODEL_ANALYSIS = model_name
    try:
        scored_rows = reliability.score_gold_set(mode="ollama", kb_summary="")
        metrics = reliability.compute_reliability_metrics(scored_rows).as_dict()
        return {
            "gold_entries_used": metrics["entries_used"],
            "semantic_mae": metrics["mae"],
            "semantic_pearson": metrics["pearson"],
            "semantic_topic_f1": metrics["topic_f1"],
            "semantic_entity_sentiment_mae": metrics["entity_sentiment_mae"],
            "semantic_verbatim_recall": metrics["verbatim_recall"],
        }
    finally:
        config.OLLAMA_MODEL_ANALYSIS = original_model


def _run_model(model_name, sample_calls):
    original_model = config.OLLAMA_MODEL_ANALYSIS
    config.OLLAMA_MODEL_ANALYSIS = model_name
    batches = []
    started = time.perf_counter()
    try:
        total_batches = (len(sample_calls) + BENCH_BATCH_SIZE - 1) // BENCH_BATCH_SIZE
        for batch_num, batch_calls in enumerate(_chunks(sample_calls, BENCH_BATCH_SIZE), start=1):
            print(f"[bench] {model_name} batch {batch_num}/{total_batches}", flush=True)
            expected_rows = [
                analysis_pipeline._build_call_entry(call, transcript_max_chars=config.OLLAMA_TRANSCRIPT_MAX_CHARS)
                for call in batch_calls
            ]
            batch_kb_summary = analysis_pipeline.get_batch_kb_excerpt(batch_calls)
            evaluations = ollama_client.analyze_batch(
                system_prompt=analysis_pipeline.SYSTEM_PROMPT,
                batch_calls=batch_calls,
                kb_summary=batch_kb_summary,
                date_str=batch_calls[0].get("bench_date") or BENCH_DATES[-1].strftime("%Y-%m-%d"),
                batch_num=batch_num,
                total_batches=total_batches,
            )
            batches.append(
                {
                    "batch_num": batch_num,
                    "status": "completed" if len(evaluations) == len(batch_calls) else "error",
                    "success": len(evaluations) == len(batch_calls),
                    "expected_rows": expected_rows,
                    "evaluations": evaluations,
                    "error": None if len(evaluations) == len(batch_calls) else "evaluation_count_mismatch",
                    "timeout_seconds": None,
                }
            )
            if BENCH_STOP_ON_FIRST_FAILED_BATCH and len(evaluations) != len(batch_calls):
                print(
                    f"[bench] {model_name} arrêt anticipé après batch {batch_num}/{total_batches} en échec",
                    flush=True,
                )
                break
    finally:
        config.OLLAMA_MODEL_ANALYSIS = original_model
    elapsed = time.perf_counter() - started
    metrics = _score_model_result(batches, elapsed, expected_total_calls=len(sample_calls))
    metrics.update(_semantic_gold_metrics(model_name))
    metrics["batches"] = batches
    print(f"[bench] {model_name} terminé en {metrics['elapsed_seconds']}s", flush=True)
    return metrics


def _rank_models(results):
    def score(row):
        metrics = row["metrics"]
        return (
            (metrics["batch_success_rate"] * 0.30)
            + (metrics["evaluation_recall_rate"] * 0.20)
            + (metrics["classified_type_fidelity_rate"] * 0.15)
            + (metrics["kb_field_completion_rate"] * 0.15)
            + (metrics["reason_field_completion_rate"] * 0.10)
            + (metrics["softskills_completion_rate"] * 0.10)
            + ((100 - (metrics.get("semantic_mae") or 100) * 20) * 0.10)
            + (((metrics.get("semantic_pearson") or 0) + 1) * 25 * 0.05)
            - metrics["timed_out_batches"] * 15
            - metrics["failed_batches"] * 10
            - metrics["elapsed_seconds"] * 0.005
        )

    ranked = []
    for row in results:
        row = dict(row)
        row["benchmark_score"] = round(score(row), 2)
        ranked.append(row)
    ranked.sort(key=lambda item: item["benchmark_score"], reverse=True)
    return ranked


def _write_report(report: dict) -> None:
    BENCH_OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _warmup_model(model_name: str) -> None:
    print(f"[bench] warmup {model_name}", flush=True)
    try:
        ollama_client._chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "Réponds uniquement par ok."},
                {"role": "user", "content": "ok"},
            ],
            max_tokens=8,
            timeout=BENCH_WARMUP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        print(f"[bench] warmup {model_name} failed: {exc}", flush=True)


def _run_model_with_timeout(model_name: str, sample_calls: list[dict]) -> dict:
    def _handle_timeout(signum, frame):
        raise TimeoutError(f"model_timeout_{model_name}")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(BENCH_MODEL_TIMEOUT_SECONDS)
    try:
        return {
            "model": model_name,
            "metrics": _run_model(model_name, sample_calls),
        }
    except TimeoutError:
        print(f"[bench] {model_name} timed out after {BENCH_MODEL_TIMEOUT_SECONDS}s", flush=True)
        return {
            "model": model_name,
            "metrics": {
                "batch_success_rate": 0.0,
                "evaluation_recall_rate": 0.0,
                "classified_type_fidelity_rate": 0.0,
                "kb_field_completion_rate": 0.0,
                "reason_field_completion_rate": 0.0,
                "softskills_completion_rate": 0.0,
                "elapsed_seconds": float(BENCH_MODEL_TIMEOUT_SECONDS),
                "evaluations_returned": 0,
                "expected_evaluations": BENCH_SAMPLE_SIZE,
                "timed_out_batches": BENCH_SAMPLE_SIZE,
                "failed_batches": 0,
                "batches": [],
                "status": "timed_out",
            },
        }
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def main():
    sample_calls = _load_sample_calls()
    results = []

    for model_name in MODEL_NAMES:
        _warmup_model(model_name)
        results.append(_run_model_with_timeout(model_name, sample_calls))
        interim_report = {
            "benchmark_dates": [d.strftime("%Y-%m-%d") for d in BENCH_DATES],
            "sample_size": len(sample_calls),
            "sample_call_ids": [str(call.get("call_id")) for call in sample_calls],
            "bench_batch_size": BENCH_BATCH_SIZE,
            "transcript_max_chars": config.OLLAMA_TRANSCRIPT_MAX_CHARS,
            "ollama_analysis_timeout": config.OLLAMA_ANALYSIS_TIMEOUT,
            "bench_model_timeout_seconds": BENCH_MODEL_TIMEOUT_SECONDS,
            "bench_warmup_timeout_seconds": BENCH_WARMUP_TIMEOUT_SECONDS,
            "models": _rank_models(results),
        }
        _write_report(interim_report)

    ranked = _rank_models(results)
    report = {
        "benchmark_dates": [d.strftime("%Y-%m-%d") for d in BENCH_DATES],
        "sample_size": len(sample_calls),
        "sample_call_ids": [str(call.get("call_id")) for call in sample_calls],
        "bench_batch_size": BENCH_BATCH_SIZE,
        "transcript_max_chars": config.OLLAMA_TRANSCRIPT_MAX_CHARS,
        "ollama_analysis_timeout": config.OLLAMA_ANALYSIS_TIMEOUT,
        "bench_model_timeout_seconds": BENCH_MODEL_TIMEOUT_SECONDS,
        "bench_warmup_timeout_seconds": BENCH_WARMUP_TIMEOUT_SECONDS,
        "models": ranked,
    }

    _write_report(report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
