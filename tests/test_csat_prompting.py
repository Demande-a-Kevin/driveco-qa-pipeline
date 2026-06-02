import csat_prompting
from csat_prompting import build_prompt, analyze, Insight


def test_build_prompt_contains_constraints_and_transcript():
    p = build_prompt("Agent: bonjour\nClient: ma borne est HS", score=2,
                     influence="agent sympa", improvements="borne HS")
    assert "55 mots" in p
    assert "borne est HS" in p
    assert "Agent/Assistance" in p and "Borne/App" in p


def test_analyze_parses_model_json(monkeypatch):
    monkeypatch.setattr(
        csat_prompting.ollama_client, "generate_json",
        lambda *a, **k: {"verdict": "Borne/App", "sentiment": "mitigé",
                         "synthese": "Agent à l'écoute mais borne HS."},
    )
    ins = analyze("transcript", score=3, influence="", improvements="")
    assert isinstance(ins, Insight)
    assert ins.verdict == "Borne/App"
    assert ins.sentiment == "mitigé"
    assert "borne hs" in ins.synthese.lower()


def test_analyze_normalizes_unknown_verdict(monkeypatch):
    monkeypatch.setattr(
        csat_prompting.ollama_client, "generate_json",
        lambda *a, **k: {"verdict": "n'importe quoi", "sentiment": "x", "synthese": "..."},
    )
    ins = analyze("t", score=1, influence="", improvements="")
    assert ins.verdict == "Autre"


def test_analyze_truncates_to_55_words(monkeypatch):
    long = " ".join(["mot"] * 100)
    monkeypatch.setattr(
        csat_prompting.ollama_client, "generate_json",
        lambda *a, **k: {"verdict": "Agent/Assistance", "sentiment": "négatif", "synthese": long},
    )
    ins = analyze("t", score=1, influence="", improvements="")
    assert len(ins.synthese.split()) <= 55
