import unittest

import reliability


class ReliabilityTest(unittest.TestCase):
    def test_gold_set_has_twenty_entries(self):
        self.assertEqual(len(reliability.load_gold_set()), 20)
        self.assertGreaterEqual(len(reliability.usable_gold_entries()), 5)

    def test_compute_reliability_metrics(self):
        scored_rows = [
            {
                "entry": {
                    "human_score": 8.0,
                    "voc_topics": [{"topic_code": "app_bug"}],
                    "voc_entities": [{"entity_code": "app_mobile", "sentiment": "négatif"}],
                    "key_verbatims": ["application plante"],
                },
                "evaluation": {
                    "score_global": 7.5,
                    "voc_extract": {
                        "topics": [{"topic_code": "app_bug"}],
                        "entity_perceptions": [{"entity_code": "app_mobile", "sentiment": "négatif"}],
                        "verbatim_quotes": [{"quote": "application plante"}],
                    },
                },
            },
            {
                "entry": {
                    "human_score": 6.0,
                    "voc_topics": [{"topic_code": "facturation"}],
                    "voc_entities": [{"entity_code": "processus_facturation", "sentiment": "négatif"}],
                    "key_verbatims": ["facture de mars"],
                },
                "evaluation": {
                    "score_global": 6.5,
                    "voc_extract": {
                        "topics": [{"topic_code": "facturation"}],
                        "entity_perceptions": [{"entity_code": "processus_facturation", "sentiment": "négatif"}],
                        "verbatim_quotes": [{"quote": "facture de mars"}],
                    },
                },
            },
        ]
        metrics = reliability.compute_reliability_metrics(scored_rows)
        self.assertEqual(metrics.entries_used, 2)
        self.assertEqual(metrics.mae, 0.5)
        self.assertIsNotNone(metrics.pearson)
        self.assertEqual(metrics.topic_f1, 1.0)
        self.assertEqual(metrics.verbatim_recall, 1.0)


if __name__ == "__main__":
    unittest.main()
