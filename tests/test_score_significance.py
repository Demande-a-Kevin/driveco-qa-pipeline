"""Tests affichage honnête des scores QA sous-effectif (chantier 0.5)."""
import unittest
from unittest import mock

import config
import notifier


class ScoreSignificanceTest(unittest.TestCase):
    def test_low_n_forces_white_icon(self):
        with mock.patch.object(config, "SCORE_MIN_N", 10):
            # n=4 sous le seuil → ⚪ même si le score serait rouge
            self.assertEqual(notifier._score_icon_n(4.2, 4), "⚪")
            # n suffisant → couleur réelle
            self.assertEqual(notifier._score_icon_n(9.0, 25), "🟢")
            self.assertEqual(notifier._score_icon_n(4.2, 25), "🔴")
            # n manquant → ⚪
            self.assertEqual(notifier._score_icon_n(9.0, None), "⚪")

    def test_score_text_shows_n(self):
        self.assertEqual(notifier._score_text_n(4.2, 4), "4.2/10 (n=4)")
        self.assertEqual(notifier._score_text_n("?", None), "n/a")

    def test_runtime_config_summary_is_informative(self):
        s = config.runtime_config_summary()
        self.assertIn("modèle=", s)
        self.assertIn("num_ctx=", s)
        self.assertIn("budget=", s)
        self.assertIn("couverture_cible=", s)


if __name__ == "__main__":
    unittest.main()
