"""Structured JSON logging configuration using structlog.

Usage:
    from agent.utils.logger import get_logger
    log = get_logger(__name__)
    log.info("newsletter_processed", message_id="abc123", sender="hello@example.com")
"""

import logging
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import structlog

LOG_RETENTION_DAYS = 30
_LOG_DIR_ENV = "NEWSLETTER_LOG_DIR"
_DAILY_LOG_RE = re.compile(r"^digest-(\d{4}-\d{2}-\d{2})\.log$")


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _default_log_dir() -> Path:
    override = os.environ.get(_LOG_DIR_ENV)
    if override:
        return Path(override)
    # Anchor on the repo, not the cwd: launchd's working directory may differ.
    return Path(__file__).resolve().parents[2] / "logs"


def prune_old_logs(
    log_dir: Path | str,
    retention_days: int = LOG_RETENTION_DAYS,
    today: date | None = None,
) -> list[Path]:
    """Delete expired ``digest-YYYY-MM-DD.log`` files and stale ``*.bak`` files in *log_dir*.

    Only those two patterns are touched — never ``agent.log`` / ``agent.error.log`` (launchd
    holds them open) and nothing outside *log_dir*. Unparseable names are ignored and
    unlink failures are swallowed. Returns the paths that were deleted.
    """
    log_dir = Path(log_dir)
    cutoff_date = (today or _utc_today()) - timedelta(days=retention_days)
    if today is None:
        cutoff_ts = time.time() - retention_days * 86400
    else:
        midnight = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        cutoff_ts = midnight.timestamp() - retention_days * 86400

    deleted: list[Path] = []
    try:
        candidates = list(log_dir.iterdir())
    except OSError:
        return deleted
    for path in candidates:
        try:
            match = _DAILY_LOG_RE.match(path.name)
            if match:
                expired = date.fromisoformat(match.group(1)) < cutoff_date
            elif path.suffix == ".bak" and path.is_file():
                expired = path.stat().st_mtime < cutoff_ts
            else:
                continue
            if expired:
                path.unlink()
                deleted.append(path)
        except (OSError, ValueError):
            continue
    return deleted


class _DailyFileHandler(logging.FileHandler):
    """Appends to ``<log_dir>/digest-YYYY-MM-DD.log`` (UTC date), rolling when the date changes.

    The scheduler process is long-running, so the date is checked on every emit. Rolling also
    prunes expired logs. Write failures are swallowed — logging must never take down a run.
    """

    def __init__(self, log_dir: Path | str, today_fn: Callable[[], date] = _utc_today) -> None:
        self._log_dir = Path(log_dir)
        self._today_fn = today_fn
        self._date = today_fn()
        super().__init__(self._path_for(self._date), mode="a", encoding="utf-8", delay=True)

    def _path_for(self, day: date) -> str:
        return str(self._log_dir / f"digest-{day.isoformat()}.log")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            today = self._today_fn()
            if today != self._date:
                self.acquire()
                try:
                    if self.stream is not None:
                        self.stream.close()
                        self.stream = None
                    self._date = today
                    self.baseFilename = os.path.abspath(self._path_for(today))
                finally:
                    self.release()
                prune_old_logs(self._log_dir, today=today)
            super().emit(record)
        except Exception:
            pass

    def handleError(self, record: logging.LogRecord) -> None:
        pass


def _attach_file_handler(log_dir: Path | str | None = None) -> _DailyFileHandler | None:
    """Add the daily file handler to the root logger. Returns None (stdout only) on any failure."""
    try:
        directory = Path(log_dir) if log_dir is not None else _default_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        prune_old_logs(directory)
        handler = _DailyFileHandler(directory)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)
        return handler
    except Exception:
        return None


def _configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


_configure_structlog()
_attach_file_handler()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for the given module name."""
    return structlog.get_logger(name)
