import unittest
from unittest import mock

import persistence


class PersistenceHelpersTest(unittest.TestCase):
    def test_canonical_ids(self):
        call = {
            "call_id_internal": "123",
            "call_id": "abc",
            "user_id": 42,
            "user_name": "Jane Doe",
        }
        self.assertEqual(persistence.canonical_call_id(call), "123")
        self.assertEqual(persistence.canonical_aircall_id(call), "abc")
        self.assertEqual(persistence.canonical_agent_id(call), "aircall:42")

    def test_build_diarization(self):
        transcript = "[Agent] Bonjour\n[Client] Je ne peux pas charger"
        diarization = persistence.build_diarization(transcript)
        self.assertEqual(len(diarization), 2)
        self.assertEqual(diarization[0]["speaker"], "agent")
        self.assertEqual(diarization[1]["speaker"], "client")

    def test_disabled_supabase_is_noop(self):
        with mock.patch("persistence.SUPABASE_AVAILABLE", False):
            self.assertFalse(persistence.is_enabled())
            self.assertIsNone(persistence.upsert_call({"call_id_internal": "1"}))
            self.assertFalse(
                persistence.save_llm_run(
                    {
                        "id": "run:test",
                        "started_at": "2026-04-16T00:00:00+00:00",
                        "status": "started",
                    }
                )
            )


if __name__ == "__main__":
    unittest.main()
