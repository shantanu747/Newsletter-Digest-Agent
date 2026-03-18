"""Unit tests for ClaudeSummarizer.

Tests cover:
- Happy path: successful summarization returns a well-formed Summary dataclass
- Retry success: recovers after transient APIError failures on earlier attempts
- All retries fail: SummarizationError raised after all 3 attempts are exhausted
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from agent.utils.exceptions import SummarizationError
from agent.utils.models import Email, Summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email(plain_text: str = "Some newsletter content.") -> Email:
    return Email(
        id="msg-001",
        source="gmail",
        sender="newsletter@example.com",
        subject="The Daily Digest — March 9",
        received_at=datetime(2026, 3, 9, 7, 0, 0, tzinfo=timezone.utc),
        raw_html="",
        plain_text=plain_text,
    )


def _make_api_response(text: str) -> MagicMock:
    """Return a mock that looks like an anthropic Messages response."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClaudeSummarizerHappyPath:
    """Successful end-to-end summarization."""

    def test_returns_summary_with_correct_fields(self, mocker):
        """summarize() returns a Summary whose fields match the source email."""
        # Arrange: 225 words of output text
        summary_text = "word " * 225

        mock_create = mocker.patch(
            "anthropic.Anthropic.messages",
            new_callable=MagicMock,
        )

        # Patch at the point the module under test imports / constructs the client
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(summary_text)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text="Top Stories\n\nContent here.")

        # Act
        result = summarizer.summarize(email)

        # Assert shape
        assert isinstance(result, Summary)
        assert result.email_id == email.id
        assert result.sender == email.sender
        assert result.subject == email.subject
        assert result.word_count == 225
        assert result.summary_text == summary_text.strip()
        assert isinstance(result.generated_at, datetime)

    def test_api_called_once_on_success(self, mocker):
        """Claude API is invoked exactly once when the first call succeeds."""
        summary_text = "word " * 225

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(summary_text)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        summarizer.summarize(_make_email())

        mock_client.messages.create.assert_called_once()

    def test_api_called_with_correct_model(self, mocker):
        """messages.create is called with the claude-sonnet-4-6 model."""
        summary_text = "word " * 225

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(summary_text)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        summarizer.summarize(_make_email())

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs.get("model") == "claude-sonnet-4-6" or (
            call_kwargs.args and call_kwargs.args[0] == "claude-sonnet-4-6"
        )

    def test_api_called_with_max_tokens_1024(self, mocker):
        """messages.create is called with max_tokens=1024."""
        summary_text = "word " * 225

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(summary_text)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        summarizer.summarize(_make_email())

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs.get("max_tokens") == 1024


class TestClaudeSummarizerRetryOnAPIError:
    """Retry behaviour on anthropic.APIError."""

    def test_retry_success_after_two_failures(self, mocker):
        """summarize() returns Summary when the third attempt succeeds."""
        summary_text = "word " * 225

        mock_client = MagicMock()
        # Build a minimal request object for APIError
        mock_request = MagicMock()
        api_error = anthropic.APIError(
            message="Internal server error",
            request=mock_request,
            body=None,
        )
        mock_client.messages.create.side_effect = [
            api_error,
            api_error,
            _make_api_response(summary_text),
        ]
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        # Patch sleep so tests don't actually wait
        mocker.patch("time.sleep")

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        result = summarizer.summarize(_make_email())

        assert isinstance(result, Summary)
        assert mock_client.messages.create.call_count == 3

    def test_retry_called_three_times_total(self, mocker):
        """messages.create is called exactly 3 times across initial call + 2 retries."""
        summary_text = "word " * 225

        mock_client = MagicMock()
        mock_request = MagicMock()
        api_error = anthropic.APIError(
            message="Internal server error",
            request=mock_request,
            body=None,
        )
        mock_client.messages.create.side_effect = [
            api_error,
            api_error,
            _make_api_response(summary_text),
        ]
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        summarizer.summarize(_make_email())

        assert mock_client.messages.create.call_count == 3


class TestClaudeSummarizerRetryOnRateLimitError:
    """Retry behaviour on anthropic.RateLimitError."""

    def test_retry_success_after_rate_limit_errors(self, mocker):
        """summarize() recovers after RateLimitError on first two attempts."""
        summary_text = "word " * 225

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_request = MagicMock()
        rate_limit_error = anthropic.RateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body=None,
        )
        mock_client.messages.create.side_effect = [
            rate_limit_error,
            rate_limit_error,
            _make_api_response(summary_text),
        ]
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        result = summarizer.summarize(_make_email())

        assert isinstance(result, Summary)
        assert mock_client.messages.create.call_count == 3


class TestClaudeSummarizerAllRetriesExhausted:
    """SummarizationError raised when every attempt fails."""

    def test_raises_summarization_error_after_all_retries(self, mocker):
        """SummarizationError is raised when all 3 attempts raise APIError."""
        mock_client = MagicMock()
        mock_request = MagicMock()
        api_error = anthropic.APIError(
            message="Internal server error",
            request=mock_request,
            body=None,
        )
        mock_client.messages.create.side_effect = api_error
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")

        with pytest.raises(SummarizationError):
            summarizer.summarize(_make_email())

    def test_all_three_attempts_made_before_raising(self, mocker):
        """All 3 attempts are made before SummarizationError is raised."""
        mock_client = MagicMock()
        mock_request = MagicMock()
        api_error = anthropic.APIError(
            message="Internal server error",
            request=mock_request,
            body=None,
        )
        mock_client.messages.create.side_effect = api_error
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")

        with pytest.raises(SummarizationError):
            summarizer.summarize(_make_email())

        assert mock_client.messages.create.call_count == 3

    def test_raises_summarization_error_on_rate_limit_exhaustion(self, mocker):
        """SummarizationError raised when all 3 attempts raise RateLimitError."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        rate_limit_error = anthropic.RateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body=None,
        )
        mock_client.messages.create.side_effect = rate_limit_error
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")

        with pytest.raises(SummarizationError):
            summarizer.summarize(_make_email())

        assert mock_client.messages.create.call_count == 3
