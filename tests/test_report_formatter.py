import unittest
from datetime import datetime
from unittest import mock

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
                "top_topics": [{"label": "TPE refusé", "count": 4}],
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

    def test_daily_report_uses_call_reasons_and_assets_aircall_links(self):
        analysis = {
            "kpis": {"calls_presented": 10, "pickup_rate_pct": 80, "overflow_rate_pct": 5, "abandon_rate_pct": 10, "kb_compliance_rate_pct": 70, "avg_duration_seconds": 120, "avg_wait_time_seconds": 20},
            "scores": {"ucc_quality_score": 8.2, "driveco_care_score": 7.8, "ucc_score_justification": "ok", "driveco_score_justification": "ok"},
            "top_problematic_calls": [
                {"call_id": "3767111602", "agent": "N/A", "duration_seconds": 120, "kb_compliance": "partiel", "errors": ["Paiement TPE refusé"]}
            ],
            "kb_gaps": {"missing": [], "incomplete": [], "to_revise": []},
            "voc_summary": {
                "call_reasons": [
                    {
                        "label": "Paiement application",
                        "count": 3,
                        "subreasons": [{"label": "TPE / CB", "count": 2}],
                    }
                ],
                "top_topics": [{"label": "TPE refusé", "count": 4}],
                "weak_signals": [],
                "verbatims": [],
                "competitors": [],
                "opportunities": [],
                "best_practices": [],
            },
            "run_health": {"degraded": False},
        }

        report = report_formatter.format_daily_report(datetime(2026, 4, 16), analysis["kpis"], analysis)
        self.assertIn("## Raisons d'appel", report)
        self.assertIn("### Raisons principales par appel", report)
        self.assertIn("Paiement application — 3 appel(s) (TPE / CB: 2)", report)
        self.assertIn("### Problématiques clients détectées", report)
        self.assertIn("TPE refusé — 4 mention(s)", report)
        self.assertIn("https://assets.aircall.io/calls/3767111602/recording/info", report)
        self.assertNotIn("https://asset.aircall.io/calls/3767111602/recording/info", report)

    def test_daily_report_does_not_render_competitors_twice(self):
        analysis = {
            "kpis": {"calls_presented": 10, "pickup_rate_pct": 80, "overflow_rate_pct": 5, "abandon_rate_pct": 10, "kb_compliance_rate_pct": 70, "avg_duration_seconds": 120, "avg_wait_time_seconds": 20},
            "scores": {},
            "top_problematic_calls": [],
            "kb_gaps": {"missing": [], "incomplete": [], "to_revise": []},
            "voc_summary": {
                "competitors": [{"competitor_name": "Carrefour", "count": 2, "sample_quote": "Carrefour est cité"}],
            },
            "run_health": {"degraded": False},
        }

        report = report_formatter.format_daily_report(datetime(2026, 4, 16), analysis["kpis"], analysis)
        self.assertEqual(report.count("Concurrents cités"), 1)

    def test_weekly_report_deduplicates_topics_between_sections(self):
        analysis = {
            "kpis": {"calls_presented": 10, "pickup_rate_pct": 80, "abandon_rate_pct": 10},
            "scores": {"ucc_quality_score": 7, "driveco_care_score": 7},
            "voc_summary": {
                "weak_signals": [
                    {"topic_code": "interruption_charge", "count": 5},
                    {"topic_code": "app_bug", "count": 3},
                ],
            },
            "top_problematic_calls": [],
            "kb_gaps": {"missing": [], "incomplete": [], "to_revise": []},
        }

        def fake_fetch(view_name, columns="*", limit=None, **filters):
            if view_name == "v_voc_topics_trend_28d":
                return [{"topic_code": "interruption_charge", "mentions": 5, "avg_sentiment": -0.8}]
            return []

        with mock.patch.object(report_formatter.persistence, "fetch_view_rows", side_effect=fake_fetch):
            report = report_formatter.format_weekly_report(
                datetime(2026, 5, 18),
                datetime(2026, 5, 24),
                analysis["kpis"],
                analysis,
            )

        self.assertEqual(report.count("interruption_charge"), 1)
        self.assertIn("app_bug", report)


if __name__ == "__main__":
    unittest.main()
