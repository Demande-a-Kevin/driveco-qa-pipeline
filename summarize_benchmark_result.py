import json
from datetime import datetime
from pathlib import Path

import config
import gdrive_uploader


def _latest_benchmark_json() -> Path | None:
    files = sorted(
        Path(config.REPORT_OUTPUT_DIR).glob("bench_ollama_models_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _fmt_duration(seconds) -> str:
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "n/a"
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}h{mins:02d}m{secs:02d}s"
    return f"{mins}m{secs:02d}s"


def build_summary_markdown(report: dict, source_json: Path) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Benchmark Ollama — résumé",
        "",
        f"- Généré le : `{generated_at}`",
        f"- Source : `{source_json.name}`",
        f"- Période appels : `{', '.join(report.get('benchmark_dates', []))}`",
        f"- Taille échantillon : `{report.get('sample_size', 0)}` appels",
        f"- Batch size : `{report.get('bench_batch_size', 'n/a')}`",
        f"- Transcript max chars : `{report.get('transcript_max_chars', 'n/a')}`",
        f"- Timeout analyse Ollama : `{report.get('ollama_analysis_timeout', 'n/a')}` s",
        f"- Timeout modèle benchmark : `{report.get('bench_model_timeout_seconds', 'n/a')}` s",
        f"- Timeout warmup benchmark : `{report.get('bench_warmup_timeout_seconds', 'n/a')}` s",
        "",
        "## Classement",
        "",
    ]

    for idx, row in enumerate(report.get("models", []), start=1):
        metrics = row.get("metrics", {})
        lines.extend(
            [
                f"### {idx}. {row.get('model', 'inconnu')}",
                "",
                f"- Score benchmark : `{row.get('benchmark_score', 'n/a')}`",
                f"- Durée totale : `{_fmt_duration(metrics.get('elapsed_seconds'))}`",
                f"- Batch success : `{metrics.get('batch_success_rate', 0)}%`",
                f"- Batches timeout : `{metrics.get('timed_out_batches', 0)}`",
                f"- Batches failed : `{metrics.get('failed_batches', 0)}`",
                f"- Evaluation recall : `{metrics.get('evaluation_recall_rate', 0)}%`",
                f"- Fidelity type : `{metrics.get('classified_type_fidelity_rate', 0)}%`",
                f"- Complétion KB : `{metrics.get('kb_field_completion_rate', 0)}%`",
                f"- Complétion raison appel : `{metrics.get('reason_field_completion_rate', 0)}%`",
                f"- Complétion soft skills : `{metrics.get('softskills_completion_rate', 0)}%`",
                f"- Evaluations rendues : `{metrics.get('evaluations_returned', 0)}/{metrics.get('expected_evaluations', 0)}`",
                "",
            ]
        )

    sample_call_ids = report.get("sample_call_ids") or []
    if sample_call_ids:
        lines.extend(
            [
                "## Appels benchmarkés",
                "",
                ", ".join(f"`{call_id}`" for call_id in sample_call_ids),
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def write_interrupted_summary(reason: str) -> Path:
    output_dir = Path(config.REPORT_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "bench_ollama_latest_summary.md"
    content = "\n".join(
        [
            "# Benchmark Ollama — interrompu",
            "",
            f"- Date : `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
            f"- Statut : `{reason}`",
            "- Action : le run `daily` de publication a été priorisé.",
            "- Consulter : `qa-driveco-data/logs/cron_benchmark.log`",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    source_json = _latest_benchmark_json()
    if not source_json:
        print("[bench-summary] aucun JSON benchmark trouvé")
        return 1

    report = json.loads(source_json.read_text(encoding="utf-8"))
    summary = build_summary_markdown(report, source_json)

    output_dir = Path(config.REPORT_OUTPUT_DIR)
    dated_name = source_json.name.replace(".json", "_summary.md")
    dated_path = output_dir / dated_name
    latest_path = output_dir / "bench_ollama_latest_summary.md"
    dated_path.write_text(summary, encoding="utf-8")
    latest_path.write_text(summary, encoding="utf-8")

    print(f"[bench-summary] résumé écrit : {dated_path}")
    print(f"[bench-summary] résumé courant : {latest_path}")

    try:
        link = gdrive_uploader.upload_report(dated_path, report_type="benchmark")
        if link:
            print(f"[bench-summary] Google Drive : {link}")
    except Exception as exc:
        print(f"[bench-summary] upload Drive ignoré : {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
