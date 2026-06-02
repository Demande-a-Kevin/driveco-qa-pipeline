import json
import unittest
from pathlib import Path

import schemas


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class SchemaValidationTest(unittest.TestCase):
    def test_fixture_cases_build_valid_call_evaluations(self):
        fixture_paths = sorted(FIXTURES_DIR.glob("ollama_case_*.json"))
        self.assertEqual(len(fixture_paths), 5)

        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                payload = json.loads(fixture_path.read_text(encoding="utf-8"))
                call = payload["call"]
                factual_extract = schemas.FactualExtract.model_validate(payload["factual_extract"])
                scorecard = schemas.CriterionScorecard.model_validate(payload["scorecard"])
                expected = payload["expected"]

                evaluation = schemas.build_call_evaluation(
                    call=call,
                    factual_extract=factual_extract,
                    scorecard=scorecard,
                    model_name="gemma4:latest",
                )

                self.assertEqual(len(evaluation.errors), expected["errors_count"])
                self.assertEqual(len(evaluation.validation_warnings), expected["warnings_count"])
                self.assertEqual(evaluation.score_global, expected["score_global"])
                self.assertEqual(evaluation.soft_skills.note_globale, expected["score_global"])
                self.assertEqual(evaluation.rubric_version, "qa_rubric_v1")

    def test_strict_json_parser_rejects_non_object_json(self):
        with self.assertRaises(ValueError):
            schemas.parse_json_strict('["not-an-object"]')

    def test_truncates_long_text_fields_deterministically(self):
        long_text = "x" * 400
        evidence = schemas.EvidenceItem.model_validate(
            {
                "text": long_text,
                "citation": long_text,
                "kb_reference": long_text,
            }
        )
        kb = schemas.KBCompliance.model_validate(
            {
                "status": "conforme",
                "article": long_text,
                "rationale": long_text,
            }
        )

        self.assertEqual(len(evidence.text), 240)
        self.assertTrue(evidence.text.endswith("…"))
        self.assertEqual(len(evidence.citation), 160)
        self.assertTrue(evidence.citation.endswith("…"))
        self.assertEqual(len(kb.rationale), 240)
        self.assertTrue(kb.rationale.endswith("…"))

    def test_strict_json_parser_repairs_common_invalid_json(self):
        payload = schemas.parse_json_strict('{"call_id":"1","classified_type":"ucc_handled",}')
        self.assertEqual(payload["call_id"], "1")
        self.assertEqual(payload["classified_type"], "ucc_handled")

    def test_resolution_status_accepts_expected_values(self):
        for value in ("resolved", "escalated", "pending"):
            with self.subTest(value=value):
                extract = schemas.FactualExtract.model_validate(
                    {
                        "call_id": "1",
                        "classified_type": "ucc_handled",
                        "customer_call_reason": "Charge interrompue",
                        "transcript_usable": True,
                        "kb_compliance": {"status": "conforme", "article": "KB-1", "rationale": "ok"},
                        "positives": [],
                        "improvement_points": [],
                        "alerts": [],
                        "procedural_steps_followed": [],
                        "emotional_signals": [],
                        "resolution_status": value,
                    }
                )
                self.assertEqual(extract.resolution_status, value)

    def test_voc_best_practice_moments_are_limited(self):
        voc = schemas.VoCExtract.model_validate(
            {
                "topics": [],
                "entity_perceptions": [],
                "customer_emotions": ["satisfaction"],
                "effort_score": 1,
                "satisfaction_signal": "positif",
                "churn_risk_signal": "aucun",
                "expansion_signal": True,
                "resolution_status": "resolved",
                "competitor_mentions": [],
                "verbatim_quotes": [],
                "best_practice_moments": [
                    {"quote": "Le support a été très clair", "timestamp_s": None, "speaker": "client", "topic_code": "feedback_positif", "sentiment": "très_positif"}
                ],
                "unmet_needs": [],
                "product_ideas": [],
                "taxonomy_version": "voc_taxonomy_v1",
                "needs_taxonomy_review": False,
                "validation_warnings": [],
            }
        )
        self.assertEqual(len(voc.best_practice_moments), 1)

    def test_voc_effort_score_accepts_numeric_strings(self):
        voc = schemas.VoCExtract.model_validate(
            {
                "topics": [],
                "entity_perceptions": [],
                "customer_emotions": ["satisfaction"],
                "effort_score": "3",
                "satisfaction_signal": "neutre",
                "churn_risk_signal": "faible",
                "expansion_signal": False,
                "resolution_status": "pending",
                "competitor_mentions": [],
                "verbatim_quotes": [],
                "best_practice_moments": [],
                "unmet_needs": [],
                "product_ideas": [],
                "taxonomy_version": "voc_taxonomy_v1",
                "needs_taxonomy_review": False,
                "validation_warnings": [],
            }
        )
        self.assertEqual(voc.effort_score, 3)

    def test_voc_customer_emotions_discards_invalid_values(self):
        voc = schemas.VoCExtract.model_validate(
            {
                "topics": [],
                "entity_perceptions": [],
                "customer_emotions": ["Satisfaction", "urgence", "confusion", ""],
                "effort_score": 2,
                "satisfaction_signal": "neutre",
                "churn_risk_signal": "faible",
                "expansion_signal": False,
                "resolution_status": "pending",
                "competitor_mentions": [],
                "verbatim_quotes": [],
                "best_practice_moments": [],
                "unmet_needs": [],
                "product_ideas": [],
                "taxonomy_version": "voc_taxonomy_v1",
                "needs_taxonomy_review": False,
                "validation_warnings": [],
            }
        )
        self.assertEqual(voc.customer_emotions, ["satisfaction", "confusion"])

    def test_scorecard_accepts_string_null_for_optional_scores(self):
        scorecard = schemas.CriterionScorecard.model_validate(
            {
                "accueil": "null",
                "ecoute_active": "8",
                "empathie": "",
                "gestion_tension": "n/a",
                "professionnalisme": None,
                "clarte_communication": 7,
                "orientation_solution": "6.5",
                "cloture": "none",
                "qualification_investigation": "9",
                "kb_application": "null",
                "observations": "ok",
            }
        )
        self.assertIsNone(scorecard.accueil)
        self.assertEqual(scorecard.ecoute_active, 8)
        self.assertIsNone(scorecard.empathie)
        self.assertIsNone(scorecard.gestion_tension)
        self.assertEqual(scorecard.orientation_solution, 6.5)
        self.assertIsNone(scorecard.cloture)
        self.assertIsNone(scorecard.kb_application)


if __name__ == "__main__":
    unittest.main()
