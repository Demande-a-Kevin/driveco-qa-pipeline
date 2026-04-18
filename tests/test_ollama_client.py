import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import config
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


class AnalysisCacheTest(unittest.TestCase):
    """Cache idempotent des analyses QA : un rerun sur la même date ne doit
    pas repayer le temps Ollama."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patches = [
            mock.patch.object(config, "LLM_CACHE_DIR", Path(self._tmp.name)),
            mock.patch.object(config, "LLM_CACHE_ENABLED", True),
            mock.patch.object(config, "LLM_ANALYSIS_CACHE_VERSION", "test-v1"),
            mock.patch.object(config, "OLLAMA_MODEL_ANALYSIS", "gemma4:latest"),
            mock.patch.object(config, "ENABLE_VOC_ANALYSIS", False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_cache_roundtrip_same_inputs(self):
        call = {"call_id": "c1", "transcript": "[Client] Bonjour"}
        key = ollama_client._cache_key(call, "kb:excerpt")
        self.assertIsNone(ollama_client._cache_get(key))
        ollama_client._cache_put(key, {"call_id": "c1", "_model": "gemma4:latest"})
        self.assertEqual(ollama_client._cache_get(key)["call_id"], "c1")

    def test_cache_key_changes_when_transcript_differs(self):
        k1 = ollama_client._cache_key({"transcript": "A"}, "kb")
        k2 = ollama_client._cache_key({"transcript": "B"}, "kb")
        self.assertNotEqual(k1, k2)

    def test_cache_key_changes_when_version_bumped(self):
        call = {"transcript": "same"}
        k1 = ollama_client._cache_key(call, "kb")
        with mock.patch.object(config, "LLM_ANALYSIS_CACHE_VERSION", "test-v2"):
            k2 = ollama_client._cache_key(call, "kb")
        self.assertNotEqual(k1, k2)

    def test_cache_disabled_skips_reads_and_writes(self):
        call = {"transcript": "x"}
        key = ollama_client._cache_key(call, "kb")
        with mock.patch.object(config, "LLM_CACHE_ENABLED", False):
            ollama_client._cache_put(key, {"call_id": "x"})
        self.assertEqual(list(Path(self._tmp.name).iterdir()), [])


class DailyCapTest(unittest.TestCase):
    """Cap dur sur le nombre d'appels QA analysés en daily."""

    def test_select_calls_applies_max_calls_after_stratification(self):
        import analysis_pipeline
        calls = [
            {"call_id": f"c{i}", "call_id_internal": f"c{i}",
             "answered": "Yes", "duration_in_call": 300 + i, "tags": ""}
            for i in range(60)
        ]
        selected = analysis_pipeline.select_calls_for_analysis(
            calls, coverage_pct=0.75, max_calls=35,
        )
        self.assertEqual(len(selected), 35)

    def test_select_calls_no_cap_when_max_is_none(self):
        import analysis_pipeline
        calls = [
            {"call_id": f"c{i}", "call_id_internal": f"c{i}",
             "answered": "Yes", "duration_in_call": 300 + i, "tags": ""}
            for i in range(20)
        ]
        selected = analysis_pipeline.select_calls_for_analysis(
            calls, coverage_pct=0.75, max_calls=None,
        )
        self.assertEqual(len(selected), 15)  # 75% de 20


if __name__ == "__main__":
    unittest.main()
