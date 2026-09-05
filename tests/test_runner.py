"""Tests for agent/runner.py — dry-run mode (US2)."""
from unittest.mock import MagicMock
from datetime import datetime, timezone

from agent.runner import NewsletterAgent
from agent.utils.config import KnowledgeConfig, UserProfile
from agent.utils.models import Email, EntityContext, Summary, Idea, EntityMention


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


class TestNewsletterAgentConstruction:
    """NewsletterAgent.__init__ must wire config through to its collaborators."""

    def test_summarizer_receives_knowledge_config(self, mock_config, mocker):
        """The summarizer must receive knowledge_config so entity extraction runs (FR gap fix)."""
        mock_config.knowledge = KnowledgeConfig(enabled=True)
        mocker.patch("agent.runner.GmailFetcher")
        mocker.patch("agent.runner.EmailDelivery")
        mock_summarizer_cls = mocker.patch("agent.runner.ClaudeSummarizer")

        NewsletterAgent(config=mock_config)

        mock_summarizer_cls.assert_called_once()
        assert mock_summarizer_cls.call_args.kwargs["knowledge_config"] is mock_config.knowledge

    def test_summarizer_receives_configured_model(self, mock_config, mocker):
        """The summarizer must receive the configured model, not a hard-coded default."""
        mock_config.model = "claude-test-x"
        mocker.patch("agent.runner.GmailFetcher")
        mocker.patch("agent.runner.EmailDelivery")
        mock_summarizer_cls = mocker.patch("agent.runner.ClaudeSummarizer")

        NewsletterAgent(config=mock_config)

        mock_summarizer_cls.assert_called_once()
        assert mock_summarizer_cls.call_args.kwargs["model"] == "claude-test-x"

    def test_advisor_receives_configured_model(self, mock_config, mocker):
        """The advisor must receive the configured model when constructed inside _run_digest."""
        mock_config.model = "claude-test-x"
        mock_config.user_profile = UserProfile()

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
        mocker.patch("agent.runner.EmailDelivery.send")
        mock_advisor_cls = mocker.patch("agent.advisor.analyzer.AdvisorAnalyzer")

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()

        mock_advisor_cls.assert_called_once()
        assert mock_advisor_cls.call_args.kwargs["model"] == "claude-test-x"


class TestThemeSynthesis:
    """Tests for theme synthesis integration in runner."""

    def test_synthesis_skipped_when_flag_off(self, mock_config, mocker):
        """synthesis_enabled=False -> ThemeSynthesizer not called."""
        mock_config.knowledge = KnowledgeConfig(enabled=True, synthesis_enabled=False)

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
        mock_synthesizer = mocker.patch("agent.runner.ThemeSynthesizer")

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()

        mock_synthesizer.assert_not_called()

    def test_synthesis_runs_when_flag_on(self, mock_config, mocker):
        """synthesis_enabled=True -> ThemeSynthesizer called and themes passed to batch."""
        mock_config.knowledge = KnowledgeConfig(enabled=True, synthesis_enabled=True)

        # Create entries with ideas that share entities
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")

        mock_emails = [
            Email(id="msg-1", source="gmail", sender="a@x.com",
                  subject="Bloomberg", received_at=datetime(2026,3,9,7,0,tzinfo=timezone.utc),
                  raw_html="<p>x</p>", plain_text="x"),
            Email(id="msg-2", source="gmail", sender="b@x.com",
                  subject="AI Journal", received_at=datetime(2026,3,9,7,0,tzinfo=timezone.utc),
                  raw_html="<p>x</p>", plain_text="x"),
        ]
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=mock_emails)
        mocker.patch("agent.runner.EmailParser.parse", side_effect=lambda e, sender_config=None: e)

        # Summaries with ideas
        summary1 = Summary(
            email_id="msg-1", sender="a@x.com", subject="Bloomberg",
            summary_text="", word_count=0,
            generated_at=datetime(2026,3,9,7,1,tzinfo=timezone.utc),
            ideas=(Idea(title="Idea 1", summary_text="Nvidia faces curbs", entities=(e1, e2)),)
        )
        summary2 = Summary(
            email_id="msg-2", sender="b@x.com", subject="AI Journal",
            summary_text="", word_count=0,
            generated_at=datetime(2026,3,9,7,1,tzinfo=timezone.utc),
            ideas=(Idea(title="Idea 2", summary_text="Export controls expand", entities=(e1, e2)),)
        )
        mocker.patch("agent.runner.ClaudeSummarizer.summarize", side_effect=[summary1, summary2])
        mocker.patch("agent.runner.DigestBuilder.build", return_value="<html>digest</html>")

        # Mock ThemeSynthesizer to return a theme
        mock_theme = MagicMock()
        mock_synthesizer_instance = MagicMock()
        mock_synthesizer_instance.synthesize.return_value = (mock_theme,)
        mock_synthesizer_cls = mocker.patch("agent.runner.ThemeSynthesizer", return_value=mock_synthesizer_instance)

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()

        mock_synthesizer_cls.assert_called_once_with(
            api_key=mock_config.anthropic_api_key, model=mock_config.model
        )
        mock_synthesizer_instance.synthesize.assert_called_once()


