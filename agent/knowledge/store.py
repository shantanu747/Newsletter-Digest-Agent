"""Persistent entity/observation store — SQLite via stdlib sqlite3.

Never raises. Any sqlite3.Error (a corrupt file, a locked database, a read-only
filesystem) disables the store for the remainder of the process: it is logged,
`self._enabled` flips to False, and every subsequent public method becomes a
no-op returning an empty result. This is the project's first persistent state,
but it is optional — the daily digest must never go down because of it.
"""

from __future__ import annotations

import functools
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime

from agent.knowledge.canonicalize import normalize_key
from agent.utils.logger import get_logger
from agent.utils.models import CooccurrenceEdge, EntityContext, EntityMention, EntityTrend, Summary

log = get_logger(__name__)

_SCHEMA_VERSION = "1"

_RECENT_CONTEXT_CHUNK_SIZE = 400

_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS entity (
        id INTEGER PRIMARY KEY,
        canonical_name TEXT NOT NULL,
        norm_key TEXT NOT NULL UNIQUE,
        entity_type TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS entity_alias (
        alias_key TEXT PRIMARY KEY,
        entity_id INTEGER NOT NULL REFERENCES entity(id),
        source TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS observation (
        id INTEGER PRIMARY KEY,
        entity_id INTEGER NOT NULL REFERENCES entity(id),
        email_id TEXT NOT NULL,
        idea_index INTEGER NOT NULL,
        sender TEXT NOT NULL,
        observed_date TEXT NOT NULL,
        sentiment TEXT NOT NULL,
        claim_text TEXT NOT NULL,
        UNIQUE (email_id, idea_index, entity_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_observation_observed_date ON observation(observed_date)",
    "CREATE INDEX IF NOT EXISTS idx_observation_entity_date ON observation(entity_id, observed_date)",
    """CREATE TABLE IF NOT EXISTS cooccurrence (
        entity_a_id INTEGER NOT NULL REFERENCES entity(id),
        entity_b_id INTEGER NOT NULL REFERENCES entity(id),
        email_id TEXT NOT NULL,
        idea_index INTEGER NOT NULL,
        observed_date TEXT NOT NULL,
        UNIQUE (email_id, idea_index, entity_a_id, entity_b_id)
    )""",
    """CREATE TABLE IF NOT EXISTS entity_daily (
        entity_id INTEGER NOT NULL REFERENCES entity(id),
        day TEXT NOT NULL,
        mentions INTEGER NOT NULL,
        distinct_senders INTEGER NOT NULL,
        net_sentiment REAL NOT NULL,
        PRIMARY KEY (entity_id, day)
    )""",
    """CREATE TABLE IF NOT EXISTS job_run (
        job_name TEXT PRIMARY KEY,
        last_run_at TEXT NOT NULL,
        last_status TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
)


def _guarded(default):
    """Method decorator: any sqlite3.Error disables the store instead of raising.

    *default* is either a plain fallback value or a zero-arg factory (e.g. `list`)
    used both when the call fails and when the store is already disabled.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            fallback = default() if callable(default) else default
            if not self._enabled:
                return fallback
            try:
                return func(self, *args, **kwargs)
            except sqlite3.Error:
                log.error("knowledge_store.disabled", db_path=self._db_path, exc_info=True)
                self._enabled = False
                return fallback

        return wrapper

    return decorator


class ObservationStore:
    """Entity/observation store at *db_path*. Never raises — see module docstring."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._enabled = True
        try:
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._ensure_schema()
        except OSError:
            log.error("knowledge_store.disabled", db_path=db_path, exc_info=True)
            self._enabled = False
        except sqlite3.Error:
            log.error("knowledge_store.disabled", db_path=db_path, exc_info=True)
            self._enabled = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                (_SCHEMA_VERSION,),
            )

    def _resolve_entity(self, conn: sqlite3.Connection, mention: EntityMention, observed_date: str) -> int:
        key = normalize_key(mention.name)
        row = conn.execute("SELECT entity_id FROM entity_alias WHERE alias_key = ?", (key,)).fetchone()
        if row is None:
            row = conn.execute("SELECT id FROM entity WHERE norm_key = ?", (key,)).fetchone()
        if row is not None:
            entity_id = row[0]
            conn.execute(
                "UPDATE entity SET last_seen = ? WHERE id = ? AND last_seen < ?",
                (observed_date, entity_id, observed_date),
            )
            return entity_id
        cur = conn.execute(
            "INSERT INTO entity (canonical_name, norm_key, entity_type, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (mention.name, key, mention.entity_type, observed_date, observed_date),
        )
        return cur.lastrowid

    def _record_cooccurrences(
        self, conn: sqlite3.Connection, entity_ids: list[int], email_id: str, idea_index: int, observed_date: str
    ) -> None:
        unique_ids = sorted(set(entity_ids))
        for i in range(len(unique_ids)):
            for j in range(i + 1, len(unique_ids)):
                conn.execute(
                    "INSERT OR IGNORE INTO cooccurrence "
                    "(entity_a_id, entity_b_id, email_id, idea_index, observed_date) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (unique_ids[i], unique_ids[j], email_id, idea_index, observed_date),
                )

    def _refresh_entity_daily(self, conn: sqlite3.Connection, entity_id: int, day: str) -> None:
        mentions, distinct_senders, sentiment_sum = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT sender), "
            "SUM(CASE WHEN sentiment='positive' THEN 1 WHEN sentiment='negative' THEN -1 ELSE 0 END) "
            "FROM observation WHERE entity_id = ? AND observed_date = ?",
            (entity_id, day),
        ).fetchone()
        net_sentiment = (sentiment_sum or 0) / mentions if mentions else 0.0
        conn.execute(
            "INSERT INTO entity_daily (entity_id, day, mentions, distinct_senders, net_sentiment) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(entity_id, day) DO UPDATE SET "
            "mentions=excluded.mentions, distinct_senders=excluded.distinct_senders, "
            "net_sentiment=excluded.net_sentiment",
            (entity_id, day, mentions, distinct_senders, net_sentiment),
        )

    @_guarded(default=False)
    def has_email(self, email_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM observation WHERE email_id = ? LIMIT 1", (email_id,)).fetchone()
        return row is not None

    @_guarded(default=lambda: 0)
    def record_summary(self, summary: Summary) -> int:
        if not summary.ideas:
            return 0
        observed_date = summary.generated_at.date().isoformat()
        inserted = 0
        with self._connect() as conn:
            for idea_index, idea in enumerate(summary.ideas):
                if not idea.entities:
                    continue
                entity_ids: list[int] = []
                for mention in idea.entities:
                    entity_id = self._resolve_entity(conn, mention, observed_date)
                    entity_ids.append(entity_id)
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO observation "
                        "(entity_id, email_id, idea_index, sender, observed_date, sentiment, claim_text) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            entity_id,
                            summary.email_id,
                            idea_index,
                            summary.sender,
                            observed_date,
                            mention.sentiment,
                            idea.summary_text,
                        ),
                    )
                    if cur.rowcount:
                        inserted += 1
                self._record_cooccurrences(conn, entity_ids, summary.email_id, idea_index, observed_date)
                for entity_id in set(entity_ids):
                    self._refresh_entity_daily(conn, entity_id, observed_date)
        return inserted

    @_guarded(default=list)
    def compute_window(self, start: datetime, end: datetime) -> list[EntityTrend]:
        """Raw per-entity counts for [start, end). Ranking/thresholding is metrics.py's job.

        Only current_count, source_breadth, net_sentiment, and sample_claims are
        meaningful here; delta/velocity/z_score/is_new/is_fading are placeholders
        that agent.trends.metrics fills in from entity_daily history.
        """
        start_s, end_s = start.date().isoformat(), end.date().isoformat()
        trends: list[EntityTrend] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT o.entity_id, e.canonical_name, e.entity_type, COUNT(*) AS mentions, "
                "COUNT(DISTINCT o.sender) AS breadth, "
                "SUM(CASE WHEN o.sentiment='positive' THEN 1 WHEN o.sentiment='negative' THEN -1 ELSE 0 END) "
                "AS sentiment_sum "
                "FROM observation o JOIN entity e ON e.id = o.entity_id "
                "WHERE o.observed_date >= ? AND o.observed_date < ? "
                "GROUP BY o.entity_id",
                (start_s, end_s),
            ).fetchall()
            for entity_id, name, entity_type, mentions, breadth, sentiment_sum in rows:
                claims = conn.execute(
                    "SELECT DISTINCT claim_text FROM observation "
                    "WHERE entity_id = ? AND observed_date >= ? AND observed_date < ? LIMIT 3",
                    (entity_id, start_s, end_s),
                ).fetchall()
                trends.append(
                    EntityTrend(
                        entity_id=entity_id,
                        name=name,
                        entity_type=entity_type,
                        current_count=mentions,
                        prior_count=0,
                        delta=0,
                        velocity=0.0,
                        source_breadth=breadth,
                        z_score=None,
                        net_sentiment=(sentiment_sum or 0) / mentions if mentions else 0.0,
                        is_new=False,
                        is_fading=False,
                        sample_claims=tuple(c[0] for c in claims),
                    )
                )
        return trends

    @_guarded(default={})
    def recent_context(
        self, norm_keys: Sequence[str], since: datetime, until: datetime
    ) -> dict[str, EntityContext]:
        """Window statistics for the given normalized entity keys.

        Resolves each key through ``entity.norm_key`` and ``entity_alias`` (same path as
        ``_resolve_entity``). Keys with no observations in [since, until) are absent from the result.
        Dates compare on ``observed_date`` (ISO ``YYYY-MM-DD``), so pass date-aligned boundaries.
        """
        keys = list(dict.fromkeys(norm_keys))
        if not keys:
            return {}
        since_s, until_s = since.date().isoformat(), until.date().isoformat()
        result: dict[str, EntityContext] = {}
        with self._connect() as conn:
            for i in range(0, len(keys), _RECENT_CONTEXT_CHUNK_SIZE):
                chunk = keys[i : i + _RECENT_CONTEXT_CHUNK_SIZE]
                # Resolve each requested key to an entity id first, so the result
                # is keyed by the key the caller asked for (alias keys included).
                placeholders = ", ".join("?" for _ in chunk)
                folded = [normalize_key(k) for k in chunk]
                entity_rows = conn.execute(
                    f"SELECT norm_key, id FROM entity WHERE norm_key IN ({placeholders})",
                    folded,
                ).fetchall()
                alias_rows = conn.execute(
                    f"SELECT alias_key, entity_id FROM entity_alias WHERE alias_key IN ({placeholders})",
                    folded,
                ).fetchall()
                norm_to_id = {norm_key: entity_id for norm_key, entity_id in entity_rows}
                alias_to_id = {alias_key: entity_id for alias_key, entity_id in alias_rows}
                entity_to_requested: dict[int, list[str]] = {}
                for requested, nk in zip(chunk, folded):
                    entity_id = norm_to_id.get(nk, alias_to_id.get(nk))
                    if entity_id is not None:
                        entity_to_requested.setdefault(entity_id, []).append(requested)
                if not entity_to_requested:
                    continue
                ids = sorted(entity_to_requested)
                id_placeholders = ", ".join("?" for _ in ids)
                rows = conn.execute(
                    "SELECT o.entity_id, e.canonical_name, "
                    "COUNT(*) AS mentions, "
                    "COUNT(DISTINCT o.sender) AS distinct_senders, "
                    "COUNT(DISTINCT o.observed_date) AS days_active, "
                    "SUM(CASE o.sentiment WHEN 'positive' THEN 1 WHEN 'negative' THEN -1 ELSE 0 END) AS net "
                    "FROM observation o "
                    "JOIN entity e ON e.id = o.entity_id "
                    f"WHERE o.entity_id IN ({id_placeholders}) "
                    "AND o.observed_date >= ? AND o.observed_date < ? "
                    "GROUP BY o.entity_id",
                    (*ids, since_s, until_s),
                ).fetchall()
                for entity_id, name, mentions, distinct_senders, days_active, net in rows:
                    ctx = EntityContext(
                        name=name,
                        mentions=mentions,
                        distinct_senders=distinct_senders,
                        days_active=days_active,
                        net_sentiment=(net or 0) / mentions if mentions else 0.0,
                    )
                    for requested in entity_to_requested[entity_id]:
                        result[requested] = ctx
        return result

    @_guarded(default=list)
    def new_edges(self, start: datetime, end: datetime) -> list[CooccurrenceEdge]:
        """Cooccurrence pairs first observed within [start, end) — no prior occurrence."""
        start_s, end_s = start.date().isoformat(), end.date().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ea.canonical_name, eb.canonical_name, COUNT(*) AS cnt "
                "FROM cooccurrence c "
                "JOIN entity ea ON ea.id = c.entity_a_id "
                "JOIN entity eb ON eb.id = c.entity_b_id "
                "WHERE c.observed_date >= ? AND c.observed_date < ? "
                "GROUP BY c.entity_a_id, c.entity_b_id "
                "HAVING NOT EXISTS ("
                "  SELECT 1 FROM cooccurrence prior "
                "  WHERE prior.entity_a_id = c.entity_a_id "
                "    AND prior.entity_b_id = c.entity_b_id "
                "    AND prior.observed_date < ?"
                ")",
                (start_s, end_s, start_s),
            ).fetchall()
        return [CooccurrenceEdge(entity_a=a, entity_b=b, count=count, is_new=True) for a, b, count in rows]

    @_guarded(default=False)
    def job_due(self, job_name: str, interval_days: int, now: datetime) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_run_at FROM job_run WHERE job_name = ?", (job_name,)
            ).fetchone()
        if row is None:
            return True
        last_run_at = datetime.fromisoformat(row[0])
        return (now - last_run_at).days >= interval_days

    @_guarded(default=list)
    def entity_daily_counts(self, entity_id: int, since: datetime) -> list[int]:
        """Per-day mention counts for *entity_id* from entity_daily, day >= since.

        The list length is the "daily bucket" count agent.trends.metrics gates the
        z-score on (FR-016) — one entry per distinct day with recorded activity.
        """
        since_s = since.date().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT mentions FROM entity_daily WHERE entity_id = ? AND day >= ? ORDER BY day",
                (entity_id, since_s),
            ).fetchall()
        return [row[0] for row in rows]

    @_guarded(default=lambda: (0, 0, None))
    def history_summary(self) -> tuple[int, int, str | None]:
        """(total_observations, distinct_senders, earliest_observed_date) across all history."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT sender), MIN(observed_date) FROM observation"
            ).fetchone()
        return (row[0], row[1], row[2])

    @_guarded(default=None)
    def mark_job_run(self, job_name: str, status: str, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO job_run (job_name, last_run_at, last_status) VALUES (?, ?, ?) "
                "ON CONFLICT(job_name) DO UPDATE SET last_run_at=excluded.last_run_at, "
                "last_status=excluded.last_status",
                (job_name, now.isoformat(), status),
            )
