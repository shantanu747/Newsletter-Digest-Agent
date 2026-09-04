# Contract: Internal Module Boundaries

**Feature**: 001-signals-knowledge-graph

Three contracts carry the spec's degradation requirements (FR-029, FR-033, FR-043). They are
recorded here because they are the ones that, if broken, turn an optional enhancement into a
reason the user stops receiving their daily digest.

---

## `ObservationStore` — never raises

```python
class ObservationStore:
    def __init__(self, db_path: str) -> None: ...
    def has_email(self, email_id: str) -> bool: ...
    def record_summary(self, summary: Summary) -> int: ...
    def compute_window(self, start: datetime, end: datetime) -> list[EntityTrend]: ...
    def new_edges(self, start: datetime, end: datetime) -> list[CooccurrenceEdge]: ...
    def job_due(self, job_name: str, interval_days: int, now: datetime) -> bool: ...
    def mark_job_run(self, job_name: str, status: str, now: datetime) -> None: ...
    def prune(self, retention_days: int, now: datetime) -> int: ...
    def stats(self) -> dict: ...
```

**Contract**: No method raises. Any `sqlite3.Error` — including a corrupt file, a locked
database, or a read-only filesystem — is logged, sets `self._enabled = False`, and every
subsequent method becomes a no-op returning an empty result. `job_due` returns `False` when
disabled, so a broken store cannot trigger an analysis over data it cannot read.

**Rationale**: FR-033 and SC-007. The daily digest is the thing the user actually depends on;
an optional memory layer must never be able to take it down.

**Corollary**: a disabled store must never be auto-deleted or auto-recreated (FR-034). Recovery
is `--rebuild-store`, explicitly invoked.

**Connection strategy**: no long-lived connection. A `@contextmanager _connect()` per call opens
with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=10000`. The agent may run concurrently
with a manual invocation, and WAL plus a busy timeout is what keeps that from being a
`database is locked` failure.

---

## `TrendAnalyzer` — never raises, mirrors `AdvisorAnalyzer`

```python
class TrendAnalyzer:
    def __init__(self, api_key: str, config: SignalsConfig,
                 user_profile: UserProfile | None) -> None: ...
    def analyze(self, brief: TrendBrief,
                macro: MacroSnapshot | None) -> SignalsReport: ...
```

**Contract**: 3 attempts, exponential backoff with jitter, `TokenBucketLimiter.acquire()` before
each call *including `pause_turn` continuations*. On exhaustion, returns a `SignalsReport` with
empty signal tuples but `macro` still populated. Never raises.

This mirrors [analyzer.py:118-171](../../../agent/advisor/analyzer.py#L118-L171) deliberately —
the retry shape, the logging, the empty-result return. One difference: `AdvisorAnalyzer` does not
rate-limit; `TrendAnalyzer` must, because a single logical analysis can become four API calls
once `pause_turn` continuations are in play (Constitution IV).

**Rationale**: FR-038 and SC-009 — an empty report carrying a populated macro dashboard is a
valid, deliverable artifact. The dashboard is deterministic and has no reason to die with the
model call.

**Response parsing**: `TrendAnalyzer` uses its own `_extract_text()` that iterates content blocks
for `block.type == "text"`. It must **not** reuse the `response.content[0].text` pattern from
[analyzer.py:145](../../../agent/advisor/analyzer.py#L145) — with a server-side tool enabled,
block 0 is a tool-use block, and the existing pattern silently returns the wrong thing or raises.

---

## `FredFetcher` — a peer of `BaseFetcher`, not a subclass

```python
class FredFetcher:
    def __init__(self, api_key: str, config: MacroConfig) -> None: ...
    def fetch_snapshot(self) -> MacroSnapshot | None: ...
```

**Contract**: Returns `None` when no API key is configured. Returns a snapshot with
`partial=True` when some series fail and at least one succeeds. Never raises. Per-request timeout
of 10 seconds; a slow FRED must not stall a digest run.

**Not a `BaseFetcher` subclass**: that ABC's contract is
`fetch_newsletters(config) -> list[Email]`. Inheriting would mean implementing a method that
returns emails from an economic data API — inheritance for the sake of directory tidiness.
It lives in `agent/fetchers/` because that is where things that fetch belong.

---

## `runner.py` integration points

**Observation recording** — immediately after the advisor block at
[runner.py:141-148](../../../agent/runner.py#L141-L148), lazily imported, gated on
`config.knowledge` and `not self.dry_run`. It must run **before delivery and `move_to_trash`**:
after trashing, the email is gone and the observation is unrecoverable (FR-007).

**Cadence evaluation** — `maybe_run_signals(now)` must execute even when
`fetch_newsletters` returns nothing. The early return at
[runner.py:71-73](../../../agent/runner.py#L71-L73) must be restructured (extract the digest body
into `_run_digest()`; call `maybe_run_signals` in a `finally`), so that neither an empty inbox
nor a digest exception can suppress a due report (FR-026, SC-006).
