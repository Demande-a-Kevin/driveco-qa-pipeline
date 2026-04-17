import unittest
from unittest import mock

import ollama_client
import schemas


class OllamaClientTest(unittest.TestCase):
    def test_chat_forces_zero_temperature_in_json_mode(self):
        response = mock.Mock()
        response.json.return_value = {"message": {"content": "{\"ok\":true}"}}
        response.raise_for_status.return_value = None

        with mock.patch.object(ollama_client._SESSION, "post", return_value=response) as mocked_post:
            ollama_client._chat(
                model="gemma4:latest",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=123,
                timeout=45,
                json_mode=True,
            )

        payload = mocked_post.call_args.kwargs["json"]
        self.assertEqual(payload["options"]["temperature"], 0.0)
        self.assertEqual(payload["options"]["num_predict"], 123)
        self.assertEqual(mocked_post.call_args.kwargs["timeout"], 45)

    def test_analyze_batch_keeps_valid_calls_when_one_call_fails(self):
        schemas.reset_clip_stats()
        batch_stats = {}
        calls = [
            {"call_id_internal": "ok-1", "call_id": "ok-1", "transcript": "[Client] Bonjour"},
            {"call_id_internal": "ko-2", "call_id": "ko-2", "transcript": "[Client] Bonjour"},
        ]

        with mock.patch("ollama_client._prepare_transcript_for_ollama", side_effect=lambda text: text):
            with mock.patch(
                "ollama_client._analyze_single_call",
                side_effect=[
                    {"call_id": "ok-1", "_model": "gemma4:latest"},
                    ValueError("json_invalid"),
                ],
            ):
                evaluations = ollama_client.analyze_batch(
                    "system",
                    calls,
                    "kb",
                    "16/04/2026",
                    stats=batch_stats,
                )

        self.assertEqual(len(evaluations), 1)
        self.assertEqual(evaluations[0]["call_id"], "ok-1")
        self.assertEqual(batch_stats["calls_total"], 2)
        self.assertEqual(batch_stats["calls_succeeded"], 1)
        self.assertEqual(batch_stats["calls_failed"], 1)
        self.assertEqual(batch_stats["failure_reasons"]["json_invalid"], 1)


if __name__ == "__main__":
    unittest.main()
