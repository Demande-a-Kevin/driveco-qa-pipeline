import unittest

import metrics_builder
import persistence
import schemas
import voc_taxonomy


class VoCTest(unittest.TestCase):
    def test_unknown_taxonomy_codes_are_flagged(self):
        item = schemas.TopicMention.model_validate(
            {
                "topic_code": "panne inconnue terrain",
                "sentiment": "négatif",
                "severity": 4,
                "quote": "la borne est encore en panne",
            }
        )
        self.assertTrue(item.topic_code.startswith("autre_"))
        self.assertTrue(item.needs_taxonomy_review)

    def test_voc_extract_rejects_missing_quotes_from_transcript(self):
        call = {
            "call_id_internal": "voc-call-1",
            "call_id": "voc-call-1",
            "classified_type": "ucc_handled",
            "duration_in_call": 180,
            "transcript": "[Client] L'application plante au paiement. [Agent] Je vais vérifier. [Client] Merci.",
        }
        factual_extract = schemas.FactualExtract.model_validate(
            {
                "call_id": "voc-call-1",
                "classified_type": "ucc_handled",
                "customer_call_reason": "Bug app",
                "transcript_usable": True,
                "kb_compliance": {"status": "partiel", "article": None, "rationale": None},
                "positives": [],
                "improvement_points": [],
                "alerts": [],
                "procedural_steps_followed": [],
                "emotional_signals": ["frustration"],
            }
        )
        scorecard = schemas.CriterionScorecard.model_validate(
            {
                "accueil": 7,
                "ecoute_active": 7,
                "empathie": 7,
                "gestion_tension": 7,
                "professionnalisme": 7,
                "clarte_communication": 7,
                "orientation_solution": 7,
                "cloture": 7,
                "qualification_investigation": 7,
                "kb_application": 7,
                "observations": "RAS",
            }
        )
        voc_extract = schemas.VoCExtract.model_validate(
            {
                "topics": [
                    {
                        "topic_code": "app_bug",
                        "sentiment": "négatif",
                        "severity": 4,
                        "quote": "L'application plante au paiement",
                    },
                    {
                        "topic_code": "facturation",
                        "sentiment": "négatif",
                        "severity": 3,
                        "quote": "citation absente du transcript",
                    },
                ],
                "entity_perceptions": [],
                "customer_emotions": ["frustration"],
                "effort_score": 4,
                "satisfaction_signal": "négatif",
                "churn_risk_signal": "faible",
                "expansion_signal": False,
                "competitor_mentions": [],
                "verbatim_quotes": [
                    {
                        "quote": "L'application plante au paiement",
                        "speaker": "client",
                        "topic_code": "app_bug",
                        "sentiment": "négatif",
                    },
                    {
                        "quote": "verbatim introuvable",
                        "speaker": "client",
                        "topic_code": "facturation",
                        "sentiment": "négatif",
                    },
                ],
                "unmet_needs": ["Un paiement fiable"],
                "product_ideas": [],
                "taxonomy_version": voc_taxonomy.taxonomy_version(),
            }
        )

        evaluation = schemas.build_call_evaluation(
            call=call,
            factual_extract=factual_extract,
            scorecard=scorecard,
            model_name="gemma4:latest",
            voc_extract=voc_extract,
        )

        self.assertIsNotNone(evaluation.voc_extract)
        self.assertEqual(len(evaluation.voc_extract.topics), 1)
        self.assertEqual(len(evaluation.voc_extract.verbatim_quotes), 1)
        self.assertTrue(any("rejeté" in warning for warning in evaluation.validation_warnings))

    def test_voc_summary_masks_pii(self):
        evaluations = [
            {
                "call_id": "123",
                "voc_extract": {
                    "topics": [
                        {
                            "topic_code": "facturation",
                            "sentiment": "négatif",
                            "severity": 3,
                            "quote": "Mon email est jean.dupont@mail.com",
                            "needs_taxonomy_review": False,
                        }
                    ],
                    "entity_perceptions": [],
                    "customer_emotions": ["confusion"],
                    "effort_score": 3,
                    "satisfaction_signal": "mixte",
                    "churn_risk_signal": "modéré",
                    "expansion_signal": False,
                    "competitor_mentions": [],
                    "verbatim_quotes": [
                        {
                            "quote": "Mon email est jean.dupont@mail.com et mon numéro est 0612345678",
                            "speaker": "client",
                            "topic_code": "facturation",
                            "sentiment": "négatif",
                        }
                    ],
                    "unmet_needs": [],
                    "product_ideas": [],
                    "taxonomy_version": voc_taxonomy.taxonomy_version(),
                    "needs_taxonomy_review": False,
                    "validation_warnings": [],
                },
            }
        ]
        summary = metrics_builder.build_voc_summary(evaluations)
        self.assertEqual(summary["top_topics"][0]["topic_code"], "facturation")
        self.assertIn("[email masqué]", summary["verbatims"][0]["quote"])
        self.assertIn("[téléphone masqué]", summary["verbatims"][0]["quote"])

    def test_voc_summary_builds_granular_call_reasons(self):
        evaluations = [
            {
                "call_id": "1",
                "customer_call_reason": "Charge interrompue avec badge RFID",
                "voc_extract": {
                    "topics": [
                        {
                            "topic_code": "interruption_charge",
                            "sentiment": "négatif",
                            "severity": 4,
                            "quote": "La charge s'arrête avec mon badge Chargemap",
                        },
                        {
                            "topic_code": "badge_tiers",
                            "sentiment": "négatif",
                            "severity": 3,
                            "quote": "Mon badge Chargemap ne relance pas la charge",
                        },
                    ],
                    "entity_perceptions": [],
                    "verbatim_quotes": [],
                },
            },
            {
                "call_id": "2",
                "customer_call_reason": "Paiement TPE refusé",
                "voc_extract": {
                    "topics": [
                        {
                            "topic_code": "app_paiement",
                            "sentiment": "négatif",
                            "severity": 4,
                            "quote": "Le paiement par carte bancaire sur le TPE est refusé",
                        }
                    ],
                    "entity_perceptions": [],
                    "verbatim_quotes": [],
                },
            },
            {
                "call_id": "3",
                "customer_call_reason": "Impossible de trouver la borne sur le parking",
                "voc_extract": {
                    "topics": [
                        {
                            "topic_code": "localisation_borne",
                            "sentiment": "négatif",
                            "severity": 3,
                            "quote": "Je ne trouve pas la borne sur le parking Carrefour",
                        }
                    ],
                    "entity_perceptions": [],
                    "verbatim_quotes": [],
                },
            },
            {
                "call_id": "4",
                "customer_call_reason": "Charge interrompue pendant le paiement",
                "voc_extract": {
                    "topics": [
                        {
                            "topic_code": "interruption_charge",
                            "sentiment": "négatif",
                            "severity": 4,
                            "quote": "La charge s'est arrêtée pendant le paiement",
                        },
                        {
                            "topic_code": "app_paiement",
                            "sentiment": "négatif",
                            "severity": 3,
                            "quote": "Le paiement a aussi posé problème",
                        },
                        {
                            "topic_code": "app_bug",
                            "sentiment": "négatif",
                            "severity": 2,
                            "quote": "L'application affichait une erreur",
                        },
                    ],
                    "entity_perceptions": [],
                    "verbatim_quotes": [],
                },
            },
        ]

        summary = metrics_builder.build_voc_summary(evaluations)
        reasons = {item["label"]: item for item in summary["call_reasons"]}

        self.assertIn("Interruption de charge", reasons)
        self.assertIn("Paiement application", reasons)
        self.assertIn("Difficulté à trouver la borne", reasons)
        interruption_subreasons = {item["label"] for item in reasons["Interruption de charge"]["subreasons"]}
        payment_subreasons = {item["label"] for item in reasons["Paiement application"]["subreasons"]}
        location_subreasons = {item["label"] for item in reasons["Difficulté à trouver la borne"]["subreasons"]}
        self.assertEqual(sum(item["count"] for item in summary["call_reasons"]), len(evaluations))
        self.assertEqual(reasons["Interruption de charge"]["count"], 2)
        self.assertEqual(reasons["Paiement application"]["count"], 1)
        self.assertGreater(sum(item["count"] for item in summary["customer_problems"]), len(evaluations))
        self.assertIn("Badge RFID / interopérabilité", interruption_subreasons)
        self.assertIn("TPE / CB", payment_subreasons)
        self.assertIn("Signalétique / borne introuvable", location_subreasons)

    def test_rgpd_opt_out_detection(self):
        self.assertTrue(persistence._call_rgpd_opt_out({"rgpd_opt_out": True}))
        self.assertTrue(persistence._call_rgpd_opt_out({"opt_out": "yes"}))
        self.assertFalse(persistence._call_rgpd_opt_out({"opt_out": "no"}))


if __name__ == "__main__":
    unittest.main()
