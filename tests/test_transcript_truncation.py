"""Tests de la troncature intelligente début+fin (chantier 0.2)."""
import unittest

import call_fetcher


class SmartTruncateTest(unittest.TestCase):
    def test_short_text_unchanged(self):
        t = "bonjour " * 10
        self.assertEqual(call_fetcher.smart_truncate_transcript(t, 5000), t)

    def test_none_and_empty(self):
        self.assertIsNone(call_fetcher.smart_truncate_transcript(None, 5000))
        self.assertEqual(call_fetcher.smart_truncate_transcript("", 5000), "")

    def test_keeps_head_and_tail(self):
        text = "DEBUT_" + ("x" * 9000) + "_FIN"
        out = call_fetcher.smart_truncate_transcript(text, 2000)
        self.assertLessEqual(len(out), 2000)
        self.assertTrue(out.startswith("DEBUT_"))      # contexte préservé
        self.assertTrue(out.endswith("_FIN"))          # clôture préservée
        self.assertIn("tronqué", out)                   # marqueur de coupe médiane

    def test_floor_500(self):
        text = "a" * 4000
        out = call_fetcher.smart_truncate_transcript(text, 100)  # sous le plancher
        self.assertLessEqual(len(out), 500)


if __name__ == "__main__":
    unittest.main()
