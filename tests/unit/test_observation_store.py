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
from datetime import datetime, timedelta, timezone

import pytest

from agent.knowledge.store import ObservationStore
from agent.utils.models import EntityMention, Idea, Summary


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
        ):
            assert expected in tables

    def test_seeds_schema_version(self, tmp_path):
        db_path = str(tmp_path / "signals.db")
        ObservationStore(db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
        conn.close()
        assert row == ("1",)


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
