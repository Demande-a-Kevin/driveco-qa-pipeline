import csat_state


def test_load_missing_returns_default(tmp_path):
    st = csat_state.load_state(tmp_path / "x.json")
    assert st == {"last_ts": "0", "pending": []}


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    csat_state.save_state(p, {"last_ts": "123.45", "pending": [{"ts": "1.0"}]})
    st = csat_state.load_state(p)
    assert st["last_ts"] == "123.45"
    assert st["pending"] == [{"ts": "1.0"}]


def test_load_corrupt_returns_default(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert csat_state.load_state(p) == {"last_ts": "0", "pending": []}
