"""TDD pour kb_draft_generator."""
from unittest.mock import patch, MagicMock

import kb_draft_generator


def test_build_prompt_coaching_format():
    ctx = {
        "cluster": {"label": "aurait_mieux_gérer", "total_frequency": 42},
        "members": [
            {"topic": "aurait_mieux_gérer"},
            {"topic": "aurait_mieux_structurer"},
        ],
        "transcripts": ["--- Appel a1b2 ---\nClient: bonjour..."],
    }
    prompt = kb_draft_generator._build_prompt("coaching", ctx)
    assert "manager QA" in prompt
    assert "fiche coaching" in prompt
    assert "aurait_mieux_gérer" in prompt
    assert "42" in prompt


def test_build_prompt_article_kb_format():
    ctx = {
        "cluster": {"label": "interruption_charge", "total_frequency": 10},
        "members": [{"topic": "interruption_charge"}],
        "transcripts": [],
    }
    prompt = kb_draft_generator._build_prompt("article_kb", ctx)
    assert "article KB" in prompt
    assert "Symptôme" in prompt
    assert "(aucun transcript disponible)" in prompt


def test_build_prompt_unknown_format_raises():
    ctx = {
        "cluster": {"label": "x", "total_frequency": 0},
        "members": [],
        "transcripts": [],
    }
    try:
        kb_draft_generator._build_prompt("unknown_format", ctx)
        assert False, "should have raised"
    except ValueError:
        pass


@patch("kb_draft_generator._call_ollama")
@patch("kb_draft_generator._fetch_cluster_context")
def test_generate_draft_returns_markdown(mock_fetch, mock_ollama):
    mock_fetch.return_value = {
        "cluster": {"label": "test", "total_frequency": 5},
        "members": [],
        "transcripts": [],
    }
    mock_ollama.return_value = "# Coaching draft\n\nContent ici."

    result = kb_draft_generator.generate_draft("cluster-x", "coaching")
    assert "# Coaching draft" in result
    mock_ollama.assert_called_once()
