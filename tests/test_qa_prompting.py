import unittest

import qa_prompting


class QaPromptingTest(unittest.TestCase):
    def test_scoring_examples_are_valid_json(self):
        examples = qa_prompting.load_scoring_examples()
        self.assertEqual(len(examples), 3)
        for example in examples:
            self.assertIn("request", example)
            self.assertIn("response", example)


if __name__ == "__main__":
    unittest.main()
