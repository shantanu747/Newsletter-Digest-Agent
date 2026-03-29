"""Tests for agent/runner.py — dry-run mode (US2)."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from agent.runner import NewsletterAgent
from agent.utils.models import Email, Summary, DigestEntry


class TestDryRun:
    def test_dry_run_does_not_call_delivery(self, mock_config, mocker):
        """--dry-run must not invoke EmailDelivery.send."""
        mock_email = Email(
            id="msg-1", source="gmail", sender="a@example.com",
            subject="Test", received_at=datetime(2026,3,9,7,0,tzinfo=timezone.utc),
            raw_html="<p>hello</p>", plain_text="hello"
        )
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=[mock_email])
        mocker.patch("agent.runner.EmailParser.parse", return_value=mock_email)
        mock_summary = Summary(
            email_id="msg-1", sender="a@example.com", subject="Test",
            summary_text="word " * 225, word_count=225,
            generated_at=datetime(2026,3,9,7,1,tzinfo=timezone.utc)
        )
        mocker.patch("agent.runner.ClaudeSummarizer.summarize", return_value=mock_summary)
        mocker.patch("agent.runner.DigestBuilder.build", return_value="<html>digest</html>")
        mock_send = mocker.patch("agent.runner.EmailDelivery.send")

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()

        mock_send.assert_not_called()

    def test_dry_run_with_summarization_error_continues(self, mock_config, mocker):
        """dry-run should continue processing when one newsletter fails."""
        from agent.utils.exceptions import SummarizationError
        emails = [
            Email(id=f"msg-{i}", source="gmail", sender="a@example.com",
                  subject=f"Newsletter {i}", received_at=datetime(2026,3,9,7,0,tzinfo=timezone.utc),
                  raw_html="<p>x</p>", plain_text="x")
            for i in range(3)
        ]
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=emails)
        mocker.patch("agent.runner.EmailParser.parse", side_effect=lambda e, sender_config=None: e)
        mocker.patch("agent.runner.ClaudeSummarizer.summarize", side_effect=SummarizationError("fail"))
        mocker.patch("agent.runner.DigestBuilder.build", return_value="<html></html>")
        mocker.patch("agent.runner.EmailDelivery.send")

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()  # must not raise

    def test_no_newsletters_exits_early(self, mock_config, mocker):
        """When no newsletters found, build and send must not be called."""
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=[])
        mock_build = mocker.patch("agent.runner.DigestBuilder.build")
        mock_send = mocker.patch("agent.runner.EmailDelivery.send")

        agent = NewsletterAgent(config=mock_config, dry_run=False)
        agent.run()

        mock_build.assert_not_called()
        mock_send.assert_not_called()

    def test_deduplication_and_cap(self, mock_config, mocker):
        """Duplicate email IDs are deduplicated; max_newsletters_per_run is enforced."""
        mock_config.max_newsletters_per_run = 2
        emails = [
            Email(id="dup", source="gmail", sender="a@example.com", subject="Dup",
                  received_at=datetime(2026,3,9,7,0,tzinfo=timezone.utc), raw_html="x", plain_text="x"),
            Email(id="dup", source="gmail", sender="a@example.com", subject="Dup",
                  received_at=datetime(2026,3,9,7,0,tzinfo=timezone.utc), raw_html="x", plain_text="x"),
            Email(id="extra", source="gmail", sender="b@example.com", subject="Extra",
                  received_at=datetime(2026,3,9,7,0,tzinfo=timezone.utc), raw_html="x", plain_text="x"),
            Email(id="over-cap", source="gmail", sender="c@example.com", subject="Over",
                  received_at=datetime(2026,3,9,7,0,tzinfo=timezone.utc), raw_html="x", plain_text="x"),
        ]
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=emails)
        mocker.patch("agent.runner.EmailParser.parse", side_effect=lambda e, sender_config=None: e)
        summarize_calls = []
        mock_summary = Summary(
            email_id="x", sender="x", subject="x",
            summary_text="w "*225, word_count=225,
            generated_at=datetime(2026,3,9,tzinfo=timezone.utc)
        )
        def capture_summarize(e):
            summarize_calls.append(e.id)
            return mock_summary
        mocker.patch("agent.runner.ClaudeSummarizer.summarize", side_effect=capture_summarize)
        mocker.patch("agent.runner.DigestBuilder.build", return_value="<html></html>")
        mocker.patch("agent.runner.EmailDelivery.send")

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()

        # After dedup: "dup" and "extra" remain (2); cap=2 so "over-cap" dropped
        assert len(summarize_calls) == 2
        assert "dup" in summarize_calls
        assert "extra" in summarize_calls


class TestPreviewMode:
    """--preview delivers email but skips Gmail mutations."""

    def _setup(self, mock_config, mocker):
        mock_email = Email(
            id="msg-1", source="gmail", sender="a@example.com",
            subject="Test", received_at=datetime(2026, 3, 9, 7, 0, tzinfo=timezone.utc),
            raw_html="<p>hello</p>", plain_text="hello",
        )
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=[mock_email])
        mocker.patch("agent.runner.EmailParser.parse", return_value=mock_email)
        mock_summary = Summary(
            email_id="msg-1", sender="a@example.com", subject="Test",
            summary_text="word " * 225, word_count=225,
            generated_at=datetime(2026, 3, 9, 7, 1, tzinfo=timezone.utc),
        )
        mocker.patch("agent.runner.ClaudeSummarizer.summarize", return_value=mock_summary)
        mocker.patch("agent.runner.DigestBuilder.build", return_value="<html>digest</html>")
        mock_send = mocker.patch("agent.runner.EmailDelivery.send")
        mock_mark = mocker.patch("agent.runner.GmailFetcher.mark_as_read")
        mock_trash = mocker.patch("agent.runner.GmailFetcher.move_to_trash")
        return mock_send, mock_mark, mock_trash

    def test_preview_delivers_email(self, mock_config, mocker):
        """--preview must invoke EmailDelivery.send."""
        mock_send, _, _ = self._setup(mock_config, mocker)
        agent = NewsletterAgent(config=mock_config, preview=True)
        agent.run()
        mock_send.assert_called_once()

    def test_preview_does_not_mark_as_read(self, mock_config, mocker):
        """--preview must not call mark_as_read."""
        _, mock_mark, _ = self._setup(mock_config, mocker)
        agent = NewsletterAgent(config=mock_config, preview=True)
        agent.run()
        mock_mark.assert_not_called()

    def test_preview_does_not_move_to_trash(self, mock_config, mocker):
        """--preview must not call move_to_trash."""
        _, _, mock_trash = self._setup(mock_config, mocker)
        agent = NewsletterAgent(config=mock_config, preview=True)
        agent.run()
        mock_trash.assert_not_called()


class TestMainSchedulerRouting:
    """main() must route to DigestScheduler or single run based on flags."""

    def _call_main(self, mocker, argv: list[str]):
        mocker.patch("sys.argv", ["agent"] + argv)
        mocker.patch("agent.runner.load_config", return_value=mocker.MagicMock())

    def test_once_flag_skips_scheduler(self, mocker):
        """--once must run a single poll and never start the scheduler."""
        self._call_main(mocker, ["--once"])
        mock_run = mocker.patch("agent.runner.NewsletterAgent.run")
        mock_scheduler = mocker.patch("agent.scheduler.DigestScheduler.start")

        from agent.runner import main
        main()

        mock_run.assert_called_once()
        mock_scheduler.assert_not_called()

    def test_no_flags_starts_scheduler(self, mocker):
        """No flags must start DigestScheduler instead of a direct run."""
        self._call_main(mocker, [])
        mocker.patch("agent.runner.NewsletterAgent.run")
        mock_scheduler_cls = mocker.patch("agent.scheduler.DigestScheduler")

        from agent.runner import main
        main()

        mock_scheduler_cls.assert_called_once()
        mock_scheduler_cls.return_value.start.assert_called_once()
