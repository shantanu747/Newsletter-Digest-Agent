"""Unit tests for DigestScheduler."""
from __future__ import annotations

import pytest

from agent.scheduler import DigestScheduler
from agent.utils.exceptions import FetchError
from apscheduler.triggers.interval import IntervalTrigger
from datetime import timedelta


class TestDigestScheduler:
    def test_start_adds_cron_job(self, mock_config, mocker):
        mock_scheduler_cls = mocker.patch("agent.scheduler.BlockingScheduler")
        mock_scheduler = mock_scheduler_cls.return_value
        mock_scheduler.get_jobs.return_value = []

        scheduler = DigestScheduler(mock_config)
        mock_scheduler.start.return_value = None
        scheduler.start()

        assert mock_scheduler.add_job.called
        call_args = mock_scheduler.add_job.call_args

        # First positional arg is the job function
        job_fn = call_args.args[0]
        assert job_fn == scheduler._run_agent

        # trigger is passed as a keyword argument
        trigger = call_args.kwargs["trigger"]
        assert isinstance(trigger, IntervalTrigger)

        # Verify the trigger interval matches config poll_interval_hours
        assert trigger.interval == timedelta(hours=mock_config.poll_interval_hours)

    def test_start_calls_scheduler_start(self, mock_config, mocker):
        mock_scheduler_cls = mocker.patch("agent.scheduler.BlockingScheduler")
        mock_scheduler = mock_scheduler_cls.return_value
        mock_scheduler.get_jobs.return_value = []

        scheduler = DigestScheduler(mock_config)
        scheduler.start()

        mock_scheduler.start.assert_called_once()

    def test_start_misfire_grace_time(self, mock_config, mocker):
        mock_scheduler_cls = mocker.patch("agent.scheduler.BlockingScheduler")
        mock_scheduler = mock_scheduler_cls.return_value
        mock_scheduler.get_jobs.return_value = []

        scheduler = DigestScheduler(mock_config)
        scheduler.start()

        call_kwargs = mock_scheduler.add_job.call_args[1]
        assert call_kwargs.get("misfire_grace_time") == 600

    def test_run_agent_catches_pipeline_exceptions(self, mock_config, mocker):
        """Known pipeline errors (FetchError etc.) are swallowed so the scheduler survives."""
        mocker.patch("agent.runner.NewsletterAgent.run", side_effect=FetchError("fetch failed"))

        scheduler = DigestScheduler(mock_config)
        # Should not raise — the scheduler must survive known pipeline failures
        scheduler._run_agent()

    def test_run_agent_propagates_unexpected_exceptions(self, mock_config, mocker):
        """Unexpected errors (e.g. programming bugs) must propagate, not be silently swallowed."""
        mocker.patch("agent.runner.NewsletterAgent.run", side_effect=RuntimeError("bug"))

        scheduler = DigestScheduler(mock_config)
        with pytest.raises(RuntimeError, match="bug"):
            scheduler._run_agent()

    def test_run_agent_logs_error_on_pipeline_exception(self, mock_config, mocker):
        mocker.patch("agent.runner.NewsletterAgent.run", side_effect=FetchError("fetch failed"))
        mock_log = mocker.patch("agent.scheduler.log")

        scheduler = DigestScheduler(mock_config)
        scheduler._run_agent()

        mock_log.error.assert_called_once_with(
            "scheduled_run_failed", error="fetch failed"
        )

    def test_run_agent_logs_start_on_success(self, mock_config, mocker):
        mocker.patch("agent.runner.NewsletterAgent.run", return_value=None)
        mock_log = mocker.patch("agent.scheduler.log")

        scheduler = DigestScheduler(mock_config)
        scheduler._run_agent()

        mock_log.info.assert_called_once_with("scheduled_run_started")

    def test_scheduler_initialized_with_timezone(self, mock_config, mocker):
        mock_scheduler_cls = mocker.patch("agent.scheduler.BlockingScheduler")
        DigestScheduler(mock_config)
        mock_scheduler_cls.assert_called_once_with(timezone=mock_config.schedule_timezone)

    def test_start_logs_poll_interval_hours(self, mock_config, mocker):
        """scheduler_started log includes poll_interval_hours matching config."""
        mock_scheduler_cls = mocker.patch("agent.scheduler.BlockingScheduler")
        mock_scheduler = mock_scheduler_cls.return_value
        mock_scheduler.get_jobs.return_value = []
        mock_log = mocker.patch("agent.scheduler.log")

        scheduler = DigestScheduler(mock_config)
        scheduler.start()

        # Locate the scheduler_started log call and verify poll_interval_hours is present
        scheduler_started_calls = [
            call for call in mock_log.info.call_args_list
            if call[0][0] == "scheduler_started"
        ]
        assert scheduler_started_calls, "Expected a 'scheduler_started' log entry"
        assert scheduler_started_calls[0][1]["poll_interval_hours"] == mock_config.poll_interval_hours
