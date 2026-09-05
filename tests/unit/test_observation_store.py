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
