# tests/test_csat_insight.py
import csat_insight


def _msg(ts, call_id="3825857378", score_line="> 3"):
    mail = f"from <mailto:{call_id}@driveco.com|x>" if call_id else "received a new response."
    return {"ts": ts, "user": "U0798UDP7U0",
            "text": f"new response {mail}\n> *...répondu à vos attentes ?*\n{score_line}"}


def _wire(monkeypatch, *, history=None, transcript="Agent: bonjour", has_reply=False):
    posted = []
    monkeypatch.setattr(csat_insight, "fetch_new_sprig_posts",
                        lambda *a, **k: list(history or []))
    monkeypatch.setattr(csat_insight, "fetch_transcript", lambda call_id: transcript)
    monkeypatch.setattr(csat_insight, "fetch_call_facts", lambda call_id: {})
    monkeypatch.setattr(csat_insight, "thread_has_bot_reply", lambda *a, **k: has_reply)
    monkeypatch.setattr(csat_insight, "analyze",
                        lambda *a, **k: csat_insight.Insight("Borne/App", "mitigé", "Borne HS."))
    def fake_post(channel, thread_ts, text, token=None):
        posted.append((thread_ts, text)); return True
    monkeypatch.setattr(csat_insight, "post_thread", fake_post)
    monkeypatch.setattr(csat_insight.config, "DISABLE_CSAT_INSIGHT", False)
    return posted


def test_first_run_sets_baseline_and_posts_nothing(monkeypatch, tmp_path):
    posted = _wire(monkeypatch, history=[_msg("10.0")])
    state_file = tmp_path / "s.json"
    csat_insight.run_once(now_epoch=999, state_path=state_file)
    assert posted == []
    import csat_state
    assert csat_state.load_state(state_file)["last_ts"] == "999"


def test_posts_thread_for_new_csat(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, history=[_msg("10.0", call_id="3825857378")])
    csat_insight.run_once(now_epoch=1000, state_path=state_file)
    assert len(posted) == 1
    thread_ts, text = posted[0]
    assert thread_ts == "10.0"
    assert "Borne/App" in text and "3825857378" in text
    assert csat_state.load_state(state_file)["last_ts"] == "10.0"


def test_no_call_id_skips_without_posting(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, history=[_msg("10.0", call_id=None)])
    csat_insight.run_once(now_epoch=1000, state_path=state_file)
    assert posted == []
    assert csat_state.load_state(state_file)["last_ts"] == "10.0"


def test_transcript_not_ready_goes_pending(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, history=[_msg("10.0")], transcript="")
    csat_insight.run_once(now_epoch=1000, state_path=state_file)
    assert posted == []
    pending = csat_state.load_state(state_file)["pending"]
    assert len(pending) == 1 and pending[0]["call_id"] == "3825857378"


def test_pending_budget_exhausted_posts_link_only(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "10.0", "pending": [
        {"ts": "9.0", "call_id": "3825857378", "score": 3, "influence": "", "improvements": "",
         "first_seen": 0, "attempts": 20}]})
    posted = _wire(monkeypatch, history=[], transcript="")
    csat_insight.run_once(now_epoch=10000, state_path=state_file)
    assert len(posted) == 1
    assert "transcript" in posted[0][1].lower()
    assert csat_state.load_state(state_file)["pending"] == []


def test_already_replied_skips(monkeypatch, tmp_path):
    state_file = tmp_path / "s.json"
    import csat_state
    csat_state.save_state(state_file, {"last_ts": "5.0", "pending": []})
    posted = _wire(monkeypatch, history=[_msg("10.0")], has_reply=True)
    csat_insight.run_once(now_epoch=1000, state_path=state_file)
    assert posted == []


def test_disabled_flag_short_circuits(monkeypatch, tmp_path):
    called = {"history": False}
    def boom(*a, **k):
        called["history"] = True
        return []
    monkeypatch.setattr(csat_insight, "fetch_new_sprig_posts", boom)
    monkeypatch.setattr(csat_insight.config, "DISABLE_CSAT_INSIGHT", True)
    csat_insight.run_once(now_epoch=999, state_path=tmp_path / "s.json")
    assert called["history"] is False


def test_render_includes_aircall_facts_line():
    ins = csat_insight.Insight("Borne/App", "négatif", "Borne HS.")
    txt = csat_insight._render(ins, "3826839572", 1,
                               {"answered": True, "time_to_answer_s": 38, "duration_s": 288})
    assert "CSAT 1/5" in txt
    assert "⏱" in txt and "38s" in txt
    assert "Verdict : Borne/App" in txt


def test_render_without_facts_has_no_facts_line():
    ins = csat_insight.Insight("Autre", "mitigé", "x")
    txt = csat_insight._render(ins, "123", 4, None)
    assert "⏱" not in txt
    assert txt.count("\n") == 2  # header + verdict + synthese


def test_render_shows_station_line():
    ins = csat_insight.Insight("Borne/App", "négatif", "x", station="Carrefour Rives 4")
    txt = csat_insight._render(ins, "123", 1, None)
    assert "📍 Station : Carrefour Rives 4" in txt


def test_render_no_station_line_when_empty():
    ins = csat_insight.Insight("Autre", "mitigé", "x")
    assert "📍" not in csat_insight._render(ins, "123", 4, None)
