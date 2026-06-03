import sentiment_prompting
from sentiment_prompting import analyze, build_prompt, SentimentInsight


def test_build_prompt_negative_includes_trajectory():
    p = build_prompt("negative", "Agent: bonjour\nClient: ça marche pas",
                     {"answered": True, "time_to_answer_s": 54, "duration_s": 838},
                     {"initial_score": -0.45, "peak_negative_score": -1, "final_score": -0.6})
    assert "final" in p.lower()
    assert "Borne/App" in p and "rattrap" in p.lower()
    assert "ça marche pas" in p


def test_analyze_negative_normalizes(monkeypatch):
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json",
                        lambda *a, **k: {"verdict": "Borne/App", "moment": "échec paiement ~8min",
                                         "recoverable": "non", "synthese": "Borne HS, paiement KO."})
    ins = analyze("negative", "transcript", {}, {"final_score": -0.6})
    assert isinstance(ins, SentimentInsight)
    assert ins.verdict == "Borne/App"
    assert ins.recoverable == "non"
    assert "paiement" in ins.moment


def test_analyze_negative_unknown_verdict_recoverable(monkeypatch):
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json",
                        lambda *a, **k: {"verdict": "xxx", "moment": "m", "recoverable": "yyy",
                                         "synthese": "s"})
    ins = analyze("negative", "t", {}, None)
    assert ins.verdict == "Autre"
    assert ins.recoverable == ""


def test_analyze_unanswered_without_transcript_is_deterministic(monkeypatch):
    called = {"llm": False}
    def boom(*a, **k):
        called["llm"] = True
        return {}
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json", boom)
    ins = analyze("unanswered", "", {"answered": False, "direction": "inbound"}, None)
    assert called["llm"] is False          # aucun appel LLM
    assert ins.verdict == ""               # pas de verdict
    assert ins.synthese                     # une explication factuelle existe


def test_analyze_synthese_truncated(monkeypatch):
    long = " ".join(["mot"] * 100)
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json",
                        lambda *a, **k: {"verdict": "Agent/Assistance", "moment": "m",
                                         "recoverable": "oui", "synthese": long})
    ins = analyze("negative", "t", {}, None)
    assert len(ins.synthese.split()) <= 50


def test_build_prompt_asks_for_station():
    p = build_prompt("negative", "t", {}, None)
    assert '"station"' in p and "invente jamais" in p.lower()


def test_analyze_extracts_station(monkeypatch):
    monkeypatch.setattr(sentiment_prompting.ollama_client, "generate_json",
                        lambda *a, **k: {"verdict": "Borne/App", "moment": "m", "recoverable": "non",
                                         "station": "Saint-Poings borne 2", "synthese": "s"})
    assert "Saint-Poings" in analyze("negative", "t", {}, None).station


def test_deterministic_unanswered_has_no_station():
    assert analyze("unanswered", "", {"answered": False, "direction": "inbound"}, None).station == ""
