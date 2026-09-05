"""Unit tests for the Signals Report cadence integration in agent/runner.py (T050).

Tests cover:
- job_due false before the interval elapses, true after (store-level, already covered by
  test_observation_store.py — re-verified here at the runner level via job_due mocking)
- mark_job_run called on both the success and the failure path
- maybe_run_signals invoked when fetch_newsletters returns an empty list (SC-006)
- maybe_run_signals invoked even when _run_digest raises
- an analyzer exception does not propagate out of run()
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent.runner import NewsletterAgent
from agent.utils.config import KnowledgeConfig, SignalsConfig
from agent.utils.models import SignalItem, SignalsReport


_NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _make_agent(mock_config, tmp_path, **overrides):
    mock_config.knowledge = overrides.pop("knowledge", KnowledgeConfig(db_path=str(tmp_path / "signals.db")))
    mock_config.signals = overrides.pop("signals", SignalsConfig())
    return NewsletterAgent(config=mock_config, **overrides)


class TestJobDueGating:
    def test_signals_skipped_when_not_due(self, mock_config, mocker, tmp_path):
        agent = _make_agent(mock_config, tmp_path)
        mocker.patch("agent.knowledge.store.ObservationStore.job_due", return_value=False)
        mock_analyzer = mocker.patch("agent.trends.analyzer.TrendAnalyzer")

        agent.maybe_run_signals(_NOW)

        mock_analyzer.assert_not_called()

    def test_signals_runs_when_due(self, mocker, mock_config, tmp_path):
        agent = _make_agent(mock_config, tmp_path)
        mocker.patch("agent.knowledge.store.ObservationStore.job_due", return_value=True)
        mocker.patch("agent.trends.metrics.compute_brief")
        mock_analyzer_cls = mocker.patch("agent.trends.analyzer.TrendAnalyzer")
        mocker.patch("agent.digest.builder.build_signals", return_value="<html></html>")
        mock_send = mocker.patch("agent.digest.delivery.EmailDelivery.send")

        agent.maybe_run_signals(_NOW)

        mock_analyzer_cls.assert_called_once()
        mock_send.assert_called_once()

    def test_force_bypasses_job_due(self, mocker, mock_config, tmp_path):
        agent = _make_agent(mock_config, tmp_path)
        mock_job_due = mocker.patch("agent.knowledge.store.ObservationStore.job_due", return_value=False)
        mocker.patch("agent.trends.metrics.compute_brief")
        mocker.patch("agent.trends.analyzer.TrendAnalyzer")
        mocker.patch("agent.digest.builder.build_signals", return_value="<html></html>")
        mocker.patch("agent.digest.delivery.EmailDelivery.send")

        agent.maybe_run_signals(_NOW, force=True)

        mock_job_due.assert_not_called()


class TestMarkJobRun:
    def test_mark_job_run_called_on_success(self, mocker, mock_config, tmp_path):
        agent = _make_agent(mock_config, tmp_path)
        mocker.patch("agent.knowledge.store.ObservationStore.job_due", return_value=True)
        mocker.patch("agent.trends.metrics.compute_brief")
        mocker.patch("agent.trends.analyzer.TrendAnalyzer")
        mocker.patch("agent.digest.builder.build_signals", return_value="<html></html>")
        mocker.patch("agent.digest.delivery.EmailDelivery.send")
        mock_mark = mocker.patch("agent.knowledge.store.ObservationStore.mark_job_run")

        agent.maybe_run_signals(_NOW)

        mock_mark.assert_called_once_with("signals_report", "success", _NOW)

    def test_mark_job_run_called_on_failure(self, mocker, mock_config, tmp_path):
        agent = _make_agent(mock_config, tmp_path)
        mocker.patch("agent.knowledge.store.ObservationStore.job_due", return_value=True)
        mocker.patch("agent.trends.metrics.compute_brief", side_effect=RuntimeError("boom"))
        mock_mark = mocker.patch("agent.knowledge.store.ObservationStore.mark_job_run")

        agent.maybe_run_signals(_NOW)  # must not raise

        mock_mark.assert_called_once_with("signals_report", "failure", _NOW)

    def test_dry_run_does_not_call_mark_job_run(self, mocker, mock_config, tmp_path):
        agent = _make_agent(mock_config, tmp_path)
        mocker.patch("agent.knowledge.store.ObservationStore.job_due", return_value=True)
        mocker.patch("agent.trends.metrics.compute_brief")
        mocker.patch("agent.trends.analyzer.TrendAnalyzer")
        mocker.patch("agent.digest.builder.build_signals", return_value="<html></html>")
        mock_send = mocker.patch("agent.digest.delivery.EmailDelivery.send")
        mock_mark = mocker.patch("agent.knowledge.store.ObservationStore.mark_job_run")

        agent.maybe_run_signals(_NOW, dry_run=True)

        mock_send.assert_not_called()
        mock_mark.assert_not_called()


class TestRunIntegration:
    def test_maybe_run_signals_invoked_on_empty_inbox(self, mocker, mock_config, tmp_path):
        """SC-006: an empty inbox must not suppress a due Signals Report."""
        agent = _make_agent(mock_config, tmp_path)
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=[])
        mock_maybe = mocker.patch.object(agent, "maybe_run_signals")

        agent.run()

        mock_maybe.assert_called_once()

    def test_maybe_run_signals_invoked_when_digest_raises(self, mocker, mock_config, tmp_path):
        from agent.utils.exceptions import FetchError

        agent = _make_agent(mock_config, tmp_path)
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", side_effect=FetchError("boom"))
        mock_maybe = mocker.patch.object(agent, "maybe_run_signals")

        try:
            agent.run()
        except FetchError:
            pass

        mock_maybe.assert_called_once()

    def test_skip_signals_suppresses_maybe_run_signals(self, mocker, mock_config):
        mock_config.knowledge = KnowledgeConfig()
        mock_config.signals = SignalsConfig()
        agent = NewsletterAgent(config=mock_config, skip_signals=True)
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=[])
        mock_maybe = mocker.patch.object(agent, "maybe_run_signals")

        agent.run()

        mock_maybe.assert_not_called()

    def test_analyzer_exception_does_not_propagate_out_of_run(self, mocker, mock_config, tmp_path):
        agent = _make_agent(mock_config, tmp_path)
        mocker.patch("agent.runner.GmailFetcher.fetch_newsletters", return_value=[])
        mocker.patch("agent.knowledge.store.ObservationStore.job_due", return_value=True)
        mocker.patch("agent.trends.metrics.compute_brief", side_effect=RuntimeError("analyzer exploded"))
        mocker.patch("agent.knowledge.store.ObservationStore.mark_job_run")

        agent.run()  # must not raise


def _make_report(**overrides) -> SignalsReport:
    defaults = dict(
        generated_at=_NOW,
        window_days=7,
        macro=None,
        risks=(SignalItem(headline="Risk", body="Body.", confidence="HIGH", entities=("Nvidia",)),),
    )
    defaults.update(overrides)
    return SignalsReport(**defaults)


class TestTrackRecordWiring:
    def _setup(self, mocker, mock_config, tmp_path, **overrides):
        agent = _make_agent(mock_config, tmp_path, signals=SignalsConfig(**overrides))
        mocker.patch("agent.knowledge.store.ObservationStore.job_due", return_value=True)
        mocker.patch("agent.trends.metrics.compute_brief")
        mocker.patch("agent.prices.stooq.StooqPriceFetcher")
        mock_build = mocker.patch(
            "agent.trends.track_record.build_track_record", return_value=()
        )
        mock_analyzer_cls = mocker.patch("agent.trends.analyzer.TrendAnalyzer")
        mock_analyzer_cls.return_value.analyze.return_value = _make_report()
        mocker.patch("agent.digest.builder.build_signals", return_value="<html></html>")
        mocker.patch("agent.digest.delivery.EmailDelivery.send")
        return agent, mock_build

    def test_record_calls_and_reviews_on_real_run(self, mocker, mock_config, tmp_path):
        agent, mock_build = self._setup(mocker, mock_config, tmp_path)
        mock_record_calls = mocker.patch("agent.knowledge.store.ObservationStore.record_signal_calls")
        mock_record_reviews = mocker.patch("agent.knowledge.store.ObservationStore.record_reviews")

        agent.maybe_run_signals(_NOW)

        mock_build.assert_called_once()
        mock_record_calls.assert_called_once()
        mock_record_reviews.assert_called_once()

    def test_dry_run_computes_but_records_nothing(self, mocker, mock_config, tmp_path):
        agent, mock_build = self._setup(mocker, mock_config, tmp_path)
        mock_record_calls = mocker.patch("agent.knowledge.store.ObservationStore.record_signal_calls")
        mock_record_reviews = mocker.patch("agent.knowledge.store.ObservationStore.record_reviews")
        mock_send = mocker.patch("agent.digest.delivery.EmailDelivery.send")

        agent.maybe_run_signals(_NOW, dry_run=True)

        mock_build.assert_called_once()
        mock_send.assert_not_called()
        mock_record_calls.assert_not_called()
        mock_record_reviews.assert_not_called()

    def test_nothing_recorded_when_send_raises(self, mocker, mock_config, tmp_path):
        agent, mock_build = self._setup(mocker, mock_config, tmp_path)
        from agent.utils.exceptions import DeliveryError

        mocker.patch("agent.digest.delivery.EmailDelivery.send", side_effect=DeliveryError("boom"))
        mock_record_calls = mocker.patch("agent.knowledge.store.ObservationStore.record_signal_calls")
        mock_record_reviews = mocker.patch("agent.knowledge.store.ObservationStore.record_reviews")

        agent.maybe_run_signals(_NOW)  # must not raise

        mock_record_calls.assert_not_called()
        mock_record_reviews.assert_not_called()

    def test_flag_off_skips_build_track_record(self, mocker, mock_config, tmp_path):
        agent, mock_build = self._setup(
            mocker, mock_config, tmp_path, track_record_enabled=False
        )
        mocker.patch("agent.knowledge.store.ObservationStore.record_signal_calls")
        mocker.patch("agent.knowledge.store.ObservationStore.record_reviews")

        agent.maybe_run_signals(_NOW)

        mock_build.assert_not_called()
