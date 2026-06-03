from sentiment_parser import parse_pingouin, SentimentPost

NEG = {"ts": "1.0", "bot_id": "B0B6V282D5Y", "text": (
    "Access link : <https://assets.aircall.io/calls/3827871596/recording/info>\n"
    "Score [-1 to +1]  :  -0.6  (confidance : 95%)\n--------------\n"
    '{\n  "overall_score": -0.88,\n  "initial_score": -0.45,\n'
    '  "peak_negative_score": -1,\n  "final_score": -0.6,\n'
    '  "label": "negative_unresolved",\n  "confidence": 0.95\n}')}

UNANS = {"ts": "2.0", "bot_id": "B0B6V282D5Y", "text": (
    "[Call not answered]\n"
    "Access link : <https://assets.aircall.io/calls/3827393590/recording/info>")}


def test_parse_negative_extracts_callid_and_scores():
    p = parse_pingouin(NEG)
    assert isinstance(p, SentimentPost)
    assert p.call_id == "3827871596"
    assert p.kind == "negative"
    assert p.scores["final_score"] == -0.6
    assert p.scores["peak_negative_score"] == -1
    assert p.scores["label"] == "negative_unresolved"


def test_parse_unanswered():
    p = parse_pingouin(UNANS)
    assert p.call_id == "3827393590"
    assert p.kind == "unanswered"
    assert p.scores is None


def test_parse_handles_html_escaped_link():
    msg = {"ts": "3.0", "bot_id": "B0B6V282D5Y",
           "text": "Access link : &lt;https://assets.aircall.io/calls/999999/recording/info&gt;\n"
                   "Score [-1 to +1] : -0.7 (confidance : 80%)\n{ \"final_score\": -0.7 }"}
    p = parse_pingouin(msg)
    assert p.call_id == "999999"
    assert p.kind == "negative"
    assert p.scores["final_score"] == -0.7


def test_parse_negative_with_broken_json_keeps_callid():
    msg = {"ts": "4.0", "bot_id": "B0B6V282D5Y",
           "text": "Access link : <https://assets.aircall.io/calls/111111/recording/info>\n"
                   "Score [-1 to +1] : -0.9 (confidance : 90%)\n{ pas du json"}
    p = parse_pingouin(msg)
    assert p.call_id == "111111"
    assert p.kind == "negative"
    assert p.scores == {}


def test_parse_negative_ignores_trailing_brace_block():
    from sentiment_parser import parse_pingouin
    msg = {"ts": "5.0", "bot_id": "B0B6V282D5Y", "text": (
        "Access link : <https://assets.aircall.io/calls/222222/recording/info>\n"
        "Score [-1 to +1] : -0.8 (confidance : 90%)\n"
        '{ "final_score": -0.8, "label": "neg" }\n*Note:* {action}')}
    p = parse_pingouin(msg)
    assert p.call_id == "222222"
    assert p.scores["final_score"] == -0.8
    assert p.scores["label"] == "neg"
