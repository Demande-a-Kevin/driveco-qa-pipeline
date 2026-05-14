import unittest
from datetime import datetime
from unittest import mock

import analysis_pipeline


class AnalysisPipelineTest(unittest.TestCase):
    def test_build_run_health_summary_marks_degraded_runs(self):
        summary = analysis_pipeline.build_run_health_summary(
            selected_calls=55,
            retained_calls=20,
            batch_stats={
                "calls_auto_truncated": 7,
                "auto_truncated_fields": 18,
                "retry_successes": 9,
                "failure_reasons": {
                    "json_invalid": 12,
                    "improvement_points.0.citation": 5,
                },
            },
        )

        self.assertTrue(summary["degraded"])
        self.assertEqual(summary["status"], "degraded")
        self.assertEqual(summary["retained_calls"], 20)
        self.assertEqual(summary["rejected_calls"], 35)
        self.assertEqual(summary["retention_rate_pct"], 36)
        self.assertEqual(summary["top_failure_reasons"][0]["reason"], "json_invalid")

    def test_persist_daily_snapshot_enriches_metrics_in_place(self):
        """Non-régression du bug observé sur le run du 17/04/2026 :
        `Conformité KB` affichée à 0% dans le rapport Markdown alors que
        `daily_kpi_snapshot.kb_compliance_rate` valait 57.1 en base.

        Cause racine : `_persist_daily_snapshot` créait une copie locale
        `enriched_metrics = dict(metrics)` jamais propagée au formatter.
        Fix : enrichissement in-place du dict `metrics` passé en paramètre.
        """
        metrics = {"pickup_rate_pct": 70.0, "abandon_rate_pct": 15.0}
        analysis = {
            "call_evaluations": [
                {"soft_skills": {"note_globale": 8.0}, "kb_compliance": "conforme", "improvement_items": []},
                {"soft_skills": {"note_globale": 6.0}, "kb_compliance": "partiel", "improvement_items": []},
            ],
            "analysis_meta": {"actual_coverage_pct": 75.3},
        }
        total_calls = [{"answered": "Yes", "duration_in_call": 180}]

        with mock.patch.object(analysis_pipeline, "_future_calls_for_repeat_cohort", return_value=[]), \
             mock.patch.object(analysis_pipeline.metrics_builder, "repeat_caller_rate", return_value=10.5), \
             mock.patch.object(analysis_pipeline, "_avg_soft_score", return_value=7.0), \
             mock.patch.object(analysis_pipeline.metrics_builder, "kb_compliance_rate", return_value=57.1), \
             mock.patch.object(analysis_pipeline.metrics_builder, "warm_transfer_success_rate", return_value=81.2), \
             mock.patch.object(analysis_pipeline.metrics_builder, "first_call_resolution_rate", return_value=35.1), \
             mock.patch.object(analysis_pipeline.metrics_builder, "detect_snapshot_anomalies", return_value=[]), \
             mock.patch.object(analysis_pipeline.metrics_builder, "build_agent_daily_snapshots", return_value=[]), \
             mock.patch.object(analysis_pipeline.metrics_builder, "cluster_kb_gaps", return_value=[]), \
             mock.patch.object(analysis_pipeline.persistence, "save_daily_snapshot"), \
             mock.patch.object(analysis_pipeline.persistence, "save_kb_gaps"), \
             mock.patch.object(analysis_pipeline.persistence, "save_anomaly_event"), \
             mock.patch.object(analysis_pipeline.persistence, "fetch_daily_snapshots", return_value=[]):
            analysis_pipeline._persist_daily_snapshot(
                datetime(2026, 4, 17), metrics, analysis, total_calls
            )

        # Le dict original doit contenir les clés enrichies — c'est ce que le formatter lit.
        self.assertEqual(metrics["kb_compliance_rate_pct"], 57.1)
        self.assertEqual(metrics["avg_soft_score"], 7.0)
        self.assertEqual(metrics["repeat_caller_rate_pct"], 10.5)
        self.assertEqual(metrics["warm_transfer_success_rate_pct"], 81.2)
        self.assertEqual(metrics["fcr_rate_pct"], 35.1)
        self.assertEqual(metrics["coverage_pct"], 75.3)
        # Les clés préexistantes sont préservées.
        self.assertEqual(metrics["pickup_rate_pct"], 70.0)

    def test_run_daily_blocks_empty_source_before_publication(self):
        with mock.patch.object(analysis_pipeline, "_sync_kb_if_enabled"), \
             mock.patch.object(analysis_pipeline.persistence, "save_llm_run"), \
             mock.patch.object(analysis_pipeline.call_fetcher, "fetch_calls_for_date", return_value=[]), \
             mock.patch.object(analysis_pipeline.call_classifier, "classify_all", return_value=[]), \
             mock.patch.object(analysis_pipeline.call_fetcher, "enrich_with_agent_identity", return_value=[]), \
             mock.patch.object(analysis_pipeline.config, "ALLOW_EMPTY_DAILY_REPORT", False), \
             mock.patch.object(analysis_pipeline.notifier, "save_report") as save_report, \
             mock.patch.object(analysis_pipeline.notifier, "send_slack_notification") as send_slack, \
             mock.patch.object(analysis_pipeline, "_finalize_run_record") as finalize:
            with self.assertRaisesRegex(RuntimeError, "empty_call_source"):
                analysis_pipeline.run_daily(datetime(2026, 5, 11))

        save_report.assert_not_called()
        send_slack.assert_not_called()
        finalize.assert_called_once()


