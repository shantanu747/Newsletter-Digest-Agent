"""Unit tests for post-delivery mark-as-read and move-to-trash sequencing.

Tests cover:
- mark_as_read() called for each message ID on successful delivery
- move_to_trash() called after mark_as_read() on success
- Neither called when delivery fails
- HttpError on trash does not halt processing (resilient)
"""

import smtplib
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest
import googleapiclient.errors

from agent.utils.exceptions import DeliveryError
from agent.utils.models import SenderConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_smtp_context_manager(mock_smtp_instance: MagicMock):
    """Return a mock that behaves as an smtplib.SMTP context manager."""
    mock_smtp_cls = MagicMock()
    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_smtp_cls


def _make_http_error() -> googleapiclient.errors.HttpError:
    """Return a minimal HttpError for testing."""
    mock_resp = MagicMock()
    mock_resp.status = 403
    mock_resp.reason = "Forbidden"
    return googleapiclient.errors.HttpError(resp=mock_resp, content=b"Forbidden")


# ---------------------------------------------------------------------------
# GmailFetcher.mark_as_read tests
# ---------------------------------------------------------------------------

class TestMarkAsRead:
    """Tests for GmailFetcher.mark_as_read()."""

    def test_mark_as_read_calls_modify_with_remove_unread(self):
        """mark_as_read() calls messages().modify() with removeLabelIds=['UNREAD']."""
        from agent.fetchers.gmail_fetcher import GmailFetcher

        fetcher = GmailFetcher()
        mock_service = MagicMock()
        fetcher._service = mock_service

        fetcher.mark_as_read("msg-123")

        mock_service.users().messages().modify.assert_called_once_with(
            userId="me",
            id="msg-123",
            body={"removeLabelIds": ["UNREAD"]},
        )

    def test_mark_as_read_http_error_does_not_raise(self):
        """HttpError in mark_as_read() is swallowed — does not propagate."""
        from agent.fetchers.gmail_fetcher import GmailFetcher

        fetcher = GmailFetcher()
        mock_service = MagicMock()
        fetcher._service = mock_service

        mock_service.users().messages().modify().execute.side_effect = _make_http_error()

        # Should not raise
        fetcher.mark_as_read("msg-123")

    def test_mark_as_read_no_service_is_noop(self):
        """mark_as_read() is a no-op and doesn't raise when service is None."""
        from agent.fetchers.gmail_fetcher import GmailFetcher

        fetcher = GmailFetcher()
        assert fetcher._service is None
        # Should not raise
        fetcher.mark_as_read("msg-123")


# ---------------------------------------------------------------------------
# GmailFetcher.move_to_trash tests
# ---------------------------------------------------------------------------

class TestMoveToTrash:
    """Tests for GmailFetcher.move_to_trash()."""

    def test_move_to_trash_calls_modify_with_add_trash(self):
        """move_to_trash() calls messages().modify() with addLabelIds=['TRASH']."""
        from agent.fetchers.gmail_fetcher import GmailFetcher

        fetcher = GmailFetcher()
        mock_service = MagicMock()
        fetcher._service = mock_service

        fetcher.move_to_trash("msg-456")

        mock_service.users().messages().modify.assert_called_once_with(
            userId="me",
            id="msg-456",
            body={"addLabelIds": ["TRASH"]},
        )

    def test_move_to_trash_http_error_does_not_raise(self):
        """HttpError in move_to_trash() is swallowed — does not propagate."""
        from agent.fetchers.gmail_fetcher import GmailFetcher

        fetcher = GmailFetcher()
        mock_service = MagicMock()
        fetcher._service = mock_service

        mock_service.users().messages().modify().execute.side_effect = _make_http_error()

        # Should not raise — processing continues
        fetcher.move_to_trash("msg-456")

    def test_move_to_trash_no_service_is_noop(self):
        """move_to_trash() is a no-op and doesn't raise when service is None."""
        from agent.fetchers.gmail_fetcher import GmailFetcher

        fetcher = GmailFetcher()
        assert fetcher._service is None
        fetcher.move_to_trash("msg-456")


# ---------------------------------------------------------------------------
# Post-delivery sequencing in NewsletterAgent
# ---------------------------------------------------------------------------

