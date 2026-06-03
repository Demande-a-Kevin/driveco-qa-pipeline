# tests/test_sentiment_insight.py
import sentiment_insight
import csat_state


def _neg(ts, call_id="3827871596"):
    return {"ts": ts, "bot_id": "B0B6V282D5Y",
            "text": (f"Access link : <https://assets.aircall.io/calls/{call_id}/recording/info>\n"
                     "Score [-1 to +1] : -0.6 (confidance : 95%)\n{ \"final_score\": -0.6 }")}


def _unans(ts, call_id="3827393590"):
    return {"ts": ts, "bot_id": "B0B6V282D5Y",
            "text": f"[Call not answered]\nAccess link : <https://assets.aircall.io/calls/{call_id}/recording/info>"}


def _wire(monkeypatch, *, posts=None, transcript="Agent: bonjour", facts=None, has_reply=False):
    posted = []
    monkeypatch.setattr(sentiment_insight, "fetch_new_posts_by_author",
                        lambda *a, **k: list(posts or []))
    monkeypatch.setattr(sentiment_insight, "fetch_transcript", lambda cid: transcript)
    monkeypatch.setattr(sentiment_insight, "fetch_call_facts",
                        lambda cid: (facts if facts is not None else {"answered": True, "duration_s": 288, "time_to_answer_s": 38}))
    monkeypatch.setattr(sentiment_insight, "thread_has_bot_reply", lambda *a, **k: has_reply)
    monkeypatch.setattr(sentiment_insight, "analyze",
                        lambda *a, **k: sentiment_insight.SentimentInsight("Borne/App", "échec paiement", "non", "Borne HS."))
    def fake_post(channel, thread_ts, text, token=None):
        posted.append((thread_ts, text)); return True
    monkeypatch.setattr(sentiment_insight, "post_thread", fake_post)
    monkeypatch.setattr(sentiment_insight.config, "DISABLE_SENTIMENT_INSIGHT", False)
    monkeypatch.setattr(sentiment_insight.config, "SENTIMENT_INSIGHT_MAX_PER_RUN", 5)
    return posted


def test_first_run_baseline_posts_nothing(monkeypatch, tmp_path):
    posted = _wire(monkeypatch, posts=[_neg("10.0")])
    sf = tmp_path / "s.json"
    sentiment_insight.run_once(now_epoch=999, state_path=sf)
    assert posted == []
    assert csat_state.load_state(sf)["last_ts"] == "999"


def test_posts_negative_with_verdict_and_score(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, posts=[_neg("10.0", "3827871596")])
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert len(posted) == 1
    ts, text = posted[0]
    assert ts == "10.0"
    assert "Borne/App" in text and "3827871596" in text and "-0.6" in text


def test_unanswered_but_answered_adds_mismatch_note(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, posts=[_unans("10.0")],
                   facts={"answered": True, "duration_s": 273, "time_to_answer_s": 114})
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert "non répondu" in posted[0][1].lower() and "décroché" in posted[0][1].lower()


def test_cap_limits_posts_per_run_and_advances_to_last_processed(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    posts = [_neg(f"{10 + i}.0") for i in range(8)]   # 8 nouveaux
    posted = _wire(monkeypatch, posts=posts)
    monkeypatch.setattr(sentiment_insight.config, "SENTIMENT_INSIGHT_MAX_PER_RUN", 3)
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert len(posted) == 3                                  # cap respecté
    assert csat_state.load_state(sf)["last_ts"] == "12.0"    # dernier traité (10,11,12)


def test_no_call_id_skips(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    bad = {"ts": "10.0", "bot_id": "B0B6V282D5Y", "text": "[Call not answered] (lien manquant)"}
    posted = _wire(monkeypatch, posts=[bad])
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert posted == []
    assert csat_state.load_state(sf)["last_ts"] == "10.0"


def test_already_replied_skips(monkeypatch, tmp_path):
    sf = tmp_path / "s.json"
    csat_state.save_state(sf, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, posts=[_neg("10.0")], has_reply=True)
    sentiment_insight.run_once(now_epoch=1000, state_path=sf)
    assert posted == []
