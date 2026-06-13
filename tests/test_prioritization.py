"""Tests de la priorisation des analyses (chantier B.1)."""
import unittest

import analysis_pipeline


def _call(cid, answered="Yes", dur=120, tags="", caller="h", started=0):
    return {"call_id": cid, "answered": answered, "duration_in_call": dur,
            "tags": tags, "caller_hash": caller, "started_at": started}


class PrioritizationTest(unittest.TestCase):
    def test_escalations_first_then_repeat_then_long(self):
        calls = [
            _call("banal", dur=120, caller="solo1", started=10),
            _call("long", dur=900, caller="solo2", started=5),
            _call("repeatA", dur=100, caller="dup", started=1),
            _call("repeatB", dur=100, caller="dup", started=2),  # même caller → repeat
            _call("esc", dur=120, caller="solo3", tags="escalation", started=0),
        ]
        out = analysis_pipeline.select_calls_for_analysis(calls, coverage_pct=1.0)
        order = [c["call_id"] for c in out]
        # escalade en 1er
        self.assertEqual(order[0], "esc")
        # repeat callers avant l'appel long et le banal
        self.assertLess(order.index("repeatA"), order.index("long"))
        self.assertLess(order.index("repeatB"), order.index("long"))
        # long avant le banal de même durée < lui (le banal finit dans le "reste")
        self.assertIn("long", order)
        # couverture 100 % → tous présents
        self.assertEqual(set(order), {"banal", "long", "repeatA", "repeatB", "esc"})

    def test_budget_cut_drops_banal_not_escalation(self):
        # cap à 2 → on garde escalade + repeat, le banal saute (→ rattrapage 0.6)
        calls = [
            _call("banal", dur=120, caller="s1", started=10),
            _call("repeatA", dur=100, caller="dup", started=1),
            _call("repeatB", dur=100, caller="dup", started=2),
            _call("esc", tags="escalation", caller="s3", started=0),
        ]
        out = analysis_pipeline.select_calls_for_analysis(calls, coverage_pct=1.0, max_calls=2)
        order = [c["call_id"] for c in out]
        self.assertEqual(order[0], "esc")
        self.assertNotIn("banal", order)  # le banal est sacrifié, pas l'escalade


if __name__ == "__main__":
    unittest.main()
