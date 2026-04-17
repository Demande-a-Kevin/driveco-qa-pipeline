import unittest

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


if __name__ == "__main__":
    unittest.main()
