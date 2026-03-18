"""Pytest fixtures shared across the test suite."""

from datetime import datetime, timezone

import pytest

from agent.utils.config import AgentConfiguration
from agent.utils.models import DigestEntry, Email, Summary


@pytest.fixture
def sample_email() -> Email:
    return Email(
        id="msg-001",
        source="gmail",
        sender="newsletter@example.com",
        subject="The Daily Digest — March 9",
        received_at=datetime(2026, 3, 9, 7, 0, 0, tzinfo=timezone.utc),
        raw_html="<html><body><h1>Top Stories</h1><p>Content here.</p></body></html>",
        plain_text=None,
    )


@pytest.fixture
def sample_email_plain() -> Email:
    """Email with pre-populated plain_text (post-parse)."""
    return Email(
        id="msg-001",
        source="gmail",
        sender="newsletter@example.com",
        subject="The Daily Digest — March 9",
        received_at=datetime(2026, 3, 9, 7, 0, 0, tzinfo=timezone.utc),
        raw_html="",
        plain_text="Top Stories\n\nContent here.",
    )


@pytest.fixture
def sample_summary() -> Summary:
    text = " ".join(["word"] * 225)
    return Summary(
        email_id="msg-001",
        sender="newsletter@example.com",
        subject="The Daily Digest — March 9",
        summary_text=text,
        word_count=225,
        generated_at=datetime(2026, 3, 9, 7, 1, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_digest_entry(sample_summary: Summary) -> DigestEntry:
    return DigestEntry(summary=sample_summary)


@pytest.fixture
def mock_config() -> AgentConfiguration:
    cfg = AgentConfiguration(
        senders=["newsletter@example.com"],
        subject_keywords=["daily digest"],
        lookback_hours=24,
        max_newsletters_per_run=20,
        summary_word_target=225,
        schedule_hour=6,
        schedule_minute=30,
        schedule_timezone="UTC",
    )
    cfg.anthropic_api_key = "test-anthropic-key"
    cfg.gmail_token_path = "test-token.json"
    cfg.delivery_recipient = "recipient@example.com"
    cfg.smtp_host = "smtp.example.com"
    cfg.smtp_port = 587
    cfg.smtp_user = "user@example.com"
    cfg.smtp_password = "test-password"
    return cfg
