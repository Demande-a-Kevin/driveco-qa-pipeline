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


if __name__ == "__main__":
    unittest.main()
