"""Tests de la fenêtre de pause nocturne des jobs Insight (chantier 0.1)."""
import datetime
import unittest
from unittest import mock

import config
import csat_insight
import sentiment_insight


def _at(h, m=0):
    return datetime.datetime(2026, 6, 13, h, m, 0)


class InsightPauseWindowTest(unittest.TestCase):
    def test_overnight_window_pauses_at_night(self):
        with mock.patch.object(config, "INSIGHT_PAUSE_WINDOW", "23:00-08:00"):
            # Dans la fenêtre (enjambe minuit)
            self.assertTrue(config.insight_paused_now(_at(23, 30)))
            self.assertTrue(config.insight_paused_now(_at(2, 0)))
            self.assertTrue(config.insight_paused_now(_at(7, 59)))
            self.assertTrue(config.insight_paused_now(_at(23, 0)))   # borne basse incluse
            # Hors fenêtre
            self.assertFalse(config.insight_paused_now(_at(8, 0)))   # reprise inconditionnelle
            self.assertFalse(config.insight_paused_now(_at(12, 0)))
            self.assertFalse(config.insight_paused_now(_at(22, 59)))

    def test_same_day_window(self):
        with mock.patch.object(config, "INSIGHT_PAUSE_WINDOW", "01:00-03:00"):
            self.assertTrue(config.insight_paused_now(_at(2, 0)))
            self.assertFalse(config.insight_paused_now(_at(0, 30)))
            self.assertFalse(config.insight_paused_now(_at(3, 0)))

    def test_empty_or_invalid_window_never_pauses(self):
        for val in ("", "garbage", "23:00", "99:99-08:00"):
            with mock.patch.object(config, "INSIGHT_PAUSE_WINDOW", val):
                self.assertFalse(config.insight_paused_now(_at(2, 0)), val)

    def test_csat_run_once_exits_during_pause(self):
        with mock.patch.object(config, "DISABLE_CSAT_INSIGHT", False), \
             mock.patch.object(config, "insight_paused_now", return_value=True), \
             mock.patch.object(csat_insight.csat_state, "load_state") as load_state:
            csat_insight.run_once()
        load_state.assert_not_called()  # sortie avant tout traitement

    def test_sentiment_run_once_exits_during_pause(self):
        with mock.patch.object(config, "DISABLE_SENTIMENT_INSIGHT", False), \
             mock.patch.object(config, "insight_paused_now", return_value=True), \
             mock.patch.object(sentiment_insight.csat_state, "load_state") as load_state:
            sentiment_insight.run_once()
        load_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
