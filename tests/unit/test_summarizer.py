"""Unit tests for ClaudeSummarizer pass-through bypass and normal summarization.

Tests cover:
- pass_through=True: returns Summary wrapping plain_text WITHOUT calling Claude API
- pass_through=False: calls Claude API normally
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from agent.utils.models import Email, Summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email(plain_text: str = "Some newsletter content.", is_pass_through: bool = False) -> Email:
    return Email(
        id="msg-001",
        source="gmail",
        sender="newsletter@example.com",
        subject="The Daily Digest — March 19",
        received_at=datetime(2026, 3, 19, 7, 0, 0, tzinfo=timezone.utc),
        raw_html="",
        plain_text=plain_text,
        is_pass_through=is_pass_through,
    )


def _make_api_response(text: str) -> MagicMock:
    """Return a mock that looks like an anthropic Messages response."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ---------------------------------------------------------------------------
# Pass-through bypass tests
# ---------------------------------------------------------------------------

class TestPassThroughBypass:
    """When email.is_pass_through=True, Claude API must not be called."""

    def test_pass_through_returns_summary_without_api_call(self, mocker):
        """summarize() returns a Summary when is_pass_through=True, no API call made."""
        mock_client = MagicMock()
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text="## Top Stories\n\n- Story one\n- Story two", is_pass_through=True)

        result = summarizer.summarize(email)

        assert isinstance(result, Summary)
        mock_client.messages.create.assert_not_called()

    def test_pass_through_summary_text_is_plain_text(self, mocker):
        """Summary.summary_text equals email.plain_text for pass_through emails."""
        mock_client = MagicMock()
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        plain = "## AI News\n\n- GPT-5 released\n- Claude 4 launched"
        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text=plain, is_pass_through=True)

        result = summarizer.summarize(email)

        assert result.summary_text == plain

    def test_pass_through_word_count_calculated_from_text(self, mocker):
        """Summary.word_count reflects actual word count of pass-through text."""
        mock_client = MagicMock()
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        plain = "one two three four five"  # 5 words
        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text=plain, is_pass_through=True)

        result = summarizer.summarize(email)

        assert result.word_count == 5

    def test_pass_through_preserves_email_metadata(self, mocker):
        """Summary fields (email_id, sender, subject) match the source email."""
        mock_client = MagicMock()
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(is_pass_through=True)

        result = summarizer.summarize(email)

        assert result.email_id == email.id
        assert result.sender == email.sender
        assert result.subject == email.subject

    def test_pass_through_generated_at_is_datetime(self, mocker):
        """Summary.generated_at is a UTC-aware datetime for pass_through emails."""
        mock_client = MagicMock()
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(is_pass_through=True)

        result = summarizer.summarize(email)

        assert isinstance(result.generated_at, datetime)
        assert result.generated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Normal summarization path (is_pass_through=False)
# ---------------------------------------------------------------------------

class TestNormalSummarizationPath:
    """When email.is_pass_through=False, Claude API must be called normally."""

    def test_normal_mode_calls_claude_api(self, mocker):
        """summarize() calls the Claude API when is_pass_through=False."""
        summary_text = "word " * 100

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(summary_text)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text="Long newsletter content here.", is_pass_through=False)

        result = summarizer.summarize(email)

        mock_client.messages.create.assert_called_once()
        assert isinstance(result, Summary)

    def test_normal_mode_returns_claude_text(self, mocker):
        """Summary.summary_text is the text returned by Claude, not the input."""
        expected_text = "This is the AI-generated summary."

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(expected_text)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text="Long newsletter.", is_pass_through=False)

        result = summarizer.summarize(email)

        assert result.summary_text == expected_text
