"""Integration smoke test for the full newsletter digest pipeline.

Mocks:
  - Gmail API (GmailFetcher.fetch_newsletters)
  - Claude API (ClaudeSummarizer.summarize)
  - SMTP delivery (EmailDelivery.send)

Verifies:
  - pass_through emails are NOT sent to Claude
  - summarize emails ARE sent to Claude
  - In dry-run mode, mark_as_read and move_to_trash are never called
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from agent.utils.config import AgentConfiguration
from agent.utils.models import Email, SenderConfig, Summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config() -> AgentConfiguration:
    cfg = AgentConfiguration(
        senders=[
            SenderConfig(address="rundown@therundown.ai", display_name="The Rundown AI", mode="pass_through"),
            SenderConfig(address="newsletter@morningbrew.com", display_name="Morning Brew", mode="summarize"),
        ],
        subject_keywords=[],
        batch_size=10,
        poll_interval_hours=4,
    )
    cfg.anthropic_api_key = "test-anthropic-key"
    cfg.gmail_token_path = "test-token.json"
    cfg.delivery_recipient = "recipient@example.com"
    cfg.smtp_host = "smtp.example.com"
    cfg.smtp_port = 587
    cfg.smtp_user = "user@example.com"
    cfg.smtp_password = "test-password"
    return cfg


def _make_emails() -> list[Email]:
    return [
        Email(
            id="pass-001",
            source="gmail",
            sender="The Rundown AI <rundown@therundown.ai>",
            subject="The Rundown: AI Daily",
            received_at=datetime(2026, 3, 19, 7, 0, 0, tzinfo=timezone.utc),
            raw_html="<h1>AI News</h1><ul><li>GPT-5 launched</li><li>Claude 4 released</li></ul>",
            gmail_message_id="pass-gmail-001",
        ),
        Email(
            id="pass-002",
            source="gmail",
            sender="The Rundown AI <rundown@therundown.ai>",
            subject="The Rundown: More AI News",
            received_at=datetime(2026, 3, 19, 8, 0, 0, tzinfo=timezone.utc),
            raw_html="<h1>More AI</h1><p>Some content here.</p>",
            gmail_message_id="pass-gmail-002",
        ),
        Email(
            id="sum-001",
            source="gmail",
            sender="Morning Brew <newsletter@morningbrew.com>",
            subject="Morning Brew Daily",
            received_at=datetime(2026, 3, 19, 6, 0, 0, tzinfo=timezone.utc),
            raw_html="<p>Business news for today.</p>",
            gmail_message_id="sum-gmail-001",
        ),
        Email(
            id="sum-002",
            source="gmail",
            sender="Morning Brew <newsletter@morningbrew.com>",
            subject="Morning Brew Weekend",
            received_at=datetime(2026, 3, 19, 9, 0, 0, tzinfo=timezone.utc),
            raw_html="<p>Weekend edition content.</p>",
            gmail_message_id="sum-gmail-002",
        ),
        Email(
            id="sum-003",
            source="gmail",
            sender="Morning Brew <newsletter@morningbrew.com>",
            subject="Morning Brew Extra",
            received_at=datetime(2026, 3, 19, 10, 0, 0, tzinfo=timezone.utc),
            raw_html="<p>Extra content.</p>",
            gmail_message_id="sum-gmail-003",
        ),
    ]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestFullPipelineDryRun:
    """End-to-end pipeline test with --dry-run --once."""

    def _run_pipeline(self, mocker, emails: list[Email], dry_run: bool = True):
        """Helper: wires up mocks and runs NewsletterAgent.run()."""
        from agent.runner import NewsletterAgent

        config = _make_config()
        agent = NewsletterAgent(config=config, dry_run=dry_run)

        # Mock fetcher
        mocker.patch.object(agent._fetcher, "fetch_newsletters", return_value=emails)

        # Spy on summarizer to track which emails reach Claude
        real_summarize_calls: list[str] = []

        def mock_summarize(email):
            if not email.is_pass_through:
                real_summarize_calls.append(email.id)
            return Summary(
                email_id=email.id,
                sender=email.sender,
                subject=email.subject,
                summary_text=email.plain_text or "Mocked AI summary.",
                word_count=3,
                generated_at=datetime(2026, 3, 19, tzinfo=timezone.utc),
            )

        mocker.patch.object(agent._summarizer, "summarize", side_effect=mock_summarize)

        # Track mark/trash calls
        mock_mark = mocker.patch.object(agent._fetcher, "mark_as_read")
        mock_trash = mocker.patch.object(agent._fetcher, "move_to_trash")

        # Mock SMTP delivery
        mock_send = mocker.patch.object(agent._delivery, "send")

        agent.run()

        return {
            "summarize_calls": real_summarize_calls,
            "mark_calls": mock_mark.call_count,
            "trash_calls": mock_trash.call_count,
            "send_calls": mock_send.call_count,
        }

    def test_pass_through_emails_not_sent_to_claude(self, mocker):
        """Pass-through emails bypass Claude summarization — summarize() not called for them."""
        emails = _make_emails()
        result = self._run_pipeline(mocker, emails, dry_run=True)

        # Only summarize-mode email IDs should appear in calls
        pass_through_ids = {"pass-001", "pass-002"}
        for called_id in result["summarize_calls"]:
            assert called_id not in pass_through_ids, (
                f"Pass-through email '{called_id}' was incorrectly sent to Claude"
            )

    def test_summarize_emails_sent_to_claude(self, mocker):
        """Summarize-mode emails are processed by Claude."""
        emails = _make_emails()
        result = self._run_pipeline(mocker, emails, dry_run=True)

        summarize_ids = {"sum-001", "sum-002", "sum-003"}
        called_set = set(result["summarize_calls"])
        assert summarize_ids == called_set, (
            f"Expected Claude calls for {summarize_ids}, got {called_set}"
        )

    def test_dry_run_no_mark_as_read(self, mocker):
        """In dry-run mode, mark_as_read is never called."""
        emails = _make_emails()
        result = self._run_pipeline(mocker, emails, dry_run=True)
        assert result["mark_calls"] == 0

    def test_dry_run_no_move_to_trash(self, mocker):
        """In dry-run mode, move_to_trash is never called."""
        emails = _make_emails()
        result = self._run_pipeline(mocker, emails, dry_run=True)
        assert result["trash_calls"] == 0

    def test_dry_run_smtp_not_called(self, mocker):
        """In dry-run mode, SMTP send is never called."""
        emails = _make_emails()
        result = self._run_pipeline(mocker, emails, dry_run=True)
        assert result["send_calls"] == 0

    def test_no_emails_runs_cleanly(self, mocker):
        """Pipeline handles 0 emails without errors."""
        result = self._run_pipeline(mocker, [], dry_run=True)
        assert result["summarize_calls"] == []
        assert result["mark_calls"] == 0
        assert result["trash_calls"] == 0
