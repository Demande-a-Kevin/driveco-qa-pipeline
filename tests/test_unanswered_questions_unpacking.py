import unittest
from hashlib import sha256

import persistence


class UnpackUnansweredQuestionsTest(unittest.TestCase):
    def test_inserts_distinct_rows_with_hashes(self):
        captured: list[list[dict]] = []

        def fake_insert(rows):
            captured.append(rows)
            return True

        evaluation = {
            "unanswered_questions": [
                "Le client demande si la borne X est compatible avec une 3.7 kW.",
                "Le client demande quel est le délai de remboursement.",
                "Le client demande comment résilier son abonnement.",
            ],
        }
        n = persistence.unpack_unanswered_questions(
            evaluation,
            call_id="call:123",
            llm_run_id="run:test:1",
            raised_at="2026-05-20T08:30:00+00:00",
            insert_fn=fake_insert,
        )
        self.assertEqual(n, 3)
        self.assertEqual(len(captured), 1)
        rows = captured[0]
        self.assertEqual(len(rows), 3)

        # Vérifie les champs et hashes distincts
        hashes = {r["question_hash"] for r in rows}
        self.assertEqual(len(hashes), 3)
        for q, row in zip(evaluation["unanswered_questions"], rows):
            self.assertEqual(row["call_id"], "call:123")
            self.assertEqual(row["llm_run_id"], "run:test:1")
            self.assertEqual(row["raised_at"], "2026-05-20T08:30:00+00:00")
            self.assertEqual(row["question_text"], q)
            expected = sha256(q.lower().strip().encode("utf-8")).hexdigest()
            self.assertEqual(row["question_hash"], expected)

    def test_empty_or_missing_inserts_zero_rows(self):
        captured: list[list[dict]] = []

        def fake_insert(rows):
            captured.append(rows)
            return True

        # Cas 1 : champ absent
        n1 = persistence.unpack_unanswered_questions(
            {},
            call_id="call:abc",
            llm_run_id="run:test:2",
            raised_at="2026-05-20T08:30:00+00:00",
            insert_fn=fake_insert,
        )
        # Cas 2 : champ présent mais vide
        n2 = persistence.unpack_unanswered_questions(
            {"unanswered_questions": []},
            call_id="call:abc",
            llm_run_id="run:test:2",
            raised_at="2026-05-20T08:30:00+00:00",
            insert_fn=fake_insert,
        )
        # Cas 3 : que des strings vides → 0 rows
        n3 = persistence.unpack_unanswered_questions(
            {"unanswered_questions": ["", "   ", None]},
            call_id="call:abc",
            llm_run_id="run:test:2",
            raised_at="2026-05-20T08:30:00+00:00",
            insert_fn=fake_insert,
        )
        self.assertEqual(n1, 0)
        self.assertEqual(n2, 0)
        self.assertEqual(n3, 0)
        self.assertEqual(captured, [])  # aucun appel à l'insert


if __name__ == "__main__":
    unittest.main()
