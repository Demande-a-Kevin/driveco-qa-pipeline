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


if __name__ == "__main__":
    unittest.main()
