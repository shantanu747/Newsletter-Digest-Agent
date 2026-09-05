"""Unit tests for agent.trends.track_record. Real store in tmp_path, fake fetcher."""

from __future__ import annotations

from datetime import date, datetime, timezone

from agent.knowledge.store import ObservationStore
from agent.trends.track_record import build_track_record, price_change, resolve_ticker
from agent.utils.config import UserProfile
from agent.utils.models import EntityMention, Idea, SignalItem, SignalsReport, Summary

_NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)


def _profile() -> UserProfile:
    return UserProfile(
        portfolio=[{"ticker": "NVDA", "name": "Nvidia"}],
        watchlist=[{"ticker": "TSLA", "name": "Tesla"}],
    )


def _make_report(**overrides) -> SignalsReport:
    def _item(headline: str, entities: tuple) -> SignalItem:
        return SignalItem(headline=headline, body="Body.", confidence="HIGH", entities=entities)

    defaults = dict(
        generated_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        window_days=7,
        macro=None,
        risks=(_item("Nvidia risk", ("Nvidia",)),),
        opportunities=(),
        emerging=(),
        fading=(),
        watch=(_item("Tesla watch", ("Tesla",)),),
    )
    defaults.update(overrides)
    return SignalsReport(**defaults)


def _seed_mention(store: ObservationStore, name: str, sender: str, when: datetime, sentiment: str = "positive") -> None:
    store.record_summary(
        Summary(
            email_id=f"{name}-{sender}-{when.isoformat()}",
            sender=sender,
            subject="Subject",
            summary_text=f"Claim about {name}.",
            word_count=5,
            generated_at=when,
            ideas=(
                Idea(
                    title=f"{name} idea",
                    summary_text=f"Claim about {name}.",
                    entities=(EntityMention(name=name, entity_type="company", sentiment=sentiment),),
                ),
            ),
        )
    )


class FakeFetcher:
    def __init__(self, closes: dict | None = None, fail: bool = False) -> None:
        self.closes = closes or {}
        self.fail = fail
        self.calls: list[str] = []

    def daily_closes(self, ticker: str, start: date, end: date):
        self.calls.append(ticker)
        if self.fail:
            raise TimeoutError("boom")
        return [(day, close) for day, close in self.closes.get(ticker, []) if start.isoformat() <= day <= end.isoformat()]


def _record(store: ObservationStore, report_date: date) -> None:
    store.record_signal_calls(
        _make_report(), report_date, ticker_for=lambda names: resolve_ticker(names, _profile())
    )


class TestResolveTicker:
    def test_matches_by_name(self):
        assert resolve_ticker(("Nvidia",), _profile()) == "NVDA"

    def test_matches_by_ticker(self):
        assert resolve_ticker(("NVDA",), _profile()) == "NVDA"

    def test_case_and_punctuation_insensitive(self):
        assert resolve_ticker(("nvidia corp.",), _profile()) == "NVDA"

    def test_portfolio_wins_over_watchlist(self):
        profile = UserProfile(
            portfolio=[{"ticker": "AAA", "name": "Shared Co"}],
            watchlist=[{"ticker": "BBB", "name": "Shared Co"}],
        )
        assert resolve_ticker(("Shared Co",), profile) == "AAA"

    def test_none_when_unmatched_or_profile_none(self):
        assert resolve_ticker(("Unknown Corp",), _profile()) is None
        assert resolve_ticker(("Nvidia",), None) is None
        assert resolve_ticker((), _profile()) is None


class TestPriceChange:
    def test_exact_days(self):
        closes = [("2026-08-27", 100.0), ("2026-09-03", 112.345)]
        assert price_change(closes, date(2026, 8, 27), 7) == 12.3

    def test_weekend_boundary_uses_nearest_trading_day_within_slack(self):
        # made_on is a Sunday; Friday close is within 5-day slack, and the
        # first trading day on/after the Sunday target is within slack.
        closes = [("2026-08-28", 100.0), ("2026-09-07", 110.0)]
        assert price_change(closes, date(2026, 8, 30), 7) == 10.0

    def test_missing_side_returns_none(self):
        assert price_change([("2026-09-03", 110.0)], date(2026, 8, 27), 7) is None
        assert price_change([("2026-08-27", 100.0)], date(2026, 8, 27), 7) is None
        assert price_change([], date(2026, 8, 27), 7) is None


class TestBuildTrackRecord:
    def test_one_review_per_due_call_horizon(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        _record(store, date(2026, 8, 27))
        fetcher = FakeFetcher({"NVDA": [("2026-08-27", 100.0), ("2026-09-03", 110.0)]})

        reviews = build_track_record(store, _profile(), fetcher, _NOW)

        assert len(reviews) == 2
        by_headline = {r.headline: r for r in reviews}
        assert by_headline["Nvidia risk"].price_change_pct == 10.0
        assert by_headline["Tesla watch"].ticker == "TSLA"
        assert by_headline["Tesla watch"].price_change_pct is None

    def test_ticker_fetched_once_for_two_calls_sharing_it(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        store.record_signal_calls(
            _make_report(
                risks=(
                    SignalItem(headline="Risk A", body="B.", confidence="HIGH", entities=("Nvidia",)),
                    SignalItem(headline="Risk B", body="B.", confidence="HIGH", entities=("NVDA",)),
                ),
                watch=(),
            ),
            date(2026, 8, 27),
            ticker_for=lambda names: resolve_ticker(names, _profile()),
        )
        fetcher = FakeFetcher({"NVDA": [("2026-08-27", 100.0), ("2026-09-03", 110.0)]})

        build_track_record(store, _profile(), fetcher, _NOW)

        assert fetcher.calls == ["NVDA"]

    def test_none_ticker_skips_fetch_and_still_yields_mention_stats(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        store.record_signal_calls(
            _make_report(
                risks=(SignalItem(headline="R", body="B.", confidence="HIGH", entities=("Unknown Corp",)),),
                watch=(),
            ),
            date(2026, 8, 27),
            ticker_for=lambda names: None,
        )
        _seed_mention(
            store, "Unknown Corp", "a@example.com", datetime(2026, 8, 28, tzinfo=timezone.utc)
        )
        fetcher = FakeFetcher()

        (review,) = build_track_record(store, _profile(), fetcher, _NOW)

        assert fetcher.calls == []
        assert review.ticker is None
        assert review.price_change_pct is None
        assert review.mentions_since == 1
        assert review.sources_since == 1

    def test_fetcher_raising_yields_price_none_others_unaffected(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        _record(store, date(2026, 8, 27))

        reviews = build_track_record(store, _profile(), FakeFetcher(fail=True), _NOW)

        assert len(reviews) == 2
        assert all(r.price_change_pct is None for r in reviews)

    def test_mention_stats_reflect_observations_after_made_on_only(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        _seed_mention(store, "Nvidia", "old@example.com", datetime(2026, 8, 20, tzinfo=timezone.utc))
        _record(store, date(2026, 8, 27))
        _seed_mention(store, "Nvidia", "a@example.com", datetime(2026, 8, 28, tzinfo=timezone.utc))
        _seed_mention(
            store, "Nvidia", "b@example.com", datetime(2026, 8, 29, tzinfo=timezone.utc), sentiment="negative"
        )

        reviews = build_track_record(store, _profile(), FakeFetcher(), _NOW)

        nvidia = next(r for r in reviews if r.headline == "Nvidia risk")
        assert nvidia.mentions_since == 2
        assert nvidia.sources_since == 2
        assert nvidia.sentiment_since == 0.0
