"""Tests du rattrapage de couverture (chantier 0.6)."""
import datetime
import unittest
from pathlib import Path
from unittest import mock

import catchup_state
import analysis_pipeline


class CatchupStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(__file__).parent / "_tmp_catchup"
        self._tmp.mkdir(exist_ok=True)
        self._patch = mock.patch.object(catchup_state, "_DIR", self._tmp)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for f in self._tmp.glob("*"):
            f.unlink()
        self._tmp.rmdir()

    def test_pending_roundtrip_and_clear(self):
        d = datetime.datetime(2026, 6, 12)
        catchup_state.save_pending(d, ["a", "b", "c"])
        self.assertEqual(set(catchup_state.load_pending(d)), {"a", "b", "c"})
        remaining = catchup_state.clear_pending(d, ["a", "c"])
        self.assertEqual(remaining, ["b"])
        self.assertEqual(catchup_state.load_pending(d), ["b"])

    def test_empty_pending_removes_file(self):
        d = datetime.datetime(2026, 6, 12)
        catchup_state.save_pending(d, ["x"])
        catchup_state.save_pending(d, [])
        self.assertEqual(catchup_state.load_pending(d), [])

    def test_slack_ref_roundtrip(self):
        d = datetime.datetime(2026, 6, 12)
        self.assertIsNone(catchup_state.load_daily_slack_ref(d))
        catchup_state.save_daily_slack_ref(d, "C123", "1781219654.5")
        self.assertEqual(catchup_state.load_daily_slack_ref(d), ("C123", "1781219654.5"))

    def test_slack_ref_ignores_non_string_ts(self):
        d = datetime.datetime(2026, 6, 12)
        catchup_state.save_daily_slack_ref(d, "C123", True)  # ts indisponible (Slack désactivé)
        self.assertIsNone(catchup_state.load_daily_slack_ref(d))


class PersistPendingTest(unittest.TestCase):
    def test_pending_is_selected_minus_evaluated(self):
        calls = [{"call_id": "1"}, {"call_id": "2"}, {"call_id": "3"}]
        analysis = {"call_evaluations": [{"call_id": "1"}]}  # seul l'appel 1 évalué
        with mock.patch.object(analysis_pipeline.catchup_state, "save_pending") as save:
            analysis_pipeline._persist_pending_for_catchup(datetime.datetime(2026, 6, 12), calls, analysis)
        save.assert_called_once()
        _, pending = save.call_args.args
        self.assertEqual(set(pending), {"2", "3"})


class RunCatchupNoopTest(unittest.TestCase):
    def test_noop_when_no_pending(self):
        with mock.patch.object(analysis_pipeline.ops_guards, "run_preflight_or_abort"), \
             mock.patch.object(analysis_pipeline, "_sync_kb_if_enabled"), \
             mock.patch.object(analysis_pipeline, "_kb_source") as kb, \
             mock.patch.object(analysis_pipeline.catchup_state, "load_pending", return_value=[]), \
             mock.patch.object(analysis_pipeline.call_fetcher, "fetch_calls_for_date") as fetch:
            kb.return_value.get_kb_summary_for_prompt.return_value = ""
            analysis_pipeline.run_catchup(datetime.datetime(2026, 6, 13))
        fetch.assert_not_called()  # rien à rattraper → pas de fetch


if __name__ == "__main__":
    unittest.main()
