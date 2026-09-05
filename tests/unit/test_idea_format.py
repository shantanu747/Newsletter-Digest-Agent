"""Guard tests for the idea-based digest recall format."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.summarizer.claude_summarizer import (
    _IDEA_SYSTEM_PROMPT_TEMPLATE,
    _build_entity_section,
    _build_profile_section,
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
    content_block = MagicMock(type="text", text=text)
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

    def test_no_entities_line_yields_unchanged_body_and_empty_entities(self):
        raw = "IDEA: Test Title\nThis is the body text."
        result = _parse_ideas(raw)
        assert result[0].title == "Test Title"
        assert result[0].summary_text == "This is the body text."
        assert result[0].entities == ()

    def test_entities_line_parses_correctly(self):
        raw = (
            "IDEA: Nvidia Earnings\n"
            "Nvidia posted strong data center growth.\n"
            "ENTITIES: Nvidia (company, positive); export controls (policy, negative)"
        )
        result = _parse_ideas(raw)
        assert len(result) == 1
        assert result[0].title == "Nvidia Earnings"
        assert result[0].summary_text == "Nvidia posted strong data center growth."
        assert len(result[0].entities) == 2
        assert result[0].entities[0].name == "Nvidia"
        assert result[0].entities[0].entity_type == "company"
        assert result[0].entities[0].sentiment == "positive"
        assert result[0].entities[1].name == "export controls"
        assert result[0].entities[1].entity_type == "policy"
        assert result[0].entities[1].sentiment == "negative"

    def test_malformed_entity_entry_skipped_while_siblings_survive(self):
        raw = (
            "IDEA: Mixed Bag\n"
            "Some body text.\n"
            "ENTITIES: Nvidia (company, positive); this entry is garbage; Fed (institution, neutral)"
        )
        result = _parse_ideas(raw)
        assert len(result[0].entities) == 2
        assert result[0].entities[0].name == "Nvidia"
        assert result[0].entities[1].name == "Fed"


class TestBuildEntitySection:
    def test_none_config_returns_empty_string(self):
        assert _build_entity_section(None) == ""

    def test_disabled_config_returns_empty_string(self):
        cfg = SimpleNamespace(enabled=False, max_entities_per_idea=8)
        assert _build_entity_section(cfg) == ""

    def test_enabled_config_mentions_entities_prefix(self):
        cfg = SimpleNamespace(enabled=True, max_entities_per_idea=8)
        section = _build_entity_section(cfg)
        assert "ENTITIES:" in section
        assert section.endswith("\n\n")


class TestPromptByteIdentity:
    def test_disabled_render_is_byte_identical_to_profile_only_render(self):
        profile_only = _IDEA_SYSTEM_PROMPT_TEMPLATE.format(
            profile_section=_build_profile_section(None), entity_section=""
        )
        disabled = _IDEA_SYSTEM_PROMPT_TEMPLATE.format(
            profile_section=_build_profile_section(None), entity_section=_build_entity_section(None)
        )
        assert disabled == profile_only


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

    def test_uses_raised_max_tokens_and_low_effort(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_api_response(
            "IDEA: Off-Topic Idea\nThis newsletter covers gardening tips for beginners."
        )
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text="Today we discuss the best tomato varieties.")
        summarizer.summarize_as_ideas(email, user_profile=None)

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs.get("max_tokens") == 4096
        assert call_kwargs.kwargs.get("output_config") == {"effort": "low"}

    def test_thinking_block_before_text_still_parses_ideas(self, mocker):
        mock_client = MagicMock()
        response = MagicMock()
        response.content = [
            MagicMock(type="thinking", thinking="pondering..."),
            MagicMock(
                type="text",
                text="IDEA: Off-Topic Idea\nThis newsletter covers gardening tips for beginners.",
            ),
        ]
        mock_client.messages.create.return_value = response
        mocker.patch("anthropic.Anthropic", return_value=mock_client)

        from agent.summarizer.claude_summarizer import ClaudeSummarizer

        summarizer = ClaudeSummarizer(api_key="test-key")
        email = _make_email(plain_text="Today we discuss the best tomato varieties.")
        result = summarizer.summarize_as_ideas(email, user_profile=None)

        assert len(result.ideas) == 1
        assert result.ideas[0].title == "Off-Topic Idea"
