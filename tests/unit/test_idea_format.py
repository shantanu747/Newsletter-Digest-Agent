"""Guard tests for the idea-based digest recall format."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from agent.summarizer.claude_summarizer import (
    _IDEA_SYSTEM_PROMPT_TEMPLATE,
    _parse_ideas,
)
from agent.utils.models import Email, Summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email(plain_text: str = "Some newsletter content.") -> Email:
    return Email(
        id="msg-001",
        source="gmail",
        sender="newsletter@example.com",
        subject="Test Newsletter",
        received_at=datetime(2026, 4, 15, 7, 0, 0, tzinfo=timezone.utc),
        raw_html="",
        plain_text=plain_text,
    )


def _make_api_response(text: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPromptGuards:
    def test_prompt_does_not_contain_no_high_signal_content(self):
        assert "No High-Signal Content" not in _IDEA_SYSTEM_PROMPT_TEMPLATE

    def test_prompt_does_not_contain_warrants_your_attention(self):
        assert "warrants your attention" not in _IDEA_SYSTEM_PROMPT_TEMPLATE


class TestParseIdeas:
    def test_empty_response_returns_content_unavailable(self):
        result = _parse_ideas("")
        assert len(result) == 1
        assert result[0].title == "Content Unavailable"

    def test_valid_idea_block_parsed_correctly(self):
        raw = "IDEA: Test Title\nThis is the body text."
        result = _parse_ideas(raw)
        assert len(result) == 1
        assert result[0].title == "Test Title"
        assert result[0].summary_text == "This is the body text."


class TestSummarizeAsIdeas:
    def test_returns_parsed_ideas_without_profile(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(
            "IDEA: Off-Topic Idea\nThis newsletter covers gardening tips for beginners."
        )
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text="Today we discuss the best tomato varieties.")
        result = summarizer.summarize_as_ideas(email, user_profile=None)

        assert isinstance(result, Summary)
        assert len(result.ideas) == 1
        assert result.ideas[0].title == "Off-Topic Idea"
