import csat_aircall


def test_fetch_call_facts_computes_time_to_answer(monkeypatch):
    monkeypatch.setattr(
        csat_aircall.call_fetcher, "fetch_call_details",
        lambda cid: {"started_at": 100, "answered_at": 138, "duration": 288,
                     "direction": "outbound", "user": {"name": "Alice"}},
    )
    f = csat_aircall.fetch_call_facts("123")
    assert f["answered"] is True
    assert f["time_to_answer_s"] == 38
    assert f["duration_s"] == 288
    assert f["direction"] == "outbound"
    assert f["agent_name"] == "Alice"


def test_fetch_call_facts_not_answered(monkeypatch):
    monkeypatch.setattr(
        csat_aircall.call_fetcher, "fetch_call_details",
        lambda cid: {"started_at": 100, "answered_at": None, "user": None},
    )
    f = csat_aircall.fetch_call_facts("123")
    assert f["answered"] is False
    assert f["time_to_answer_s"] is None
    assert f["agent_name"] is None


def test_fetch_call_facts_handles_missing_and_errors(monkeypatch):
    monkeypatch.setattr(csat_aircall.call_fetcher, "fetch_call_details", lambda cid: None)
    assert csat_aircall.fetch_call_facts("123") == {}

    def boom(cid):
        raise RuntimeError("api down")

    monkeypatch.setattr(csat_aircall.call_fetcher, "fetch_call_details", boom)
    assert csat_aircall.fetch_call_facts("123") == {}
