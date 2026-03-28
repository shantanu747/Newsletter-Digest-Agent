"""Unit tests for AdvisorAnalyzer.

Tests cover:
- Both delimiter sections parsed correctly
- Relevance-only response (no signals delimiter)
- Signals-only response (no relevance delimiter)
- Neither delimiter → both fields None
- Empty summaries list returns empty analysis
- System prompt includes reader interests and portfolio
- Retry logic on transient API errors
- API failure after 3 attempts returns empty analysis (no exception raised)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import anthropic
import pytest

from agent.advisor.analyzer import AdvisorAnalyzer, _RELEVANCE_DELIMITER, _SIGNALS_DELIMITER
from agent.utils.config import UserProfile
from agent.utils.models import AdvisorAnalysis, Summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(
    interests: list[str] | None = None,
    portfolio: list[dict] | None = None,
    watchlist: list[dict] | None = None,
    custom_prompts: list[str] | None = None,
) -> UserProfile:
    return UserProfile(
        interests=interests or ["aviation", "electric vehicles"],
        portfolio=portfolio or [{"ticker": "UAL", "name": "United Airlines", "notes": "Watch fuel costs."}],
        watchlist=watchlist or [{"ticker": "RIVN", "name": "Rivian"}],
        custom_prompts=custom_prompts or [],
    )


def _make_summary(subject: str, text: str) -> Summary:
    return Summary(
        email_id="msg-1",
        sender="test@example.com",
        subject=subject,
        summary_text=text,
        word_count=len(text.split()),
        generated_at=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
    )


def _make_analyzer(profile: UserProfile | None = None) -> AdvisorAnalyzer:
    return AdvisorAnalyzer(api_key="test-key", user_profile=profile or _make_profile())


def _mock_response(text: str) -> MagicMock:
    """Build a mock Anthropic message response."""
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    return response


# ---------------------------------------------------------------------------
# _parse_response tests
# ---------------------------------------------------------------------------

class TestParseResponse:

    def test_both_sections_parsed(self):
        analyzer = _make_analyzer()
        raw = (
            "Today's news is significant.\n"
            f"{_RELEVANCE_DELIMITER}\n"
            "Rising oil prices hurt UAL margins.\n"
            f"{_SIGNALS_DELIMITER}\n"
            "[SELL] UAL (United Airlines) — fuel costs eroding margins."
        )
        result = analyzer._parse_response(raw)
        assert result.relevance_text == "Rising oil prices hurt UAL margins."
        assert result.signals_text == "[SELL] UAL (United Airlines) — fuel costs eroding margins."

    def test_relevance_only(self):
        analyzer = _make_analyzer()
        raw = (
            f"{_RELEVANCE_DELIMITER}\n"
            "Aviation sector faces headwinds from jet fuel prices."
        )
        result = analyzer._parse_response(raw)
        assert result.relevance_text == "Aviation sector faces headwinds from jet fuel prices."
        assert result.signals_text is None

    def test_signals_only(self):
        analyzer = _make_analyzer()
        raw = (
            "Summary text.\n"
            f"{_SIGNALS_DELIMITER}\n"
            "[BUY] XOM (ExxonMobil) — oil price rising."
        )
        result = analyzer._parse_response(raw)
        assert result.relevance_text is None
        assert result.signals_text == "[BUY] XOM (ExxonMobil) — oil price rising."

    def test_no_delimiters_returns_both_none(self):
        analyzer = _make_analyzer()
        result = analyzer._parse_response("No relevant implications found.")
        assert result.relevance_text is None
        assert result.signals_text is None

    def test_empty_relevance_block_returns_none(self):
        analyzer = _make_analyzer()
        raw = f"{_RELEVANCE_DELIMITER}\n   \n{_SIGNALS_DELIMITER}\n[BUY] XOM — rationale."
        result = analyzer._parse_response(raw)
        assert result.relevance_text is None
        assert result.signals_text == "[BUY] XOM — rationale."


# ---------------------------------------------------------------------------
# analyze() tests — mocking the Anthropic client
# ---------------------------------------------------------------------------

class TestAnalyze:

    def test_empty_summaries_returns_empty_analysis(self):
        analyzer = _make_analyzer()
        result = analyzer.analyze([])
        assert result.relevance_text is None
        assert result.signals_text is None

    def test_successful_analysis(self, mocker):
        raw = (
            f"{_RELEVANCE_DELIMITER}\n"
            "UAL at risk from rising fuel costs.\n"
            f"{_SIGNALS_DELIMITER}\n"
            "[BUY] XOM (ExxonMobil) — oil price tailwind."
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(raw)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        analyzer = _make_analyzer()
        summaries = [_make_summary("Oil Prices Rise", "Global oil prices climbed 5% today.")]
        result = analyzer.analyze(summaries)

        assert result.relevance_text is not None
        assert "UAL" in result.relevance_text
        assert result.signals_text is not None
        assert "XOM" in result.signals_text

    def test_prompt_includes_interests(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response("No implications.")
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        profile = _make_profile(interests=["renewable energy", "battery technology"])
        analyzer = _make_analyzer(profile)
        analyzer.analyze([_make_summary("test", "test")])

        system_prompt = mock_client.messages.create.call_args[1]["system"]
        assert "renewable energy" in system_prompt
        assert "battery technology" in system_prompt

    def test_prompt_includes_portfolio_ticker(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response("No implications.")
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        profile = _make_profile(portfolio=[{"ticker": "AAPL", "name": "Apple"}])
        analyzer = _make_analyzer(profile)
        analyzer.analyze([_make_summary("test", "test")])

        system_prompt = mock_client.messages.create.call_args[1]["system"]
        assert "AAPL" in system_prompt
        assert "Apple" in system_prompt

    def test_prompt_includes_custom_prompts(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response("No implications.")
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        profile = _make_profile(custom_prompts=["Flag SpaceX news specifically."])
        analyzer = _make_analyzer(profile)
        analyzer.analyze([_make_summary("test", "test")])

        system_prompt = mock_client.messages.create.call_args[1]["system"]
        assert "Flag SpaceX news specifically." in system_prompt

    def test_user_message_contains_all_subjects(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response("No implications.")
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        analyzer = _make_analyzer()
        summaries = [
            _make_summary("Bloomberg Markets", "stocks rose"),
            _make_summary("Unusual Whales", "options volume surged"),
        ]
        analyzer.analyze(summaries)

        user_message = mock_client.messages.create.call_args[1]["messages"][0]["content"]
        assert "Bloomberg Markets" in user_message
        assert "Unusual Whales" in user_message

    def test_retries_on_rate_limit_error(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            anthropic.RateLimitError.__new__(anthropic.RateLimitError),
            _mock_response("No implications."),
        ]
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")

        analyzer = _make_analyzer()
        result = analyzer.analyze([_make_summary("test", "test")])

        assert mock_client.messages.create.call_count == 2
        assert result.relevance_text is None
        assert result.signals_text is None

    def test_all_retries_exhausted_returns_empty_not_raises(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.RateLimitError.__new__(
            anthropic.RateLimitError
        )
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")

        analyzer = _make_analyzer()
        # Should NOT raise — graceful degradation
        result = analyzer.analyze([_make_summary("test", "test")])

        assert mock_client.messages.create.call_count == 3
        assert result.relevance_text is None
        assert result.signals_text is None