class TestDigestStoreContext:
    """Tests for recurring-entity context wiring in the runner (plan 03, step 5)."""

    def _setup_digest(self, mock_config, mocker, summary):
        mock_email = Email(
            id="msg-1", source="gmail", sender="a@example.com",
            subject="Test", received_at=datetime(2026, 3, 9, 7, 0, tzinfo=timezone.utc),
            raw_html="<p>hello</p>", plain_text="hello",
        )
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=[mock_email])
        mocker.patch("agent.runner.EmailParser.parse", return_value=mock_email)
        mocker.patch("agent.runner.ClaudeSummarizer.summarize", return_value=summary)
        mocker.patch("agent.runner.DigestBuilder.build", return_value="<html>digest</html>")
        mocker.patch("agent.runner.EmailDelivery.send")

    def _idea_summary(self):
        return Summary(
            email_id="msg-1", sender="a@example.com", subject="Test",
            summary_text="", word_count=0,
            generated_at=datetime(2026, 3, 9, 7, 1, tzinfo=timezone.utc),
            ideas=(Idea(
                title="Nvidia idea", summary_text="Nvidia news.",
                entities=(EntityMention(name="Nvidia", entity_type="company", sentiment="positive"),),
            ),),
        )

    def test_store_opened_for_reads_in_dry_run_but_record_not_called(self, mock_config, mocker, tmp_path):
        """Dry-run opens the store for reads but never records observations."""
        mock_config.knowledge = KnowledgeConfig(enabled=True, db_path=str(tmp_path / "signals.db"))
        self._setup_digest(mock_config, mocker, self._idea_summary())
        mock_store_cls = mocker.patch("agent.knowledge.store.ObservationStore")
        mock_store_cls.return_value.recent_context.return_value = {}
        mock_advisor_cls = mocker.patch("agent.advisor.analyzer.AdvisorAnalyzer")

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()

        mock_store_cls.assert_called_once_with(str(tmp_path / "signals.db"))
        mock_store_cls.return_value.record_summary.assert_not_called()
        mock_store_cls.return_value.recent_context.assert_called_once()
        mock_advisor_cls.assert_not_called()  # no user profile configured

    def test_advisor_receives_entity_context(self, mock_config, mocker, tmp_path):
        """The advisor call receives the entity_context from the single store query."""
        mock_config.knowledge = KnowledgeConfig(enabled=True, db_path=str(tmp_path / "signals.db"))
        mock_config.user_profile = UserProfile()
        self._setup_digest(mock_config, mocker, self._idea_summary())
        mocker.patch("agent.runner.DigestBuilder.build", return_value="<html>digest</html>")
        mock_store_cls = mocker.patch("agent.knowledge.store.ObservationStore")
        context = {"nvidia": EntityContext(
            name="Nvidia", mentions=5, distinct_senders=3, days_active=4, net_sentiment=0.6,
        )}
        mock_store_cls.return_value.recent_context.return_value = context
        mock_advisor_cls = mocker.patch("agent.advisor.analyzer.AdvisorAnalyzer")

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()

        mock_store_cls.return_value.recent_context.assert_called_once()
        mock_advisor_cls.return_value.analyze.assert_called_once()
        assert mock_advisor_cls.return_value.analyze.call_args.kwargs["entity_context"] == context

    def test_context_window_excludes_run_date(self, mock_config, mocker, tmp_path):
        """The store query window ends at the start of the run date (today excluded)."""
        mock_config.knowledge = KnowledgeConfig(enabled=True, db_path=str(tmp_path / "signals.db"))
        self._setup_digest(mock_config, mocker, self._idea_summary())
        mock_store_cls = mocker.patch("agent.knowledge.store.ObservationStore")
        mock_store_cls.return_value.recent_context.return_value = {}

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        run_date = datetime(2026, 9, 5, 15, 30, tzinfo=timezone.utc)
        agent._run_digest(run_date)

        _, since, until = mock_store_cls.return_value.recent_context.call_args[0]
        assert since == datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
        assert until == datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)

    def test_no_store_query_when_knowledge_disabled(self, mock_config, mocker):
        """knowledge=None -> no store opened, advisor gets empty context."""
        mock_config.user_profile = UserProfile()
        self._setup_digest(mock_config, mocker, self._idea_summary())
        mock_store_cls = mocker.patch("agent.knowledge.store.ObservationStore")
        mock_advisor_cls = mocker.patch("agent.advisor.analyzer.AdvisorAnalyzer")

        agent = NewsletterAgent(config=mock_config, dry_run=True)
        agent.run()

        mock_store_cls.assert_not_called()
        assert mock_advisor_cls.return_value.analyze.call_args.kwargs["entity_context"] == {}
