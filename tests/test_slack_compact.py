"""Tests du post Slack compact exception-based (chantier A)."""
import datetime
import unittest
from unittest import mock

import config
import notifier


def _analysis(actionable=None, ucc_n=25, analyzed=100, eligible=100):
    return {
        "scores": {"ucc_quality_score": 8.5, "driveco_care_score": 7.0,
                   "ucc_evaluated_calls": ucc_n, "driveco_care_evaluated_calls": 12},
        "kpis": {"answer_rate_pct": 92.0, "abandon_rate_pct": 3.0, "escalations_count": 2},
        "analysis_meta": {"analyzed_calls": analyzed, "eligible_calls": eligible},
        "actionable_items": actionable or [],
    }


class CompactBuilderTest(unittest.TestCase):
    def test_block_count_within_limit(self):
        blocks = notifier.build_slack_blocks_compact(_analysis(), "daily", datetime.datetime(2026, 6, 12))
        self.assertLessEqual(len(blocks), 10)
        self.assertEqual(blocks[0]["type"], "header")

    def test_ras_when_no_alerts(self):
        blocks = notifier.build_slack_blocks_compact(_analysis(), "daily", datetime.datetime(2026, 6, 12))
        txt = " ".join(b.get("text", {}).get("text", "") for b in blocks if b.get("type") == "section")
        self.assertIn("RAS", txt)

    def test_alerts_listed_and_capped(self):
        items = [{"priority": "critical", "description": f"Souci {i}", "representative_call_ids": ["123"]}
                 for i in range(8)]
        lines = notifier._compact_alert_lines(items, max_lines=5)
        self.assertEqual(len(lines), 5)  # capé à 5
        self.assertTrue(all(l.startswith("🔴") for l in lines))

    def test_low_n_shows_white_icon(self):
        blocks = notifier.build_slack_blocks_compact(_analysis(ucc_n=4), "daily", datetime.datetime(2026, 6, 12))
        fields = next(b for b in blocks if b.get("type") == "section" and "fields" in b)["fields"]
        ucc_field = fields[0]["text"]
        self.assertIn("⚪", ucc_field)
        self.assertIn("(n=4)", ucc_field)

    def test_partial_coverage_note(self):
        blocks = notifier.build_slack_blocks_compact(_analysis(analyzed=59, eligible=106), "daily", datetime.datetime(2026, 6, 12))
        txt = " ".join(e.get("text", "") for b in blocks if b.get("type") == "context" for e in b.get("elements", []))
        self.assertIn("rattrapage", txt)

    def test_dispatch_compact_vs_full(self):
        with mock.patch.object(config, "SLACK_REPORT_STYLE", "compact"):
            b = notifier.build_slack_blocks(_analysis(), "daily", datetime.datetime(2026, 6, 12))
            self.assertLessEqual(len(b), 10)
        # weekly reste détaillé (non compact) même en style compact
        with mock.patch.object(config, "SLACK_REPORT_STYLE", "compact"):
            bw = notifier.build_slack_blocks(_analysis(), "weekly", datetime.datetime(2026, 6, 12),
                                             calls=[], ucc_calls=[], qa_calls=[])
            self.assertGreater(len(bw), 5)


if __name__ == "__main__":
    unittest.main()