class TestPostDeliverySequencing:
    """Tests for mark_as_read → move_to_trash sequencing after successful delivery."""

    def _make_config(self):
        from agent.utils.config import AgentConfiguration
        from agent.utils.models import SenderConfig
        cfg = AgentConfiguration(
            senders=[SenderConfig(address="newsletter@example.com", mode="summarize")],
            subject_keywords=[],
            batch_size=10,
        )
        cfg.anthropic_api_key = "test-key"
        cfg.gmail_token_path = "test-token.json"
        cfg.delivery_recipient = "recipient@example.com"
        cfg.smtp_host = "smtp.example.com"
        cfg.smtp_port = 587
        cfg.smtp_user = "user@example.com"
        cfg.smtp_password = "password"
        return cfg

    def test_mark_as_read_called_per_message_on_success(self, mocker):
        """mark_as_read() is called for each gmail_message_id after successful delivery."""
        from datetime import datetime, timezone
        from agent.runner import NewsletterAgent
        from agent.utils.models import Email, Summary, DigestEntry

        config = self._make_config()
        agent = NewsletterAgent(config=config)

        # Mock fetcher to return 2 emails
        mock_emails = [
            Email(
                id=f"id-{i}", source="gmail", sender="newsletter@example.com",
                subject=f"Newsletter {i}",
                received_at=datetime(2026, 3, 19, 7, i, 0, tzinfo=timezone.utc),
                raw_html="<p>Content.</p>",
                gmail_message_id=f"gmail-{i}",
            )
            for i in range(2)
        ]
        mocker.patch.object(agent._fetcher, "fetch_newsletters", return_value=mock_emails)

        # Mock parser
        def mock_parse(email, sender_config=None):
            import dataclasses
            return dataclasses.replace(email, plain_text="Content.", links=(), images=())
        mocker.patch.object(agent._parser, "parse", side_effect=mock_parse)

        # Mock summarizer
        def mock_summarize(email):
            return Summary(
                email_id=email.id, sender=email.sender, subject=email.subject,
                summary_text="Summary.", word_count=1,
                generated_at=datetime(2026, 3, 19, tzinfo=timezone.utc),
            )
        mocker.patch.object(agent._summarizer, "summarize", side_effect=mock_summarize)

        # Mock builder
        mocker.patch.object(agent._builder, "build", return_value="<html>digest</html>")

        # Mock delivery to succeed
        mocker.patch.object(agent._delivery, "send")

        # Mock fetcher mark/trash methods
        mock_mark = mocker.patch.object(agent._fetcher, "mark_as_read")
        mock_trash = mocker.patch.object(agent._fetcher, "move_to_trash")

        agent.run()

        # mark_as_read should be called for each gmail_message_id
        assert mock_mark.call_count == 2
        mark_ids = {c.args[0] for c in mock_mark.call_args_list}
        assert "gmail-0" in mark_ids
        assert "gmail-1" in mark_ids

    def test_move_to_trash_called_after_mark_as_read(self, mocker):
        """move_to_trash() is called for each gmail_message_id after mark_as_read."""
        from datetime import datetime, timezone
        from agent.runner import NewsletterAgent
        from agent.utils.models import Email, Summary

        config = self._make_config()
        agent = NewsletterAgent(config=config)

        mock_emails = [
            Email(
                id="id-0", source="gmail", sender="newsletter@example.com",
                subject="Newsletter",
                received_at=datetime(2026, 3, 19, 7, 0, 0, tzinfo=timezone.utc),
                raw_html="<p>Content.</p>",
                gmail_message_id="gmail-0",
            )
        ]
        mocker.patch.object(agent._fetcher, "fetch_newsletters", return_value=mock_emails)

        def mock_parse(email, sender_config=None):
            import dataclasses
            return dataclasses.replace(email, plain_text="Content.", links=(), images=())
        mocker.patch.object(agent._parser, "parse", side_effect=mock_parse)

        def mock_summarize(email):
            return Summary(
                email_id=email.id, sender=email.sender, subject=email.subject,
                summary_text="Summary.", word_count=1,
                generated_at=datetime(2026, 3, 19, tzinfo=timezone.utc),
            )
        mocker.patch.object(agent._summarizer, "summarize", side_effect=mock_summarize)
        mocker.patch.object(agent._builder, "build", return_value="<html>digest</html>")
        mocker.patch.object(agent._delivery, "send")

        call_order = []
        mocker.patch.object(agent._fetcher, "mark_as_read", side_effect=lambda mid: call_order.append(f"mark:{mid}"))
        mocker.patch.object(agent._fetcher, "move_to_trash", side_effect=lambda mid: call_order.append(f"trash:{mid}"))

        agent.run()

        assert call_order == ["mark:gmail-0", "trash:gmail-0"]

    def test_mark_and_trash_not_called_when_delivery_fails(self, mocker):
        """Neither mark_as_read nor move_to_trash is called when delivery fails."""
        from datetime import datetime, timezone
        from agent.runner import NewsletterAgent
        from agent.utils.models import Email, Summary
        from agent.utils.exceptions import DeliveryError

        config = self._make_config()
        agent = NewsletterAgent(config=config)

        mock_emails = [
            Email(
                id="id-0", source="gmail", sender="newsletter@example.com",
                subject="Newsletter",
                received_at=datetime(2026, 3, 19, 7, 0, 0, tzinfo=timezone.utc),
                raw_html="<p>Content.</p>",
                gmail_message_id="gmail-0",
            )
        ]
        mocker.patch.object(agent._fetcher, "fetch_newsletters", return_value=mock_emails)

        def mock_parse(email, sender_config=None):
            import dataclasses
            return dataclasses.replace(email, plain_text="Content.", links=(), images=())
        mocker.patch.object(agent._parser, "parse", side_effect=mock_parse)

        def mock_summarize(email):
            return Summary(
                email_id=email.id, sender=email.sender, subject=email.subject,
                summary_text="Summary.", word_count=1,
                generated_at=datetime(2026, 3, 19, tzinfo=timezone.utc),
            )
        mocker.patch.object(agent._summarizer, "summarize", side_effect=mock_summarize)
        mocker.patch.object(agent._builder, "build", return_value="<html>digest</html>")

        # Delivery fails
        mocker.patch.object(agent._delivery, "send", side_effect=DeliveryError("SMTP failed"))

        mock_mark = mocker.patch.object(agent._fetcher, "mark_as_read")
        mock_trash = mocker.patch.object(agent._fetcher, "move_to_trash")

        agent.run()  # Should not raise — delivery errors are logged, not re-raised

        mock_mark.assert_not_called()
        mock_trash.assert_not_called()

    def test_dry_run_does_not_call_mark_or_trash(self, mocker):
        """In --dry-run mode, mark_as_read and move_to_trash are never called."""
        from datetime import datetime, timezone
        from agent.runner import NewsletterAgent
        from agent.utils.models import Email, Summary

        config = self._make_config()
        agent = NewsletterAgent(config=config, dry_run=True)

        mock_emails = [
            Email(
                id="id-0", source="gmail", sender="newsletter@example.com",
                subject="Newsletter",
                received_at=datetime(2026, 3, 19, 7, 0, 0, tzinfo=timezone.utc),
                raw_html="<p>Content.</p>",
                gmail_message_id="gmail-0",
            )
        ]
        mocker.patch.object(agent._fetcher, "fetch_newsletters", return_value=mock_emails)

        def mock_parse(email, sender_config=None):
            import dataclasses
            return dataclasses.replace(email, plain_text="Content.", links=(), images=())
        mocker.patch.object(agent._parser, "parse", side_effect=mock_parse)

        def mock_summarize(email):
            return Summary(
                email_id=email.id, sender=email.sender, subject=email.subject,
                summary_text="Summary.", word_count=1,
                generated_at=datetime(2026, 3, 19, tzinfo=timezone.utc),
            )
        mocker.patch.object(agent._summarizer, "summarize", side_effect=mock_summarize)
        mocker.patch.object(agent._builder, "build", return_value="<html>digest</html>")

        mock_mark = mocker.patch.object(agent._fetcher, "mark_as_read")
        mock_trash = mocker.patch.object(agent._fetcher, "move_to_trash")

        agent.run()

        mock_mark.assert_not_called()
        mock_trash.assert_not_called()
