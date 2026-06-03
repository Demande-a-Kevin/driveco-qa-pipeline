"""Garde-fous sur les validateurs qui rendent le one-shot fiable.

Le modèle Gemma renvoie souvent effort_score en string ('3') et des scores
'null'/'' : sans coercition, OneShotCallAnalysis échoue en validation → fallback
legacy systématique (one-shot inutile). Ces tests verrouillent les coercitions.
"""
import schemas


def test_voc_extract_coerces_string_effort_score():
    voc = schemas.VoCExtract(effort_score="3", satisfaction_signal="neutre",
                             churn_risk_signal="aucun")
    assert voc.effort_score == 3


def test_voc_extract_cleans_unknown_emotions():
    voc = schemas.VoCExtract(effort_score=2, satisfaction_signal="négatif",
                             churn_risk_signal="faible",
                             customer_emotions=["frustration", "BOGUS", "colère"])
    assert "frustration" in voc.customer_emotions
    assert "colère" in voc.customer_emotions
    assert "BOGUS" not in voc.customer_emotions


def test_criterion_scorecard_coerces_null_strings():
    sc = schemas.CriterionScorecard(accueil="null", empathie="", professionnalisme="n/a")
    assert sc.accueil is None
    assert sc.empathie is None
    assert sc.professionnalisme is None


def test_oneshot_analysis_parses_with_string_effort_score():
    obj = schemas.OneShotCallAnalysis(
        factual_extract={"call_id": "1", "classified_type": "driveco",
                         "kb_compliance": {"status": "conforme"}},
        scorecard={"accueil": 8, "empathie": "null"},
        voc_extract={"effort_score": "4", "satisfaction_signal": "positif",
                     "churn_risk_signal": "aucun"},
    )
    assert obj.voc_extract.effort_score == 4
    assert obj.scorecard.accueil == 8
    assert obj.scorecard.empathie is None
