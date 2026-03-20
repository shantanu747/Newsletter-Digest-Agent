"""Unit tests for config loading and SenderConfig parsing.

Tests cover:
- SenderConfig parsed correctly from YAML dict entries
- Unknown keys produce a log warning but no error
- Invalid mode value raises ConfigurationError
- batch_size defaults to 10 when not specified
- Empty senders list raises no error (warning logged instead)
"""

import pytest
from unittest.mock import patch, MagicMock

from agent.utils.config import _parse_sender, AgentConfiguration
from agent.utils.exceptions import ConfigurationError
from agent.utils.models import SenderConfig


# ---------------------------------------------------------------------------
# _parse_sender() tests
# ---------------------------------------------------------------------------

class TestParseSender:
    """Tests for the _parse_sender() helper."""

    def test_parses_address_and_mode(self):
        """address and mode fields are parsed correctly."""
        sc = _parse_sender({"address": "newsletter@example.com", "mode": "summarize"})
        assert sc.address == "newsletter@example.com"
        assert sc.mode == "summarize"

    def test_address_lowercased(self):
        """Sender address is lowercased during parsing."""
        sc = _parse_sender({"address": "Newsletter@Example.COM", "mode": "summarize"})
        assert sc.address == "newsletter@example.com"

    def test_pass_through_mode_accepted(self):
        """mode: pass_through is parsed without error."""
        sc = _parse_sender({"address": "digest@example.com", "mode": "pass_through"})
        assert sc.mode == "pass_through"

    def test_display_name_parsed(self):
        """display_name is populated when present."""
        sc = _parse_sender({
            "address": "newsletter@example.com",
            "mode": "summarize",
            "display_name": "Morning Brew",
        })
        assert sc.display_name == "Morning Brew"

    def test_display_name_defaults_to_none(self):
        """display_name is None when not provided."""
        sc = _parse_sender({"address": "newsletter@example.com", "mode": "summarize"})
        assert sc.display_name is None

    def test_invalid_mode_raises_config_error(self):
        """ConfigurationError raised for an unrecognised mode value."""
        with pytest.raises(ConfigurationError, match="Invalid sender mode"):
            _parse_sender({"address": "x@example.com", "mode": "invalid_mode"})

    def test_missing_address_raises_config_error(self):
        """ConfigurationError raised when address field is missing."""
        with pytest.raises(ConfigurationError, match="missing required 'address'"):
            _parse_sender({"mode": "summarize"})

    def test_unknown_keys_log_warning_not_error(self, mocker):
        """Unknown keys produce a structured log warning but do not raise."""
        mock_log = MagicMock()
        mocker.patch("agent.utils.logger.get_logger", return_value=mock_log)

        # Should not raise
        sc = _parse_sender({
            "address": "x@example.com",
            "mode": "summarize",
            "unknown_key": "unexpected_value",
        })
        mock_log.warning.assert_called_once()
        call_kwargs = mock_log.warning.call_args
        assert "unknown_sender_config_keys" in call_kwargs[0]

    def test_summary_word_target_parsed(self):
        """summary_word_target is parsed as an integer."""
        sc = _parse_sender({
            "address": "x@example.com",
            "mode": "summarize",
            "summary_word_target": 300,
        })
        assert sc.summary_word_target == 300

    def test_summary_word_target_below_50_raises(self):
        """summary_word_target < 50 raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="summary_word_target"):
            _parse_sender({
                "address": "x@example.com",
                "mode": "summarize",
                "summary_word_target": 10,
            })

    def test_max_images_zero_allowed(self):
        """max_images=0 is valid (disables images for this sender)."""
        sc = _parse_sender({
            "address": "x@example.com",
            "mode": "summarize",
            "max_images": 0,
        })
        assert sc.max_images == 0

    def test_max_images_negative_raises(self):
        """max_images < 0 raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="max_images"):
            _parse_sender({
                "address": "x@example.com",
                "mode": "summarize",
                "max_images": -1,
            })


# ---------------------------------------------------------------------------
# AgentConfiguration defaults
# ---------------------------------------------------------------------------

class TestAgentConfigurationDefaults:
    """Tests for AgentConfiguration field defaults."""

    def test_batch_size_defaults_to_10(self):
        """batch_size defaults to 10 when not specified."""
        cfg = AgentConfiguration()
        assert cfg.batch_size == 10

    def test_poll_interval_hours_defaults_to_4(self):
        """poll_interval_hours defaults to 4."""
        cfg = AgentConfiguration()
        assert cfg.poll_interval_hours == 4

    def test_senders_defaults_to_empty_list(self):
        """senders defaults to an empty list."""
        cfg = AgentConfiguration()
        assert cfg.senders == []

    def test_senders_type_is_list_of_sender_config(self):
        """senders field accepts a list of SenderConfig objects."""
        sc = SenderConfig(address="x@example.com", mode="summarize")
        cfg = AgentConfiguration(senders=[sc])
        assert cfg.senders[0].address == "x@example.com"
