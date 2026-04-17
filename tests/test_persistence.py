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

    def test_execute_delete_calls_supabase(self):
        mock_query = mock.Mock()
        mock_query.eq.return_value = mock_query
        mock_table = mock.Mock()
        mock_table.delete.return_value = mock_query
        mock_supa = mock.Mock()
        mock_supa.table.return_value = mock_table

        with mock.patch("persistence.client", return_value=mock_supa):
            result = persistence._execute_delete("issues", evaluation_id="eval:1", type="alert")

        self.assertTrue(result)
        mock_supa.table.assert_called_once_with("issues")
        mock_table.delete.assert_called_once_with()
        self.assertEqual(
            mock_query.eq.call_args_list,
            [
                mock.call("evaluation_id", "eval:1"),
                mock.call("type", "alert"),
            ],
        )
        mock_query.execute.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
