"""DigestScheduler — runs NewsletterAgent on a recurring interval via APScheduler.

Uses IntervalTrigger(hours=config.poll_interval_hours) so the agent polls every N
hours regardless of time-of-day. The first poll runs immediately on startup before
the scheduler begins counting intervals.
"""
from __future__ import annotations

import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.utils.config import AgentConfiguration, load_config
from agent.utils.exceptions import ConfigurationError, DeliveryError, FetchError, SummarizationError
from agent.utils.logger import get_logger

log = get_logger(__name__)


class DigestScheduler:
    """Wraps APScheduler to trigger NewsletterAgent runs every poll_interval_hours."""

    def __init__(self, config: AgentConfiguration) -> None:
        self.config = config
        self._scheduler = BlockingScheduler(timezone=config.schedule_timezone)

    def _run_agent(self) -> None:
        """Job function — catch known pipeline errors so the scheduler survives transient
        failures, but let unexpected exceptions propagate so bugs are not silently swallowed."""
        from agent.runner import NewsletterAgent
        try:
            log.info("scheduled_run_started")
            NewsletterAgent(config=self.config).run()
        except (FetchError, SummarizationError, DeliveryError) as exc:
            log.error("scheduled_run_failed", error=str(exc))

    def start(self) -> None:
        """Run once immediately, then start the blocking interval scheduler.

        The immediate first run drains any backlog. Subsequent runs fire every
        config.poll_interval_hours hours. Clean shutdown on KeyboardInterrupt.
        """
        trigger = IntervalTrigger(hours=self.config.poll_interval_hours)
        self._scheduler.add_job(
            self._run_agent,
            trigger=trigger,
            misfire_grace_time=600,  # 10-minute grace window
        )

        log.info(
            "scheduler_started",
            poll_interval_hours=self.config.poll_interval_hours,
            timezone=self.config.schedule_timezone,
        )

        # Immediate first execution — drains backlog before interval starts
        self._run_agent()

        try:
            self._scheduler.start()
        except KeyboardInterrupt:
            self._scheduler.shutdown()
            log.info("scheduler_stopped")


def main() -> None:
    try:
        config = load_config()
    except ConfigurationError as exc:
        log.error("configuration_error", error=str(exc))
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    DigestScheduler(config).start()


if __name__ == "__main__":
    main()
