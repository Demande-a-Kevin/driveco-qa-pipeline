import csat_slack


class _Resp:
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


def test_fetch_new_sprig_posts_filters_author_and_oldest(monkeypatch):
    captured = {}
    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _Resp({"ok": True, "messages": [
            {"ts": "3.0", "user": "U0798UDP7U0", "text": "from <mailto:111111@driveco.com|x>"},
            {"ts": "2.0", "user": "UOTHER", "text": "bruit"},
        ]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    msgs = csat_slack.fetch_new_sprig_posts("C0B724V5X4L", oldest="1.0",
                                            sprig_user_id="U0798UDP7U0", token="xoxb-x")
    assert [m["ts"] for m in msgs] == ["3.0"]          # auteur filtré
    assert captured["params"]["oldest"] == "1.0"


def test_fetch_skips_message_equal_to_oldest(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({"ok": True, "messages": [
            {"ts": "1.0", "user": "U0798UDP7U0", "text": "from <mailto:111111@driveco.com|x>"},
        ]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    msgs = csat_slack.fetch_new_sprig_posts("C", oldest="1.0",
                                            sprig_user_id="U0798UDP7U0", token="t")
    assert msgs == []                                   # oldest inclusif -> on exclut l'égal


def test_post_thread_sends_thread_ts(monkeypatch):
    captured = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _Resp({"ok": True})
    monkeypatch.setattr(csat_slack.requests, "post", fake_post)
    ok = csat_slack.post_thread("C", "123.456", "coucou", token="t")
    assert ok is True
    assert captured["json"]["thread_ts"] == "123.456"
    assert captured["json"]["channel"] == "C"


def test_thread_has_bot_reply_true(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({"ok": True, "messages": [
            {"ts": "1.0", "user": "U0798UDP7U0"},
            {"ts": "1.1", "user": "U0AMEHDCDV5"},
        ]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    assert csat_slack.thread_has_bot_reply("C", "1.0", "U0AMEHDCDV5", token="t") is True


def test_thread_has_bot_reply_false(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _Resp({"ok": True, "messages": [{"ts": "1.0", "user": "U0798UDP7U0"}]})
    monkeypatch.setattr(csat_slack.requests, "get", fake_get)
    assert csat_slack.thread_has_bot_reply("C", "1.0", "U0AMEHDCDV5", token="t") is False
