import unittest
from datetime import datetime

import metrics_builder


class MetricsBuilderTest(unittest.TestCase):
    def test_repeat_caller_rate_with_future_calls(self):
        calls = [
            {"from_number": "0612345678"},
            {"from_number": "0699999999"},
        ]
        future_calls = [
            {"from_number": "0612345678"},
        ]
        self.assertEqual(metrics_builder.repeat_caller_rate(calls, future_calls=future_calls), 50.0)

    def test_build_agent_daily_snapshots(self):
        calls = [
            {
                "call_id_internal": "1",
                "call_id": "1",
                "user_id": 42,
                "user_name": "Jane Doe",
                "answered": "Yes",
                "duration_in_call": 120,
                "classified_type": "ucc_handled",
                "from_number": "0612345678",
            },
            {
                "call_id_internal": "2",
                "call_id": "2",
                "user_id": 42,
                "user_name": "Jane Doe",
                "answered": "No",
                "duration_in_call": 0,
                "classified_type": "abandoned",
                "from_number": "0611111111",
            },
        ]
        evaluations = [
            {"call_id": "1", "soft_skills": {"note_globale": 8.0}, "kb_compliance": "conforme", "improvement_items": []},
        ]
        snapshots = metrics_builder.build_agent_daily_snapshots(calls, evaluations)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["agent_id"], "aircall:42")
        self.assertEqual(snapshots[0]["calls_presented"], 2)
        self.assertEqual(snapshots[0]["avg_soft_score"], 8.0)

    def test_detect_snapshot_anomalies(self):
        history = [
            {"date": f"2026-04-0{i}", "pickup_rate": 90.0, "abandon_rate": 5.0, "avg_soft_score": 8.0}
            for i in range(1, 8)
        ]
        history.append({"date": "2026-04-08", "pickup_rate": 89.0, "abandon_rate": 6.0, "avg_soft_score": 7.8})
        anomalies = metrics_builder.detect_snapshot_anomalies(
            datetime(2026, 4, 17),
            "global",
            "",
            {"pickup_rate": 60.0, "abandon_rate": 5.0, "avg_soft_score": 8.0},
            history,
            [{"call_id_internal": "1", "call_id": "1", "answered": "No"}],
            [],
        )
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["metric"], "pickup_rate")

    def test_cluster_kb_gaps(self):
        evaluations = [
            {
                "call_id": "1",
                "improvement_items": [
                    {"text": "Absence de procédure remboursement charge interrompue", "kb_reference": None},
                    {"text": "Absence de procédure remboursement charge interrompue", "kb_reference": None},
                ],
            }
        ]
        clusters = metrics_builder.cluster_kb_gaps(evaluations)
        self.assertEqual(clusters[0]["frequency"], 2)
        self.assertIn("1", clusters[0]["example_call_ids"])


if __name__ == "__main__":
    unittest.main()