class WeeklyReuseExistingEvaluationsTest(unittest.TestCase):
    """Le weekly doit réutiliser les évaluations déjà persistées par les
    dailies pour ne pas repasser par Ollama sur les mêmes appels."""

    def test_reused_evaluations_skip_ollama_and_land_in_consolidation(self):
        reused = {
            "abc123": {"call_id": "abc123", "score_global": 7.2, "_model": "gemma4:latest"},
            "def456": {"call_id": "def456", "score_global": 5.5, "_model": "gemma4:latest"},
        }
        calls = [
            {"call_id": "abc123", "call_id_internal": "abc123", "transcript": "t1"},
            {"call_id": "def456", "call_id_internal": "def456", "transcript": "t2"},
            {"call_id": "new999", "call_id_internal": "new999", "transcript": "t3"},
        ]

        with mock.patch.object(analysis_pipeline.persistence, "fetch_raw_evaluations_by_call_ids", return_value=reused), \
             mock.patch.object(analysis_pipeline.persistence, "canonical_call_id", side_effect=lambda c: c.get("call_id")), \
             mock.patch.object(analysis_pipeline, "run_prescreening"), \
             mock.patch.object(analysis_pipeline.schemas, "reset_clip_stats"), \
             mock.patch.object(analysis_pipeline.ollama_client, "is_available", return_value=False), \
             mock.patch.object(analysis_pipeline, "get_top_problematic", return_value=[]), \
             mock.patch.object(analysis_pipeline.metrics_builder, "build_voc_summary", return_value={}), \
             mock.patch.object(analysis_pipeline, "build_consolidation_summary", return_value={}), \
             mock.patch.object(analysis_pipeline, "build_consolidation_prompt", return_value=""), \
             mock.patch.object(analysis_pipeline.llm_client, "analyze", return_value={}), \
             mock.patch.object(analysis_pipeline.llm_client, "get_model_standard", return_value="haiku"), \
             mock.patch.object(analysis_pipeline.llm_client, "get_model_flagged", return_value="sonnet"), \
             mock.patch.object(analysis_pipeline.config, "ENABLE_ANTHROPIC_CONSOLIDATION", False):
            result = analysis_pipeline.run_batched_llm_analysis(
                datetime(2026, 4, 19), {}, calls, "kb-summary",
                consolidation_model="sonnet", mode="weekly",
                reuse_existing_evaluations=True,
            )

        evaluated_ids = {ev.get("call_id") for ev in result.get("call_evaluations", [])}
        self.assertIn("abc123", evaluated_ids)
        self.assertIn("def456", evaluated_ids)
        # `new999` n'a pas d'éval existante ; Ollama étant down dans ce test,
        # il n'est pas évalué — mais les 2 réutilisés doivent remonter.
        self.assertGreaterEqual(len(evaluated_ids), 2)


if __name__ == "__main__":
    unittest.main()
