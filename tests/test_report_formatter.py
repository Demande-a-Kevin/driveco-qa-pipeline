import unittest
from datetime import datetime

import report_formatter


class ReportFormatterTest(unittest.TestCase):
    def test_build_actionable_items_deduplicates_descriptions(self):
        analysis = {
            "top_problematic_calls": [
                {"call_id": "1", "errors": ["Manque d'empathie"]},
                {"call_id": "2", "errors": ["manque d'empathie"]},
            ],
            "kb_gaps": {"missing": [], "incomplete": [], "to_revise": []},
            "voc_summary": {"opportunities": []},
            "anomalies": [],
        }

        items = report_formatter.build_actionable_items(analysis)
        coaching = [item for item in items if item.get("tag") == "coaching"]
        self.assertEqual(len(coaching), 1)

    def test_daily_report_contains_voc_opportunities_section(self):
        analysis = {
            "kpis": {"calls_presented": 10, "pickup_rate_pct": 80, "overflow_rate_pct": 5, "abandon_rate_pct": 10, "kb_compliance_rate_pct": 70, "avg_duration_seconds": 120, "avg_wait_time_seconds": 20},
            "scores": {"ucc_quality_score": 8.2, "driveco_care_score": 7.8, "ucc_score_justification": "ok", "driveco_score_justification": "ok"},
            "top_problematic_calls": [],
            "kb_gaps": {"missing": [], "incomplete": [], "to_revise": []},
            "voc_summary": {
                "top_topics": [],
                "weak_signals": [],
                "verbatims": [],
                "competitors": [],
                "opportunities": [{"description": "Ajouter une alerte proactive", "count": 2}],
                "best_practices": [],
                "positive_satisfaction": {"count": 1, "sample_quote": "Merci pour votre aide"},
            },
            "run_health": {"degraded": False},
        }
        report = report_formatter.format_daily_report(datetime(2026, 4, 16), analysis["kpis"], analysis)
        self.assertIn("💡 Opportunités détectées", report)


if __name__ == "__main__":
    unittest.main()
