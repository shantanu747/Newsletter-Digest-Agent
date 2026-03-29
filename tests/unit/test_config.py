"""Unit tests for config loading and SenderConfig parsing.

Tests cover:
- SenderConfig parsed correctly from YAML dict entries
- Unknown keys produce a log warning but no error
- Invalid mode value raises ConfigurationError
- batch_size defaults to 10 when not specified
- Empty senders list raises no error (warning logged instead)
- UserProfile parses interests, portfolio, watchlist, custom_prompts
- Missing ticker/name in portfolio raises ConfigurationError
- Absent user_profile.yaml leaves cfg.user_profile as None
- Malformed user_profile.yaml raises ConfigurationError
"""

import pytest
from unittest.mock import patch, MagicMock

from agent.utils.config import _parse_sender, _parse_user_profile, AgentConfiguration, UserProfile
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

    def test_user_profile_defaults_to_none(self):
        """user_profile defaults to None when not set."""
        cfg = AgentConfiguration()
        assert cfg.user_profile is None


# ---------------------------------------------------------------------------
# _parse_user_profile() tests
# ---------------------------------------------------------------------------

class TestParseUserProfile:
    """Tests for the _parse_user_profile() helper."""

    def test_interests_parsed(self):
        """interests list is parsed into UserProfile.interests."""
        profile = _parse_user_profile({"interests": ["aviation", "AI"]})
        assert profile.interests == ["aviation", "AI"]

    def test_portfolio_parsed(self):
        """portfolio list with ticker+name is parsed correctly."""
        raw = {"portfolio": [{"ticker": "UAL", "name": "United Airlines"}]}
        profile = _parse_user_profile(raw)
        assert len(profile.portfolio) == 1
        assert profile.portfolio[0]["ticker"] == "UAL"
        assert profile.portfolio[0]["name"] == "United Airlines"

    def test_portfolio_notes_preserved(self):
        """notes field in portfolio entries is preserved."""
        raw = {"portfolio": [{"ticker": "BA", "name": "Boeing", "notes": "Watch 737 MAX."}]}
        profile = _parse_user_profile(raw)
        assert profile.portfolio[0]["notes"] == "Watch 737 MAX."

    def test_watchlist_parsed(self):
        """watchlist entries are parsed correctly."""
        raw = {"watchlist": [{"ticker": "RIVN", "name": "Rivian"}]}
        profile = _parse_user_profile(raw)
        assert profile.watchlist[0]["ticker"] == "RIVN"

    def test_custom_prompts_parsed(self):
        """custom_prompts list is parsed into UserProfile.custom_prompts."""
        raw = {"custom_prompts": ["Flag SpaceX news.", "Long-term only."]}
        profile = _parse_user_profile(raw)
        assert profile.custom_prompts == ["Flag SpaceX news.", "Long-term only."]

    def test_empty_dict_returns_defaults(self):
        """Empty dict returns a UserProfile with all empty fields."""
        profile = _parse_user_profile({})
        assert profile.interests == []
        assert profile.portfolio == []
        assert profile.watchlist == []
        assert profile.custom_prompts == []

    def test_missing_ticker_raises(self):
        """ConfigurationError raised when portfolio entry is missing 'ticker'."""
        with pytest.raises(ConfigurationError, match="ticker"):
            _parse_user_profile({"portfolio": [{"name": "United Airlines"}]})

    def test_missing_name_raises(self):
        """ConfigurationError raised when portfolio entry is missing 'name'."""
        with pytest.raises(ConfigurationError, match="name"):
            _parse_user_profile({"portfolio": [{"ticker": "UAL"}]})

    def test_watchlist_missing_ticker_raises(self):
        """ConfigurationError raised when watchlist entry is missing 'ticker'."""
        with pytest.raises(ConfigurationError, match="ticker"):
            _parse_user_profile({"watchlist": [{"name": "Rivian"}]})

    def test_unknown_profile_keys_log_warning(self, mocker):
        """Unknown top-level keys produce a warning but do not raise."""
        mock_log = MagicMock()
        mocker.patch("agent.utils.logger.get_logger", return_value=mock_log)
        _parse_user_profile({"interests": ["AI"], "unknown_field": "value"})
        mock_log.warning.assert_called_once()


class TestLoadConfigUserProfile:
    """Tests for user_profile loading inside load_config()."""

    def test_absent_profile_file_sets_none(self, tmp_path):
        """user_profile stays None when user_profile.yaml does not exist."""
        from agent.utils.config import load_config
        import os

        yaml_content = "senders: []\nsubject_keywords: []\n"
        yaml_file = tmp_path / "newsletters.yaml"
        yaml_file.write_text(yaml_content)
        absent_profile = str(tmp_path / "nonexistent_profile.yaml")

        env = {
            "ANTHROPIC_API_KEY": "sk-test",
            "GMAIL_OAUTH_TOKEN_PATH": "token.json",
            "DELIVERY_EMAIL": "test@example.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "user@example.com",
            "SMTP_PASSWORD": "password",
        }
        with patch.dict(os.environ, env):
            cfg = load_config(str(yaml_file), profile_path=absent_profile)

        assert cfg.user_profile is None

    def test_valid_profile_file_sets_user_profile(self, tmp_path):
        """Valid user_profile.yaml is parsed and attached to cfg."""
        from agent.utils.config import load_config
        import os

        yaml_content = "senders: []\nsubject_keywords: []\n"
        yaml_file = tmp_path / "newsletters.yaml"
        yaml_file.write_text(yaml_content)

        profile_content = (
            "user_profile:\n"
            "  interests:\n"
            "    - aviation\n"
            "  portfolio:\n"
            "    - ticker: UAL\n"
            "      name: United Airlines\n"
        )
        profile_file = tmp_path / "user_profile.yaml"
        profile_file.write_text(profile_content)

        env = {
            "ANTHROPIC_API_KEY": "sk-test",
            "GMAIL_OAUTH_TOKEN_PATH": "token.json",
            "DELIVERY_EMAIL": "test@example.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "user@example.com",
            "SMTP_PASSWORD": "password",
        }
        with patch.dict(os.environ, env):
            cfg = load_config(str(yaml_file), profile_path=str(profile_file))

        assert cfg.user_profile is not None
        assert cfg.user_profile.interests == ["aviation"]
        assert cfg.user_profile.portfolio[0]["ticker"] == "UAL"

    def test_malformed_profile_yaml_raises(self, tmp_path):
        """Malformed YAML in user_profile.yaml raises ConfigurationError."""
        from agent.utils.config import load_config
        import os

        yaml_content = "senders: []\nsubject_keywords: []\n"
        yaml_file = tmp_path / "newsletters.yaml"
        yaml_file.write_text(yaml_content)

        profile_file = tmp_path / "user_profile.yaml"
        profile_file.write_text("user_profile: {\n  bad yaml: [unclosed")

        env = {
            "ANTHROPIC_API_KEY": "sk-test",
            "GMAIL_OAUTH_TOKEN_PATH": "token.json",
            "DELIVERY_EMAIL": "test@example.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "user@example.com",
            "SMTP_PASSWORD": "password",
        }
        with patch.dict(os.environ, env):
            with pytest.raises(ConfigurationError, match="Malformed YAML"):
                load_config(str(yaml_file), profile_path=str(profile_file))
