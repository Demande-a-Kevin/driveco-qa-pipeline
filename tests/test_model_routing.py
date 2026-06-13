"""Tests du routage hybride de modèle (4B volume / 12B haut risque) — direction Maui."""
import unittest
from unittest import mock

import config
import ollama_client


class ModelOverrideTest(unittest.TestCase):
    def tearDown(self):
        ollama_client._active_analysis_model = None

    def test_default_is_analysis_model(self):
        ollama_client._active_analysis_model = None
        self.assertEqual(ollama_client._analysis_model(), config.OLLAMA_MODEL_ANALYSIS)

    def test_override_applies(self):
        ollama_client._active_analysis_model = "gemma4:12b"
        self.assertEqual(ollama_client._analysis_model(), "gemma4:12b")

    def test_cache_key_depends_on_active_model(self):
        call = {"transcript": "[Client] bonjour\n[Agent] bonjour"}
        ollama_client._active_analysis_model = "gemma3:4b"
        k4 = ollama_client._cache_key(call)
        ollama_client._active_analysis_model = "gemma4:12b"
        k12 = ollama_client._cache_key(call)
        self.assertNotEqual(k4, k12)  # pas de collision de cache entre modèles

    def test_analyze_batch_sets_active_model(self):
        # On mocke l'analyse unitaire pour ne pas toucher Ollama.
        captured = {}

        def fake_single(call, kb, stats=None):
            captured["model"] = ollama_client._analysis_model()
            return {"call_id": call.get("call_id"), "score_global": 8}

        with mock.patch.object(ollama_client, "_analyze_single_call", side_effect=fake_single):
            ollama_client.analyze_batch(
                "sys", [{"call_id": "1", "transcript": "[Client] x\n[Agent] y"}],
                "kb", "01/01/2026", model="gemma4:12b",
            )
        self.assertEqual(captured["model"], "gemma4:12b")


class FlaggedConfigTest(unittest.TestCase):
    def test_flagged_model_defined(self):
        self.assertTrue(hasattr(config, "OLLAMA_MODEL_FLAGGED"))
        self.assertTrue(config.OLLAMA_MODEL_FLAGGED)


if __name__ == "__main__":
    unittest.main()
