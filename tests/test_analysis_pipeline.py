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


if __name__ == "__main__":
    unittest.main()
