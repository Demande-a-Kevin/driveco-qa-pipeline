from csat_parser import parse_sprig, CsatPost

# Message réel observé (texte API mrkdwn, blockquotes en lignes ">")
MSG_WITH_ID = {
    "ts": "1780404011.283339",
    "user": "U0798UDP7U0",
    "text": (
        "<https://app.sprig.com/x/surveys/abc|*CSAT Customer Care - New Version*> "
        "received a new response from <mailto:3825857378@driveco.com|3825857378@driveco.com>.\n"
        "> *Dans quelle mesure notre assistance a-t-elle répondu à vos attentes ?*\n"
        "> 3\n"
        "> \n"
        "> *Qu'est ce qui a le plus influencé votre satisfaction lors de cet appel ?*\n"
        "> L'amabilité et l'écoute de l'agent\n"
        "> \n"
        "> *Quelles améliorations suggéreriez-vous ?*\n"
        "> La borne n°4 est HS et le QR code manque.\n"
    ),
}

MSG_NO_ID = {
    "ts": "1780356924.718089",
    "user": "U0798UDP7U0",
    "text": (
        "<https://app.sprig.com/x/surveys/abc|*CSAT Customer Care - New Version*> "
        "received a new response.\n"
        "> *Dans quelle mesure notre assistance a-t-elle répondu à vos attentes ?*\n"
        "> 1\n"
    ),
}


def test_parse_extracts_call_id_and_score():
    post = parse_sprig(MSG_WITH_ID)
    assert isinstance(post, CsatPost)
    assert post.ts == "1780404011.283339"
    assert post.call_id == "3825857378"
    assert post.score == 3
    assert "écoute de l'agent" in post.influence
    assert "QR code" in post.improvements


def test_parse_without_call_id_returns_none_call_id():
    post = parse_sprig(MSG_NO_ID)
    assert post.call_id is None
    assert post.score == 1


def test_parse_flattens_attachments_text():
    msg = {
        "ts": "1.1",
        "user": "U0798UDP7U0",
        "text": "received a new response from <mailto:123456@driveco.com|123456@driveco.com>.",
        "attachments": [{"text": "> *Dans quelle mesure...*\n> 5"}],
    }
    post = parse_sprig(msg)
    assert post.call_id == "123456"
    assert post.score == 5


def test_parse_missing_score_is_none():
    msg = {"ts": "1.1", "user": "U0798UDP7U0",
           "text": "received a new response from <mailto:999999@driveco.com|x>."}
    post = parse_sprig(msg)
    assert post.call_id == "999999"
    assert post.score is None


def test_parse_score_answer_with_extra_text_is_none():
    msg = {"ts": "1.1", "user": "U0798UDP7U0",
           "text": ("from <mailto:123456@driveco.com|x>.\n"
                    "> *Dans quelle mesure notre assistance a-t-elle répondu à vos attentes ?*\n"
                    "> top 10 fois")}
    from csat_parser import parse_sprig
    assert parse_sprig(msg).score is None
