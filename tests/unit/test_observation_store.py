"""Unit tests for agent.knowledge.store.ObservationStore (T022-T027).

Tests cover:
- Schema creation on a tmp_path database (all seven tables + schema_meta seed)
- record_summary inserting the expected observation row count
- Idempotency: calling record_summary twice with the same Summary leaves counts unchanged (SC-002)
- Cooccurrence pairs always stored with entity_a_id < entity_b_id
- A corrupted database file makes every method a silent no-op and job_due return False (SC-007)
- A read-only directory does not raise
"""

import os
import sqlite3
import stat
from datetime import date, datetime, timedelta, timezone

import pytest

from agent.knowledge.store import ObservationStore
from agent.utils.models import CallReview, EntityMention, Idea, SignalItem, SignalsReport, Summary


def _make_summary(
    email_id: str = "email-1",
    sender: str = "newsletter@example.com",
    ideas: tuple[Idea, ...] | None = None,
    generated_at: datetime | None = None,
) -> Summary:
    if ideas is None:
        ideas = (
            Idea(
                title="Nvidia beats estimates",
                summary_text="Nvidia posted strong earnings driven by data center demand.",
                entities=(
                    EntityMention(name="Nvidia", entity_type="company", sentiment="positive"),
                    EntityMention(name="data center demand", entity_type="concept", sentiment="positive"),
                ),
            ),
        )
    return Summary(
        email_id=email_id,
        sender=sender,
        subject="Test Digest",
        summary_text="body",
        word_count=10,
        generated_at=generated_at or datetime(2026, 9, 1, 7, 0, 0, tzinfo=timezone.utc),
        ideas=ideas,
    )


