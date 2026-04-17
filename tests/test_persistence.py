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

    def test_save_voc_extract_upserts_product_ideas_without_double_counting_rerun(self):
        with mock.patch("persistence._seed_voc_taxonomy_once"), \
             mock.patch("persistence._call_rgpd_opt_out", return_value=False), \
             mock.patch("persistence._execute_delete", return_value=True), \
             mock.patch("persistence._execute_upsert", return_value=True) as upsert_mock, \
             mock.patch("persistence._find_existing_signal") as existing_mock:
            existing_mock.side_effect = [
                None,
                {
                    "id": "voc_signal:product_idea:abc",
                    "description": "Ajouter une alerte proactive",
                    "frequency": 1,
                    "source_call_ids": ["call-1"],
                    "status": "new",
                    "first_seen": "2026-04-16",
                    "last_seen": "2026-04-16",
                    "tags": ["produit"],
                },
            ]
            call = {"call_id_internal": "call-1", "user_id": 7, "user_name": "Alice", "phone_e164": "+33612345678"}
            voc_extract = {
                "topics": [],
                "entity_perceptions": [],
                "customer_emotions": ["satisfaction"],
                "effort_score": 1,
                "satisfaction_signal": "positif",
                "churn_risk_signal": "aucun",
                "expansion_signal": False,
                "resolution_status": "resolved",
                "competitor_mentions": [],
                "verbatim_quotes": [],
                "best_practice_moments": [],
                "unmet_needs": [],
                "product_ideas": ["Ajouter une alerte proactive"],
                "taxonomy_version": "voc_taxonomy_v1",
                "validation_warnings": [],
            }

            persistence.save_voc_extract("eval:call-1", call, voc_extract)
            persistence.save_voc_extract("eval:call-1", call, voc_extract)

        voc_signal_payloads = [
            call.args[1]
            for call in upsert_mock.call_args_list
            if call.args and call.args[0] == "voc_signals"
        ]
        self.assertGreaterEqual(len(voc_signal_payloads), 2)
        self.assertEqual(voc_signal_payloads[-1]["frequency"], 1)


if __name__ == "__main__":
    unittest.main()
