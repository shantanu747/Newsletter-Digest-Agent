"""Unit tests for agent.prices.stooq.StooqPriceFetcher. Zero real network calls."""

from __future__ import annotations

from datetime import date

import pytest

from agent.prices.stooq import _TIMEOUT_SECONDS, StooqPriceFetcher, stooq_symbol

_START = date(2026, 8, 20)
_END = date(2026, 9, 3)

_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-08-20,180.0,182.0,179.0,181.5,1000\n"
    "2026-08-27,182.0,184.0,181.0,183.25,1100\n"
    "2026-09-03,185.0,187.0,184.0,186.0,1200\n"
)


def _opener(body: bytes, seen: dict | None = None):
    def _open(url: str, timeout: int) -> bytes:
        if seen is not None:
            seen["url"] = url
            seen["timeout"] = timeout
        return body

    return _open


class TestSymbolMapping:
    @pytest.mark.parametrize(
        ("ticker", "expected"),
        [
            ("NVDA", "nvda.us"),
            ("BRK-B", "brk-b.us"),
            ("nvda.us", "nvda.us"),
            ("NVDA.US", "nvda.us"),
        ],
    )
    def test_symbol_mapping_cases(self, ticker, expected):
        assert stooq_symbol(ticker) == expected


class TestDailyCloses:
    def test_parses_csv_and_filters_to_range(self):
        seen: dict = {}
        fetcher = StooqPriceFetcher(opener=_opener(_CSV.encode(), seen))

        closes = fetcher.daily_closes("NVDA", date(2026, 8, 27), date(2026, 9, 3))

        assert closes == [("2026-08-27", 183.25), ("2026-09-03", 186.0)]
        assert seen["url"] == "https://stooq.com/q/d/l/?s=nvda.us&i=d"

    def test_no_data_body_returns_empty(self):
        fetcher = StooqPriceFetcher(opener=_opener(b"No data"))

        assert fetcher.daily_closes("NVDA", _START, _END) == []

    def test_short_body_returns_empty(self):
        fetcher = StooqPriceFetcher(opener=_opener(b"Date,Open,High,Low,Close,Volume\n"))

        assert fetcher.daily_closes("NVDA", _START, _END) == []

    def test_http_error_returns_empty(self):
        def _raise(url: str, timeout: int) -> bytes:
            raise OSError("connection refused")

        fetcher = StooqPriceFetcher(opener=_raise)

        assert fetcher.daily_closes("NVDA", _START, _END) == []

    def test_timeout_returns_empty(self):
        def _raise(url: str, timeout: int) -> bytes:
            raise TimeoutError("timed out")

        fetcher = StooqPriceFetcher(opener=_raise)

        assert fetcher.daily_closes("NVDA", _START, _END) == []

    def test_malformed_row_skipped(self):
        body = (
            "Date,Open,High,Low,Close,Volume\n"
            "2026-08-27,182.0,184.0,181.0,N/A,1100\n"
            "2026-09-03,185.0,187.0,184.0,186.0,1200\n"
        )
        fetcher = StooqPriceFetcher(opener=_opener(body.encode()))

        assert fetcher.daily_closes("NVDA", _START, _END) == [("2026-09-03", 186.0)]

    def test_uses_10_second_timeout(self):
        seen: dict = {}
        fetcher = StooqPriceFetcher(opener=_opener(_CSV.encode(), seen))

        fetcher.daily_closes("NVDA", _START, _END)

        assert seen["timeout"] == _TIMEOUT_SECONDS == 10
