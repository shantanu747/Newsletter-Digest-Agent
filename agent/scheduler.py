"""DigestScheduler — runs NewsletterAgent on a daily cron schedule via APScheduler."""
from __future__ import annotations

import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from agent.utils.config import AgentConfiguration, load_config
from agent.utils.exceptions import ConfigurationError, DeliveryError, FetchError, SummarizationError
from agent.utils.logger import get_logger

log = get_logger(__name__)


class DigestScheduler:
    """Wraps APScheduler to trigger a daily NewsletterAgent run."""

    def __init__(self, config: AgentConfiguration) -> None:
        self.config = config
        self._scheduler = BlockingScheduler(timezone=config.schedule_timezone)

    def _run_agent(self) -> None:
        """Job function — catch known pipeline errors so the scheduler survives transient
        failures, but let unexpected exceptions propagate so bugs are not silently swallowed."""
        # Import here to avoid circular imports at module load time
        from agent.runner import NewsletterAgent
        try:
            log.info("scheduled_run_started")
            NewsletterAgent(config=self.config).run()
        except (FetchError, SummarizationError, DeliveryError) as exc:
            log.error("scheduled_run_failed", error=str(exc))

    def start(self) -> None:
        """Add the daily job and start the blocking scheduler."""
        trigger = CronTrigger(
            hour=self.config.schedule_hour,
            minute=self.config.schedule_minute,
            timezone=self.config.schedule_timezone,
        )
        self._scheduler.add_job(
            self._run_agent,
            trigger=trigger,
            misfire_grace_time=600,  # 10-minute grace window
        )
        next_run = self._scheduler.get_jobs()[0].next_run_time if self._scheduler.get_jobs() else "unknown"
        log.info(
            "scheduler_started",
            hour=self.config.schedule_hour,
            minute=self.config.schedule_minute,
            timezone=self.config.schedule_timezone,
            next_run=str(next_run),
        )
        self._scheduler.start()


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
