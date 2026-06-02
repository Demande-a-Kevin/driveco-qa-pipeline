"""Tests de déduplication Slack pour notifier.

Couvre le bug observé sur le run du 17/04/2026 où `send_voc_alerts` et
`send_anomaly_alerts` pouvaient republier Slack lors d'un rerun manuel parce
qu'ils n'avaient pas de flag de déduplication (contrairement à
`send_slack_notification`).
"""
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import notifier


class SlackDedupFlagsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._output_patch = mock.patch.object(notifier, "OUTPUT", Path(self._tmp.name))
        self._output_patch.start()
        self.addCleanup(self._output_patch.stop)
        self.date = datetime(2026, 4, 17)

    def test_report_flag_keeps_legacy_name_for_watchdog_compat(self):
        """Le flag du rapport principal doit garder le nom historique
        `.slack_sent_{mode}_{date}.flag` pour rester compatible avec
        `run_daily_watchdog.sh`."""
        flag = notifier._slack_sent_flag("report", "daily", self.date)
        self.assertEqual(flag.name, ".slack_sent_daily_2026-04-17.flag")

    def test_voc_and_anomaly_have_distinct_flags(self):
        voc_flag = notifier._slack_sent_flag("voc", "daily", self.date)
        anomaly_flag = notifier._slack_sent_flag("anomaly", "daily", self.date)
        report_flag = notifier._slack_sent_flag("report", "daily", self.date)
        self.assertEqual(voc_flag.name, ".slack_sent_voc_daily_2026-04-17.flag")
        self.assertEqual(anomaly_flag.name, ".slack_sent_anomaly_daily_2026-04-17.flag")
        self.assertNotIn(report_flag, {voc_flag, anomaly_flag})

    def test_send_voc_alerts_is_idempotent_on_second_call(self):
        analysis = {
            "voc_summary": {
                "weak_signals": [{"topic_code": "app_bug", "count": 5}],
                "churn_risk_calls": [],
            }
        }
        with mock.patch.object(notifier, "_post_to_slack", return_value=True) as post:
            ok1 = notifier.send_voc_alerts(analysis, mode="daily", date=self.date)
            ok2 = notifier.send_voc_alerts(analysis, mode="daily", date=self.date)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertEqual(post.call_count, 1, "VoC Slack doit être posté une seule fois même après rerun")
        self.assertTrue(notifier._slack_already_sent("voc", "daily", self.date))

    def test_send_anomaly_alerts_is_idempotent_on_second_call(self):
        analysis = {
            "anomalies": [
                {
                    "metric": "pickup_rate",
                    "scope": "global",
                    "agent_id": "",
                    "z_score": -2.4,
                    "current_value": 55,
                    "baseline_mean": 72,
                    "representative_call_ids": ["abc", "def"],
                }
            ]
        }
        with mock.patch.object(notifier, "_post_to_slack", return_value=True) as post:
            ok1 = notifier.send_anomaly_alerts(analysis, date=self.date)
            ok2 = notifier.send_anomaly_alerts(analysis, date=self.date)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertEqual(post.call_count, 1, "Anomalies Slack doivent être postées une seule fois même après rerun")
        self.assertTrue(notifier._slack_already_sent("anomaly", "daily", self.date))

    def test_flag_not_set_when_post_fails(self):
        """Si l'envoi Slack échoue, le flag ne doit pas être posé — sinon
        on perdrait définitivement le signal sur un rerun."""
        analysis = {
            "voc_summary": {
                "weak_signals": [{"topic_code": "app_bug", "count": 5}],
                "churn_risk_calls": [],
            }
        }
        with mock.patch.object(notifier, "_post_to_slack", return_value=False):
            notifier.send_voc_alerts(analysis, mode="daily", date=self.date)
        self.assertFalse(notifier._slack_already_sent("voc", "daily", self.date))

    def test_aircall_links_use_assets_domain(self):
        link = notifier._aircall_link("3767111602")
        self.assertIn("https://assets.aircall.io/calls/3767111602/recording/info", link)
        self.assertNotIn("https://asset.aircall.io/calls/3767111602/recording/info", link)

    def test_daily_slack_uses_call_reasons_without_churn_risk_block(self):
        analysis = {
            "kpis": {"calls_presented": 1, "calls_answered": 1, "answerable_calls": 1},
            "scores": {},
            "top_problematic_calls": [],
            "kb_gaps": {"missing": [], "incomplete": [], "to_revise": []},
            "voc_summary": {
                "call_reasons": [
                    {
                        "label": "Interruption de charge",
                        "count": 2,
                        "subreasons": [{"label": "TPE / CB", "count": 1}],
                    }
                ],
                "top_topics": [{"label": "Voix du client legacy", "count": 9}],
                "churn_risk_typology": {"eleve": 6, "modere": 45, "total": 51},
            },
        }

        blocks = notifier.build_slack_blocks(analysis, "daily", self.date, calls=[])
        text = "\n".join(
            block.get("text", {}).get("text", "")
            for block in blocks
            if isinstance(block.get("text"), dict)
        )

        self.assertIn("Raisons principales d’appel", text)
        self.assertIn("Interruption de charge", text)
        self.assertIn("TPE / CB: 1", text)
        self.assertIn("Problématiques clients détectées", text)
        self.assertIn("Voix du client", text)
        self.assertNotIn("Risque client détecté", text)

    def test_weekly_voc_side_post_is_suppressed(self):
        analysis = {
            "voc_summary": {
                "call_reasons": [{"label": "Interruption de charge", "count": 3}],
                "weak_signals": [{"topic_code": "interruption_charge", "count": 3}],
            }
        }
        with mock.patch.object(notifier, "_post_to_slack", return_value=True) as post:
            ok = notifier.send_voc_alerts(analysis, mode="weekly", date=self.date)
        self.assertTrue(ok)
        post.assert_not_called()
        self.assertFalse(notifier._slack_already_sent("voc", "weekly", self.date))

    def test_weekly_slack_does_not_duplicate_reason_blocks(self):
        analysis = {
            "kpis": {"calls_presented": 3, "calls_answered": 2, "answerable_calls": 3},
            "scores": {},
            "call_evaluations": [{"call_id": "1", "customer_call_reason": "Interruption de charge"}],
            "top_problematic_calls": [],
            "kb_gaps": {"missing": [], "incomplete": [], "to_revise": []},
            "voc_summary": {
                "call_reasons": [{"label": "Interruption de charge", "count": 1}],
                "top_topics": [
                    {"topic_code": "interruption_charge", "count": 1},
                    {"topic_code": "app_bug", "label": "App bug", "count": 2},
                ],
            },
        }

        blocks = notifier.build_slack_blocks(analysis, "weekly", self.date, calls=[])
        text = "\n".join(
            block.get("text", {}).get("text", "")
            for block in blocks
            if isinstance(block.get("text"), dict)
        )

        self.assertIn("Raisons principales d’appel", text)
        self.assertNotIn("Pourquoi les clients ont appelé", text)
        self.assertNotIn("interruption_charge", text)
        self.assertEqual(text.count("Interruption de charge"), 1)


if __name__ == "__main__":
    unittest.main()
