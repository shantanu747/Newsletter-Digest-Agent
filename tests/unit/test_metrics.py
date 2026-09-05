"""Unit tests for agent.trends.metrics.compute_brief (T033-T035). Zero API calls.

Tests cover:
- FR-014 gate: 5 mentions from 1 sender excluded, 5 mentions from 4 senders included (SC-004)
- is_new / is_fading flags
- z_score is None below 8 daily buckets (FR-016)
- Truncation to max_entities_in_prompt holds the brief's size stable regardless of
  underlying store volume — 300 observations vs 30,000 (SC-005)
- is_cold_start true when history spans fewer than two windows
"""

import sqlite3
from datetime import datetime, timezone

from agent.knowledge.store import ObservationStore
from agent.trends.metrics import compute_brief
from agent.utils.config import SignalsConfig
from agent.utils.models import EntityMention, Idea, Summary

_NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _make_config(**overrides) -> SignalsConfig:
    return SignalsConfig(**overrides)


def _make_summary(email_id: str, sender: str, entity_name: str, generated_at: datetime) -> Summary:
    idea = Idea(
        title="idea",
        summary_text=f"{entity_name} claim text",
        entities=(EntityMention(name=entity_name, entity_type="company", sentiment="neutral"),),
    )
    return Summary(
        email_id=email_id,
        sender=sender,
        subject="subject",
        summary_text="",
        word_count=0,
        generated_at=generated_at,
        ideas=(idea,),
    )


def _record_mentions(store, entity_name, senders, generated_at, prefix):
    for i, sender in enumerate(senders):
        store.record_summary(_make_summary(f"{prefix}-{i}", sender, entity_name, generated_at))


def _seed_bulk(db_path, num_entities, mentions_per_entity, senders_per_entity, day):
    """Bulk-insert synthetic entity/observation/entity_daily rows via direct SQL.

    Bypasses record_summary's Python-level loop for the SC-005 volume test, where the
    goal is store size, not extraction correctness (already covered elsewhere).
    """
    conn = sqlite3.connect(db_path)
    for i in range(num_entities):
        cur = conn.execute(
            "INSERT INTO entity (canonical_name, norm_key, entity_type, first_seen, last_seen) "
            "VALUES (?, ?, 'company', ?, ?)",
            (f"Entity {i}", f"entity {i}", day, day),
        )
        entity_id = cur.lastrowid
        rows = [
            (entity_id, f"bulk-{i}-{m}", m, f"sender{m % senders_per_entity}@example.com", day, "neutral", "claim")
            for m in range(mentions_per_entity)
        ]
        conn.executemany(
            "INSERT INTO observation (entity_id, email_id, idea_index, sender, observed_date, sentiment, claim_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute(
            "INSERT INTO entity_daily (entity_id, day, mentions, distinct_senders, net_sentiment) "
            "VALUES (?, ?, ?, ?, 0.0)",
            (entity_id, day, mentions_per_entity, senders_per_entity),
        )
    conn.commit()
    conn.close()


class TestSourceBreadthGate:
    def test_single_sender_excluded_multi_sender_included(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        current_date = datetime(2026, 9, 1, tzinfo=timezone.utc)

        _record_mentions(
            store, "OnlyOne Corp", ["same@example.com"] * 5, current_date, "single"
        )
        _record_mentions(
            store,
            "Broad Co",
            [f"sender{i}@example.com" for i in range(4)] + ["sender0@example.com"],
            current_date,
            "multi",
        )

        brief = compute_brief(store, _make_config(), _NOW)
        names = {t.name for t in brief.trends}

        assert "OnlyOne Corp" not in names
        assert "Broad Co" in names


class TestNewAndFadingFlags:
    def test_is_new_true_for_entity_absent_from_prior_window(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        current_date = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _record_mentions(
            store, "Fresh Inc", [f"s{i}@example.com" for i in range(3)], current_date, "fresh"
        )

        brief = compute_brief(store, _make_config(), _NOW)
        fresh = next(t for t in brief.trends if t.name == "Fresh Inc")

        assert fresh.is_new is True
        assert fresh.is_fading is False

    def test_is_fading_true_for_entity_only_in_prior_window(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        prior_date = datetime(2026, 8, 20, tzinfo=timezone.utc)  # falls in the prior window
        _record_mentions(
            store, "Fading Corp", [f"s{i}@example.com" for i in range(3)], prior_date, "fading"
        )

        brief = compute_brief(store, _make_config(), _NOW)
        fading = next(t for t in brief.trends if t.name == "Fading Corp")

        assert fading.is_fading is True
        assert fading.is_new is False
        assert fading.current_count == 0


class TestZScoreGuard:
    def test_z_score_is_none_below_eight_daily_buckets(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        current_date = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _record_mentions(
            store, "Sparse Co", [f"s{i}@example.com" for i in range(3)], current_date, "sparse"
        )

        brief = compute_brief(store, _make_config(), _NOW)
        sparse = next(t for t in brief.trends if t.name == "Sparse Co")

        assert sparse.z_score is None


class TestTruncation:
    def test_brief_size_stable_across_store_volume(self, tmp_path):
        config = _make_config(max_entities_in_prompt=10, min_mentions=3, min_sources=2)
        day = "2026-09-01"

        small_db = str(tmp_path / "small.db")
        ObservationStore(small_db)
        _seed_bulk(small_db, num_entities=60, mentions_per_entity=5, senders_per_entity=4, day=day)
        small_brief = compute_brief(ObservationStore(small_db), config, _NOW)

        large_db = str(tmp_path / "large.db")
        ObservationStore(large_db)
        _seed_bulk(large_db, num_entities=60, mentions_per_entity=500, senders_per_entity=4, day=day)
        large_brief = compute_brief(ObservationStore(large_db), config, _NOW)

        assert len(small_brief.trends) == config.max_entities_in_prompt
        assert len(large_brief.trends) == config.max_entities_in_prompt


class TestColdStart:
    def test_is_cold_start_true_when_history_spans_fewer_than_two_windows(self, tmp_path):
        store = ObservationStore(str(tmp_path / "signals.db"))
        current_date = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _record_mentions(
            store, "New Entrant", [f"s{i}@example.com" for i in range(3)], current_date, "entrant"
        )

        brief = compute_brief(store, _make_config(), _NOW)

        assert brief.is_cold_start is True
