"""Tests du CSAT du jour (x/5) — agrégation des sondages Sprig (demande Maui)."""
import datetime
import unittest
from unittest import mock

import csat_daily
from csat_parser import CsatPost


def _post(cid, score):
    return CsatPost(ts="x", call_id=cid, score=score, influence="", improvements="", raw_text="")


class DailyCsatTest(unittest.TestCase):
    def _run(self, posts_by_ts, call_ids):
        msgs = [{"ts": k} for k in posts_by_ts]
        with mock.patch.object(csat_daily.config, "DISABLE_CSAT_INSIGHT", False), \
             mock.patch.object(csat_daily.config, "SLACK_CSAT_CHANNEL_ID", "C0B724V5X4L"), \
             mock.patch.object(csat_daily.csat_slack, "fetch_new_sprig_posts", return_value=msgs), \
             mock.patch.object(csat_daily.csat_parser, "parse_sprig",
                               side_effect=lambda m: posts_by_ts[m["ts"]]):
            return csat_daily.daily_csat_for_calls(datetime.datetime(2026, 6, 11), call_ids)

    def test_averages_only_matching_calls(self):
        posts = {"1": _post("100", 5), "2": _post("200", 3), "3": _post("999", 1)}
        res = self._run(posts, {"100", "200"})  # 999 hors périmètre du jour
        self.assertEqual(res["n"], 2)
        self.assertEqual(res["avg"], 4.0)

    def test_no_call_ids_takes_all(self):
        posts = {"1": _post("100", 4), "2": _post("200", 2)}
        res = self._run(posts, set())
        self.assertEqual(res["n"], 2)
        self.assertEqual(res["avg"], 3.0)

    def test_ignores_missing_scores(self):
        posts = {"1": _post("100", None), "2": _post("200", 5)}
        res = self._run(posts, {"100", "200"})
        self.assertEqual(res["n"], 1)
        self.assertEqual(res["avg"], 5.0)

    def test_empty_returns_none(self):
        res = self._run({}, {"100"})
        self.assertIsNone(res["avg"])
        self.assertEqual(res["n"], 0)


class CsatIconTest(unittest.TestCase):
    def test_icon_thresholds(self):
        import notifier
        self.assertEqual(notifier._csat_icon(4.2), "🟢")
        self.assertEqual(notifier._csat_icon(3.0), "🟡")
        self.assertEqual(notifier._csat_icon(2.1), "🔴")
        self.assertEqual(notifier._csat_icon(None), "⚪")


if __name__ == "__main__":
    unittest.main()
