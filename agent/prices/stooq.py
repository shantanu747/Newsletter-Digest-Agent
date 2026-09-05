"""Stooq daily-close fetcher — free, unauthenticated CSV over stdlib urllib.

Fetches from ``https://stooq.com/q/d/l/?s={symbol}&i=d`` and parses the
``Date,Open,High,Low,Close,Volume`` CSV with the stdlib ``csv`` module. No new
third-party dependency.

Fail-soft by contract: any exception, HTTP error, ``No data`` body, or
unparseable row yields an empty result (or skips the row) with a warning log.
Never raises.
"""

from __future__ import annotations

import csv
import io
import urllib.request
from collections.abc import Callable
from datetime import date

from agent.utils.logger import get_logger

log = get_logger(__name__)

_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
_TIMEOUT_SECONDS = 10


def stooq_symbol(ticker: str) -> str:
    """Map a profile ticker to its Stooq symbol.

    'NVDA' -> 'nvda.us'; 'BRK-B' -> 'brk-b.us'; 'nvda.us' -> 'nvda.us'
    (a ticker already containing a '.' is used as-is, lower-cased).
    """
    lowered = ticker.lower()
    if "." in lowered:
        return lowered
    return f"{lowered}.us"


def _default_opener(url: str, timeout: int) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


class StooqPriceFetcher:
    """Fetches daily closes from Stooq's CSV endpoint. Fail-soft: returns [] on any problem."""

    def __init__(self, opener: Callable[[str, int], bytes] | None = None) -> None:
        """Args:
            opener: Injectable ``(url, timeout) -> bytes`` for tests.
                Defaults to a urllib.request.urlopen wrapper.
        """
        self._opener = opener or _default_opener

    def daily_closes(self, ticker: str, start: date, end: date) -> list[tuple[str, float]]:
        """Daily ``[(YYYY-MM-DD, close), ...]`` for *ticker* in [start, end], ascending.

        Returns [] on any failure — HTTP error, timeout, `No data` body,
        malformed CSV. Never raises.
        """
        symbol = stooq_symbol(ticker)
        try:
            raw = self._opener(_URL.format(symbol=symbol), _TIMEOUT_SECONDS)
        except Exception as exc:
            log.warning("price_fetch_failed", ticker=ticker, error=type(exc).__name__)
            return []
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("price_fetch_failed", ticker=ticker, error=type(exc).__name__)
            return []
        if "No data" in text:
            return []
        lines = text.splitlines()
        if len(lines) < 2:
            return []
        start_s, end_s = start.isoformat(), end.isoformat()
        closes: list[tuple[str, float]] = []
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                day = (row.get("Date") or "").strip()
                if not day or day < start_s or day > end_s:
                    continue
                try:
                    close = float((row.get("Close") or "").strip())
                except (ValueError, TypeError, AttributeError):
                    continue
                closes.append((day, close))
        except Exception as exc:
            log.warning("price_fetch_failed", ticker=ticker, error=type(exc).__name__)
            return []
        closes.sort()
        return closes