class TestSchemaCreation:
    def test_creates_all_seven_tables_and_schema_version(self, tmp_path):
        db_path = str(tmp_path / "signals.db")
        ObservationStore(db_path)

        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()

        for expected in (
            "entity", "entity_alias", "observation", "cooccurrence",
            "entity_daily", "job_run", "schema_meta",
            "signal_call", "signal_review", "price_daily",
        ):
            assert expected in tables

    def test_seeds_schema_version(self, tmp_path):
        db_path = str(tmp_path / "signals.db")
        ObservationStore(db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        conn.close()
        assert row == ("2",)

    def test_v1_database_upgrades_to_v2_in_place(self, tmp_path):
        db_path = str(tmp_path / "signals.db")
        store = ObservationStore(db_path)
        store.record_summary(_make_summary())

        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")
        conn.execute("DROP TABLE signal_call")
        conn.execute("DROP TABLE signal_review")
        conn.execute("DROP TABLE price_daily")
        conn.commit()
        conn.close()

        reopened = ObservationStore(db_path)

        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        obs_count = conn.execute("SELECT COUNT(*) FROM observation").fetchone()[0]
        conn.close()

        assert {"signal_call", "signal_review", "price_daily"} <= tables
        assert row == ("2",)
        assert obs_count == 2
        assert reopened.record_summary(_make_summary()) == 0


class TestRecordSummary:
    def test_inserts_expected_observation_count(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        inserted = store.record_summary(_make_summary())
        assert inserted == 2

    def test_calling_twice_leaves_count_unchanged(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        summary = _make_summary()
        store.record_summary(summary)
        second_inserted = store.record_summary(summary)

        conn = sqlite3.connect(store._db_path)
        total = conn.execute("SELECT COUNT(*) FROM observation").fetchone()[0]
        conn.close()

        assert second_inserted == 0
        assert total == 2

    def test_cooccurrence_pairs_stored_with_a_less_than_b(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        store.record_summary(_make_summary())

        conn = sqlite3.connect(store._db_path)
        rows = conn.execute("SELECT entity_a_id, entity_b_id FROM cooccurrence").fetchall()
        conn.close()

        assert len(rows) == 1
        entity_a_id, entity_b_id = rows[0]
        assert entity_a_id < entity_b_id


class TestComputeWindow:
    def test_returns_current_window_counts(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        store.record_summary(_make_summary())

        start = datetime(2026, 8, 25, tzinfo=timezone.utc)
        end = datetime(2026, 9, 8, tzinfo=timezone.utc)
        trends = store.compute_window(start, end)

        assert len(trends) == 2
        nvidia = next(t for t in trends if t.name == "Nvidia")
        assert nvidia.current_count == 1
        assert nvidia.source_breadth == 1


class TestJobCadence:
    def test_job_due_true_when_never_run(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        assert store.job_due("signals_report", 3, datetime.now(timezone.utc)) is True

    def test_job_due_false_immediately_after_mark(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        now = datetime.now(timezone.utc)
        store.mark_job_run("signals_report", "success", now)
        assert store.job_due("signals_report", 3, now + timedelta(hours=1)) is False


class TestRecentContext:
    def _seed_observations(self, store: ObservationStore) -> None:
        base = datetime(2026, 9, 1, 7, 0, 0, tzinfo=timezone.utc)
        # Nvidia: 5 mentions, 3 senders, 4 days, sentiment (+3 -1) / 5 = +0.4
        nvidia_ideas = (
            ("email-n1", "a@example.com", base, "positive", "Nvidia beats estimates"),
            ("email-n2", "b@example.com", base, "positive", "Nvidia data center boom"),
            ("email-n3", "b@example.com", base + timedelta(days=1), "positive", "Nvidia chips ship"),
            ("email-n4", "c@example.com", base + timedelta(days=2), "negative", "Nvidia faces curbs"),
            ("email-n5", "a@example.com", base + timedelta(days=3), "neutral", "Nvidia outlook steady"),
        )
        for email_id, sender, generated_at, sentiment, claim in nvidia_ideas:
            store.record_summary(
                _make_summary(
                    email_id=email_id,
                    sender=sender,
                    generated_at=generated_at,
                    ideas=(
                        Idea(
                            title="Nvidia idea",
                            summary_text=claim,
                            entities=(EntityMention(name="Nvidia", entity_type="company", sentiment=sentiment),),
                        ),
                    ),
                )
            )

    def test_counts_mentions_senders_days_and_sentiment_in_window(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._seed_observations(store)

        result = store.recent_context(
            ["nvidia"],
            datetime(2026, 8, 25, tzinfo=timezone.utc),
            datetime(2026, 9, 8, tzinfo=timezone.utc),
        )

        assert set(result) == {"nvidia"}
        ctx = result["nvidia"]
        assert ctx.name == "Nvidia"
        assert ctx.mentions == 5
        assert ctx.distinct_senders == 3
        assert ctx.days_active == 4
        assert ctx.net_sentiment == pytest.approx(0.4)

    def test_observations_outside_window_are_excluded(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._seed_observations(store)

        # Everything before since is excluded
        assert store.recent_context(
            ["nvidia"],
            datetime(2026, 9, 10, tzinfo=timezone.utc),
            datetime(2026, 9, 20, tzinfo=timezone.utc),
        ) == {}

        # `until` is exclusive: observations on/after until do not count
        result = store.recent_context(
            ["nvidia"],
            datetime(2026, 8, 25, tzinfo=timezone.utc),
            datetime(2026, 9, 2, tzinfo=timezone.utc),
        )
        assert result["nvidia"].mentions == 2
        assert result["nvidia"].days_active == 1

    def test_unknown_key_absent_from_result(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._seed_observations(store)

        result = store.recent_context(
            ["nvidia", "never-mentioned"],
            datetime(2026, 8, 25, tzinfo=timezone.utc),
            datetime(2026, 9, 8, tzinfo=timezone.utc),
        )
        assert set(result) == {"nvidia"}

    def test_empty_input_returns_empty_dict(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        assert (
            store.recent_context(
                [],
                datetime(2026, 8, 25, tzinfo=timezone.utc),
                datetime(2026, 9, 8, tzinfo=timezone.utc),
            )
            == {}
        )

    def test_alias_key_resolves_to_canonical_entity(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._seed_observations(store)

        conn = sqlite3.connect(str(tmp_path / "signals.db"))
        entity_id = conn.execute("SELECT id FROM entity WHERE norm_key = 'nvidia'").fetchone()[0]
        conn.execute(
            "INSERT INTO entity_alias (alias_key, entity_id, source) VALUES (?, ?, ?)",
            ("nvda", entity_id, "test"),
        )
        conn.commit()
        conn.close()

        result = store.recent_context(
            ["nvda"],
            datetime(2026, 8, 25, tzinfo=timezone.utc),
            datetime(2026, 9, 8, tzinfo=timezone.utc),
        )
        assert set(result) == {"nvda"}
        assert result["nvda"].name == "Nvidia"
        assert result["nvda"].mentions == 5

    def test_more_than_400_keys_are_chunked(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._seed_observations(store)
        store.record_summary(
            _make_summary(
                email_id="email-oil",
                sender="d@example.com",
                ideas=(
                    Idea(
                        title="Oil idea",
                        summary_text="Oil prices rise.",
                        entities=(EntityMention(name="Oil", entity_type="asset", sentiment="neutral"),),
                    ),
                ),
            )
        )

        keys = ["nvidia", "oil"] + [f"missing-{i}" for i in range(448)]
        result = store.recent_context(
            keys,
            datetime(2026, 8, 25, tzinfo=timezone.utc),
            datetime(2026, 9, 8, tzinfo=timezone.utc),
        )
        assert set(result) == {"nvidia", "oil"}

    def test_disabled_store_returns_empty_dict(self, tmp_path):
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"not a sqlite database")
        store = ObservationStore(str(db_path))

        result = store.recent_context(
            ["nvidia"],
            datetime(2026, 8, 25, tzinfo=timezone.utc),
            datetime(2026, 9, 8, tzinfo=timezone.utc),
        )
        assert result == {}


def _make_signal_item(headline: str = "Call headline", entities: tuple = ("Nvidia",)) -> SignalItem:
    return SignalItem(
        headline=headline,
        body="Mechanism and consequence.",
        confidence="HIGH",
        entities=entities,
    )


def _make_signals_report(**overrides) -> SignalsReport:
    defaults = dict(
        generated_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        window_days=7,
        macro=None,
        risks=(_make_signal_item("Risk one"),),
        opportunities=(_make_signal_item("Opportunity one", ("Tesla",)),),
        emerging=(_make_signal_item("Emerging one", ("OpenAI",)),),
        fading=(),
        watch=(_make_signal_item("Watch one", ("Apple",)), _make_signal_item("Watch two", ("Meta",))),
        divergences=(_make_signal_item("Divergence one", ("Nvidia",)),),
    )
    defaults.update(overrides)
    return SignalsReport(**defaults)


def _make_review(call_id: int = 1, horizon_days: int = 7, **overrides) -> CallReview:
    defaults = dict(
        call_id=call_id,
        made_on=date(2026, 8, 20),
        horizon_days=horizon_days,
        section="risks",
        headline="Risk one",
        confidence="HIGH",
        entities=("Nvidia",),
        ticker="NVDA",
        price_change_pct=12.4,
        mentions_since=9,
        sources_since=4,
        sentiment_since=0.5,
    )
    defaults.update(overrides)
    return CallReview(**defaults)


class TestSignalCalls:
    def test_records_five_items_across_sections(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        count = store.record_signal_calls(
            _make_signals_report(), date(2026, 9, 3), ticker_for=lambda names: None
        )

        assert count == 5
        conn = sqlite3.connect(str(tmp_path / "signals.db"))
        total = conn.execute("SELECT COUNT(*) FROM signal_call").fetchone()[0]
        sections = {row[0] for row in conn.execute("SELECT DISTINCT section FROM signal_call").fetchall()}
        conn.close()
        assert total == 5
        assert sections == {"risks", "opportunities", "emerging", "watch"}

    def test_rerecording_same_date_replaces_never_duplicates(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        report_date = date(2026, 9, 3)
        store.record_signal_calls(_make_signals_report(), report_date, ticker_for=lambda names: None)
        count = store.record_signal_calls(
            _make_signals_report(risks=(_make_signal_item("Risk one"),)),
            report_date,
            ticker_for=lambda names: None,
        )

        conn = sqlite3.connect(str(tmp_path / "signals.db"))
        total = conn.execute("SELECT COUNT(*) FROM signal_call").fetchone()[0]
        conn.close()
        assert count == 5
        assert total == 5

    def test_divergences_are_not_recorded(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        store.record_signal_calls(
            _make_signals_report(divergences=(_make_signal_item("Only divergence"),)),
            date(2026, 9, 3),
            ticker_for=lambda names: None,
        )

        conn = sqlite3.connect(str(tmp_path / "signals.db"))
        headlines = [row[0] for row in conn.execute("SELECT headline FROM signal_call").fetchall()]
        conn.close()
        assert "Only divergence" not in headlines
        assert "Divergence one" not in headlines

    def test_ticker_for_result_stored_and_entity_names_round_trip(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        store.record_signal_calls(
            _make_signals_report(),
            date(2026, 9, 3),
            ticker_for=lambda names: "NVDA" if "Nvidia" in names else None,
        )

        due = store.calls_due_for_review(
            datetime(2026, 9, 10, tzinfo=timezone.utc), [7], max_age_days=90
        )
        risk_call = next(call for call, _ in due if call.headline == "Risk one")
        assert risk_call.entity_names == ("Nvidia",)
        assert risk_call.ticker == "NVDA"
        watch_call = next(call for call, _ in due if call.headline == "Watch one")
        assert watch_call.ticker is None


class TestCallsDueForReview:
    def _record(self, store: ObservationStore, report_date: date) -> None:
        store.record_signal_calls(
            _make_signals_report(), report_date, ticker_for=lambda names: None
        )

    def test_due_at_exactly_h_days(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._record(store, date(2026, 8, 27))

        due = store.calls_due_for_review(
            datetime(2026, 9, 3, tzinfo=timezone.utc), [7], max_age_days=90
        )
        assert len(due) == 5
        assert all(horizon == 7 for _, horizon in due)

    def test_not_due_at_h_minus_one(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._record(store, date(2026, 8, 28))

        due = store.calls_due_for_review(
            datetime(2026, 9, 3, tzinfo=timezone.utc), [7], max_age_days=90
        )
        assert due == []

    def test_not_due_when_review_exists(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._record(store, date(2026, 8, 27))
        due = store.calls_due_for_review(
            datetime(2026, 9, 3, tzinfo=timezone.utc), [7], max_age_days=90
        )
        call_id = due[0][0].id
        store.record_reviews(
            [_make_review(call_id=call_id, made_on=date(2026, 8, 27))],
            datetime(2026, 9, 3, tzinfo=timezone.utc),
        )

        remaining = store.calls_due_for_review(
            datetime(2026, 9, 3, tzinfo=timezone.utc), [7], max_age_days=90
        )
        assert len(remaining) == 4
        assert all(call.id != call_id for call, _ in remaining)

    def test_seven_day_review_does_not_block_thirty_day_review(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._record(store, date(2026, 8, 4))
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        due = store.calls_due_for_review(now, [7, 30], max_age_days=90)
        call_id = due[0][0].id
        store.record_reviews([_make_review(call_id=call_id, made_on=date(2026, 8, 4))], now)

        remaining = store.calls_due_for_review(now, [7, 30], max_age_days=90)
        own = [(call, horizon) for call, horizon in remaining if call.id == call_id]
        assert own == [(own[0][0], 30)]

    def test_calls_older_than_max_age_excluded(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._record(store, date(2026, 5, 1))

        due = store.calls_due_for_review(
            datetime(2026, 9, 3, tzinfo=timezone.utc), [7, 30], max_age_days=90
        )
        assert due == []

    def test_ordering_by_report_date_id_horizon(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        self._record(store, date(2026, 8, 4))
        self._record(store, date(2026, 8, 27))
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)

        due = store.calls_due_for_review(now, [7, 30], max_age_days=90)
        keys = [(call.report_date, call.id, horizon) for call, horizon in due]
        assert keys == sorted(keys)


class TestPrices:
    def test_upsert_idempotent_and_closes_between_inclusive_ascending(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        assert store.upsert_prices("NVDA", [("2026-08-27", 180.0), ("2026-08-28", 182.5)]) == 2
        assert store.upsert_prices("NVDA", [("2026-08-28", 183.0)]) == 1

        closes = store.closes_between("NVDA", date(2026, 8, 27), date(2026, 8, 28))
        assert closes == [("2026-08-27", 180.0), ("2026-08-28", 183.0)]


class TestSignalStoreDegradation:
    def test_disabled_store_returns_defaults_for_new_methods(self, tmp_path):
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"not a sqlite database")
        store = ObservationStore(str(db_path))
        now = datetime.now(timezone.utc)

        assert store.record_signal_calls(_make_signals_report(), date(2026, 9, 3), ticker_for=lambda names: None) == 0
        assert store.calls_due_for_review(now, [7, 30], max_age_days=90) == []
        assert store.record_reviews([_make_review()], now) == 0
        assert store.upsert_prices("NVDA", [("2026-09-01", 100.0)]) == 0
        assert store.closes_between("NVDA", date(2026, 9, 1), date(2026, 9, 3)) == []


class TestDegradation:
    def test_corrupted_database_file_disables_store(self, tmp_path):
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"not a sqlite database")

        store = ObservationStore(str(db_path))

        assert store.has_email("anything") is False
        assert store.record_summary(_make_summary()) == 0
        assert store.compute_window(datetime.now(timezone.utc), datetime.now(timezone.utc)) == []
        assert store.new_edges(datetime.now(timezone.utc), datetime.now(timezone.utc)) == []
        assert store.job_due("signals_report", 3, datetime.now(timezone.utc)) is False
        assert store.mark_job_run("signals_report", "success", datetime.now(timezone.utc)) is None

    def test_read_only_directory_does_not_raise(self, tmp_path):
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        os.chmod(ro_dir, stat.S_IREAD | stat.S_IEXEC)
        try:
            store = ObservationStore(str(ro_dir / "signals.db"))
            assert store.record_summary(_make_summary()) == 0
        finally:
            os.chmod(ro_dir, stat.S_IRWXU)
