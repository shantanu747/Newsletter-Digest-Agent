"""Unit tests for the Signals Report config sections (knowledge_graph, signals, macro).

Tests cover:
- All three sections absent → all three config attributes are None
- An unknown key in any section raises ConfigurationError
- signals present without knowledge_graph raises ConfigurationError
- macro present without signals is ignored (warn, not raise)
- Missing FRED_API_KEY does not stop load_config() from succeeding
"""

import os
from unittest.mock import patch

import pytest

from agent.utils.config import (
    _parse_knowledge_config,
    _parse_macro_config,
    _parse_signals_config,
    load_config,
)
from agent.utils.exceptions import ConfigurationError

_ENV = {
    "ANTHROPIC_API_KEY": "sk-test",
    "GMAIL_OAUTH_TOKEN_PATH": "token.json",
    "DELIVERY_EMAIL": "test@example.com",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "user@example.com",
    "SMTP_PASSWORD": "password",
}


def _write_yaml(tmp_path, content: str):
    yaml_file = tmp_path / "newsletters.yaml"
    yaml_file.write_text(content)
    return yaml_file


class TestSectionsAbsent:
    def test_all_three_sections_absent_leaves_all_none(self, tmp_path):
        yaml_file = _write_yaml(tmp_path, "senders: []\nsubject_keywords: []\n")
        with patch.dict(os.environ, _ENV):
            cfg = load_config(str(yaml_file), profile_path=str(tmp_path / "missing.yaml"))
        assert cfg.knowledge is None
        assert cfg.signals is None
        assert cfg.macro is None


class TestParseKnowledgeConfig:
    def test_defaults(self):
        cfg = _parse_knowledge_config({})
        assert cfg.enabled is True
        assert cfg.db_path == "data/signals.db"
        assert cfg.retention_days == 180
        assert cfg.max_entities_per_idea == 8

    def test_unknown_key_raises(self):
        with pytest.raises(ConfigurationError, match="Unknown key"):
            _parse_knowledge_config({"bogus_key": True})


class TestParseSignalsConfig:
    def test_defaults(self):
        cfg = _parse_signals_config({})
        assert cfg.enabled is True
        assert cfg.interval_days == 3
        assert cfg.window_days == 7
        assert cfg.min_mentions == 3
        assert cfg.min_sources == 2
        assert cfg.max_entities_in_prompt == 40
        assert cfg.web_search_enabled is False
        assert cfg.web_search_max_uses == 5
        assert cfg.model == "claude-opus-5"

    def test_unknown_key_raises(self):
        with pytest.raises(ConfigurationError, match="Unknown key"):
            _parse_signals_config({"min_sourses": 3})


class TestParseMacroConfig:
    def test_defaults(self):
        cfg = _parse_macro_config({})
        assert cfg.enabled is True
        assert "T10Y3M" in cfg.series
        assert cfg.cache_hours == 12

    def test_unknown_key_raises(self):
        with pytest.raises(ConfigurationError, match="Unknown key"):
            _parse_macro_config({"bogus_key": True})


class TestLoadConfigDependencyRules:
    def test_signals_without_knowledge_graph_raises(self, tmp_path):
        yaml_file = _write_yaml(
            tmp_path,
            "senders: []\nsubject_keywords: []\nsignals:\n  enabled: true\n",
        )
        with patch.dict(os.environ, _ENV):
            with pytest.raises(ConfigurationError, match="knowledge_graph"):
                load_config(str(yaml_file), profile_path=str(tmp_path / "missing.yaml"))

    def test_macro_without_signals_is_ignored(self, tmp_path):
        yaml_file = _write_yaml(
            tmp_path,
            "senders: []\nsubject_keywords: []\nmacro:\n  enabled: true\n",
        )
        with patch.dict(os.environ, _ENV):
            cfg = load_config(str(yaml_file), profile_path=str(tmp_path / "missing.yaml"))
        assert cfg.macro is None

    def test_knowledge_graph_and_signals_together_populate_both(self, tmp_path):
        yaml_file = _write_yaml(
            tmp_path,
            "senders: []\nsubject_keywords: []\n"
            "knowledge_graph:\n  enabled: true\n"
            "signals:\n  enabled: true\n  interval_days: 5\n",
        )
        with patch.dict(os.environ, _ENV):
            cfg = load_config(str(yaml_file), profile_path=str(tmp_path / "missing.yaml"))
        assert cfg.knowledge is not None
        assert cfg.signals is not None
        assert cfg.signals.interval_days == 5


class TestFredApiKeyOptional:
    def test_missing_fred_api_key_still_succeeds(self, tmp_path):
        yaml_file = _write_yaml(tmp_path, "senders: []\nsubject_keywords: []\n")
        env = dict(_ENV)
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("FRED_API_KEY", None)
            cfg = load_config(str(yaml_file), profile_path=str(tmp_path / "missing.yaml"))
        assert cfg.fred_api_key == ""
