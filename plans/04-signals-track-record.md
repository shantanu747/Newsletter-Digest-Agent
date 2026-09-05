# Plan 04 — Signals track record: the advisor remembers its calls and scores them

**Branch:** `feature/signals-track-record` (cut from `main` after plan 03 merges)

**Depends on:** plan 01 (`extract_text`), plan 03 (`recent_context`-style window queries)

## Why

An advisor whose calls are never checked cannot be trusted or improved. Today each Signals
Report is written and forgotten. This plan makes the agent **persist every Signals Report
item**, and at **7 and 30 days** after each call, compute what happened — the price move of the
related profile ticker (when there is one) and how newsletter coverage of the call's entities
evolved — then render a **Track Record** section at the top of the next Signals Report with a
1–2 sentence model interpretation per call.

All numbers are computed in code. The model only writes the commentary and is validated against
known call ids, exactly as `TrendAnalyzer` validates entities today (FR-019 pattern).

## Design decisions

| Question | Decision |
|---|---|
| What is a "call" | Every `SignalItem` in `risks`, `opportunities`, `emerging`, `fading`, `watch` of a delivered (non-dry-run) report. `divergences` are not calls. |
| Horizons | `_REVIEW_HORIZONS_DAYS = (7, 30)`. A review at horizon H is due when `now - report_date >= H days` and no `signal_review` row exists for `(call_id, H)`. Calls older than `_MAX_CALL_AGE_DAYS = 90` are never reviewed (keeps the section short). |
| Price source | Stooq daily CSV: `https://stooq.com/q/d/l/?s={symbol}&i=d`, fetched with stdlib `urllib.request`, parsed with `csv`. Symbol = `ticker.lower() + ".us"` unless the ticker already contains a `.`, in which case it is used as-is lower-cased. 10 s timeout. Fail-soft: any exception, HTTP error, or the literal `No data` body → empty result and a warning log. **No new dependency.** |
| Entity → ticker | Match each call entity's `normalize_key` against `normalize_key` of each profile holding's `name` **and** `ticker` (portfolio + watchlist). First match wins; a call with no match gets `ticker=None` and is reviewed on mentions only. |
| Price change | `close(on or after made_on + H days, first trading day) / close(on or before made_on, last trading day) - 1`, as a percentage rounded to 1 dp. If either boundary is missing (< 3 trading days of slack) → `None`. |
| Mentions since | `recent_context([entity keys], since=made_on, until=review_date)` summed across the call's entities: `mentions_since`, `sources_since`, and mention-weighted `sentiment_since`. |
| Persistence of prices | `price_daily(ticker, day, close)` cache in the store, refreshed per review run for tickers due. |
| Where rendered | "Track Record" section directly after the cold-start banner, before the macro dashboard, in `signals.html.j2`. Only reviews **produced in this run** are shown (fresh ones), grouped by horizon. |
| Config | `SignalsConfig.track_record_enabled: bool = True`. Default on: the section is empty until calls age, so nothing changes visibly on day one. |
| Schema | Bump `_SCHEMA_VERSION` to `"2"`. New tables are `CREATE TABLE IF NOT EXISTS`, so an existing v1 file upgrades in place; the version row is updated with `INSERT OR REPLACE`. |
| Dry-run | `--signals-dry-run` computes and renders the track record (fetching prices is allowed — read-only network) but records neither calls nor reviews. |

## Files

| File | Change |
|---|---|
| `agent/knowledge/store.py` | Schema v2: `signal_call`, `signal_review`, `price_daily`; methods below. |
| `agent/prices/__init__.py`, `agent/prices/stooq.py` | **New.** `StooqPriceFetcher`. |
| `agent/trends/track_record.py` | **New.** `resolve_ticker`, `build_track_record`. |
| `agent/utils/models.py` | `CallReview`; `SignalsReport.track_record`. |
| `agent/utils/config.py` | `SignalsConfig.track_record_enabled`; `_KNOWN_SIGNALS_KEYS`. |
| `agent/trends/analyzer.py` | `analyze(brief, macro, track_record=())`; prompt block; `---TRACK RECORD---` parsing + validation. |
| `agent/runner.py::maybe_run_signals` | Wire it. |
| `agent/digest/builder.py::build_signals` | Log counts; nothing else. |
| `templates/signals.html.j2` | Track Record section. |
| `config/newsletters.yaml` | `track_record_enabled: true` under `signals:`. |
| Tests | store, stooq, track_record, trend_analyzer, signals_cadence, builder. |

## Steps

### Step 1 — Schema v2 + store methods

`agent/knowledge/store.py` — append to `_SCHEMA_STATEMENTS`:
```sql
CREATE TABLE IF NOT EXISTS signal_call (
    id INTEGER PRIMARY KEY,
    report_date TEXT NOT NULL,        -- YYYY-MM-DD
    section TEXT NOT NULL,            -- risks|opportunities|emerging|fading|watch
    headline TEXT NOT NULL,
    body TEXT NOT NULL,
    confidence TEXT NOT NULL,
    entity_names TEXT NOT NULL,       -- JSON list of the item's entity strings
    ticker TEXT                       -- resolved at record time; NULL when no profile match
);
CREATE INDEX IF NOT EXISTS idx_signal_call_report_date ON signal_call(report_date);
CREATE TABLE IF NOT EXISTS signal_review (
    call_id INTEGER NOT NULL REFERENCES signal_call(id),
    horizon_days INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,
    price_change_pct REAL,
    mentions_since INTEGER NOT NULL,
    sources_since INTEGER NOT NULL,
    sentiment_since REAL NOT NULL,
    PRIMARY KEY (call_id, horizon_days)
);
CREATE TABLE IF NOT EXISTS price_daily (
    ticker TEXT NOT NULL,
    day TEXT NOT NULL,
    close REAL NOT NULL,
    PRIMARY KEY (ticker, day)
);
```
`_SCHEMA_VERSION = "2"`; in `_ensure_schema` use `INSERT OR REPLACE` for the version row.

Methods (all `@_guarded`):
- `record_signal_calls(self, report: SignalsReport, report_date: date, ticker_for: Callable[[tuple[str,...]], str | None]) -> int`
  — deletes existing rows for the same `report_date` first (re-runs replace, never duplicate),
  inserts one row per item across the five sections, returns count. Default `0`.
- `calls_due_for_review(self, now: datetime, horizons: Sequence[int], max_age_days: int) -> list[tuple[SignalCallRow, int]]`
  — every `(call, horizon)` pair where `report_date + horizon <= now.date()`,
  `report_date >= now.date() - max_age_days`, and no `signal_review` row exists. Default `[]`.
  `SignalCallRow` is a small frozen dataclass in `models.py` (`id, report_date, section, headline, body, confidence, entity_names: tuple[str,...], ticker: str|None`).
- `record_reviews(self, reviews: Sequence[CallReview], now: datetime) -> int` — `INSERT OR REPLACE`. Default `0`.
- `upsert_prices(self, ticker: str, rows: Sequence[tuple[str, float]]) -> int` and
  `closes_between(self, ticker: str, start: date, end: date) -> list[tuple[str, float]]` (ascending). Defaults `0` / `[]`.

Tests (`tests/unit/test_observation_store.py`):
- Update `test_creates_all_seven_tables_and_schema_version` → ten tables, version `"2"`.
- `test_v1_database_upgrades_to_v2_in_place` (create a store, manually set version to `"1"` and drop the three new tables, reopen → tables exist and version is `"2"`, existing observation rows intact).
- `TestSignalCalls`: record 5 items across sections → 5 rows; re-record same date → still 5; `divergences` not recorded; `ticker_for` result stored; `entity_names` round-trips as a tuple.
- `TestCallsDueForReview`: due at exactly H days; not due at H-1; not due when a review exists; a 7-day review does not block the 30-day one; calls older than `max_age_days` excluded; ordering by `report_date, id, horizon`.
- `TestPrices`: upsert idempotent; `closes_between` inclusive and ascending.
- `test_disabled_store_returns_defaults_for_new_methods`.

### Step 2 — Stooq fetcher

`agent/prices/stooq.py`:
```python
_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
_TIMEOUT_SECONDS = 10

def stooq_symbol(ticker: str) -> str:
    """'NVDA' -> 'nvda.us'; 'BRK-B' -> 'brk-b.us'; 'nvda.us' -> 'nvda.us'."""

class StooqPriceFetcher:
    """Fetches daily closes from Stooq's CSV endpoint. Fail-soft: returns [] on any problem."""

    def __init__(self, opener: Callable[[str, int], bytes] | None = None) -> None:
        # opener defaults to a urllib.request.urlopen wrapper; injectable for tests

    def daily_closes(self, ticker: str, start: date, end: date) -> list[tuple[str, float]]:
        """[(YYYY-MM-DD, close), ...] ascending, filtered to [start, end]. [] on failure."""
```
CSV header is `Date,Open,High,Low,Close,Volume`. Body `No data` (or fewer than 2 lines) → `[]`.
Parse with `csv.DictReader`; skip rows whose `Close` is not a float. Log
`price_fetch_failed` with `ticker` and the exception class name; never raise.

Tests (`tests/unit/test_stooq.py`, inject `opener`):
`test_symbol_mapping_cases`, `test_parses_csv_and_filters_to_range`, `test_no_data_body_returns_empty`,
`test_http_error_returns_empty`, `test_timeout_returns_empty` (opener raises `TimeoutError`),
`test_malformed_row_skipped`, `test_uses_10_second_timeout` (assert opener called with `_TIMEOUT_SECONDS`).

### Step 3 — Track record computation

`agent/utils/models.py`:
```python
@dataclass(frozen=True)
class CallReview:
    call_id: int
    made_on: date
    horizon_days: int
    section: str
    headline: str
    confidence: str
    entities: tuple[str, ...]
    ticker: str | None
    price_change_pct: float | None
    mentions_since: int
    sources_since: int
    sentiment_since: float
    commentary: str = ""     # filled by TrendAnalyzer; "" when the model fails
```
`SignalsReport.track_record: tuple[CallReview, ...] = field(default_factory=tuple)` (last field).

`agent/trends/track_record.py`:
```python
_REVIEW_HORIZONS_DAYS = (7, 30)
_MAX_CALL_AGE_DAYS = 90
_PRICE_SLACK_DAYS = 5   # trading-day tolerance around each boundary

def resolve_ticker(entity_names: Sequence[str], profile: UserProfile | None) -> str | None:
    """First profile holding (portfolio then watchlist) whose name or ticker normalizes equal to
    any entity name. None when profile is None or nothing matches."""

def price_change(closes: Sequence[tuple[str, float]], made_on: date, horizon_days: int) -> float | None:
    """Percent change between the last close on/before made_on and the first close on/after
    made_on + horizon_days. None if either side is missing within _PRICE_SLACK_DAYS."""

def build_track_record(store, profile, fetcher, now: datetime) -> tuple[CallReview, ...]:
    """Compute every due review. Never raises — a failing ticker just yields price None.
    Fetches each distinct ticker once, upserts into price_daily, reads back via closes_between."""
```
`mentions_since`/`sources_since`/`sentiment_since` use `store.recent_context(keys, since=made_on 00:00, until=review day 00:00)` and sum/aggregate across the call's entities (sentiment = mention-weighted mean; 0.0 when no mentions).

Tests (`tests/unit/test_track_record.py`, real store in `tmp_path`, fake fetcher returning canned closes):
- `resolve_ticker`: matches by name, by ticker, case/punctuation-insensitive, portfolio wins over watchlist, `None` when unmatched or profile `None`.
- `price_change`: exact days; weekend boundary uses nearest trading day within slack; missing side → `None`; rounding to 1 dp.
- `build_track_record`: one review per due `(call, horizon)`; ticker fetched once for two calls sharing it; `None` ticker skips fetch and still yields mention stats; fetcher raising → price `None`, others unaffected; mention stats reflect observations recorded after `made_on` only.

### Step 4 — TrendAnalyzer commentary

`agent/trends/analyzer.py`:
- `analyze(self, brief, macro, track_record: Sequence[CallReview] = ())`.
- When `track_record` is non-empty, append to the brief text:
  ```
  TRACK RECORD — your earlier calls, now reviewed (numbers computed deterministically):
  CALL_ID 17 | made 2026-08-05 | 30d | OPPORTUNITIES | HIGH | "Data center demand still climbing" | Nvidia | price +12.4% | 9 mentions from 4 newsletters since, sentiment +0.5
  ...
  ```
  and add to `_SYSTEM_PROMPT` a seventh section instruction:
  ```
  ---TRACK RECORD---
  For each CALL_ID in the TRACK RECORD list (and only those ids), write:
  CALL_ID: <id>
  BODY: one or two sentences — did the call play out, and what does the price and coverage
  evidence say about why. Be direct; "too early to tell" is a valid verdict when the evidence is flat.
  ```
- `_SECTION_DELIMITERS` gains `("track_record", "---TRACK RECORD---")`. Parse that section with a
  separate regex `_REVIEW_RE = re.compile(r"CALL_ID:\s*(?P<id>\d+)\s*\nBODY:\s*(?P<body>.+?)(?=\nCALL_ID:|\Z)", re.S)`.
  Ids not in the supplied `track_record` are dropped and logged (`track_record_unknown_call_id`).
  Reviews with no commentary keep `commentary=""`.
- On retry exhaustion, the empty report carries `track_record` through **unchanged** (like `macro`).

Tests (`tests/unit/test_trend_analyzer.py`): prompt contains the TRACK RECORD block only when
supplied; commentary attached to the right review; unknown id dropped; missing section leaves
commentary `""`; exhaustion passes reviews through; existing tests unchanged.

### Step 5 — Config + runner + template

`agent/utils/config.py`: `SignalsConfig.track_record_enabled: bool = True`, `_KNOWN_SIGNALS_KEYS`
add `"track_record_enabled"`, parse with `bool(raw.get("track_record_enabled", True))`.
`config/newsletters.yaml` under `signals:`: `track_record_enabled: true` with a one-line comment.

`agent/runner.py::maybe_run_signals` inside the `try`:
```python
track_record: tuple[CallReview, ...] = ()
if self.config.signals.track_record_enabled:
    track_record = build_track_record(store, self.config.user_profile, StooqPriceFetcher(), now)

report = TrendAnalyzer(...).analyze(brief, macro, track_record=track_record)
html = build_signals(report, now)
...
if not dry_run:
    self._delivery.send(...)
    store.record_reviews(report.track_record, now)
    store.record_signal_calls(
        report, now.date(),
        ticker_for=lambda names: resolve_ticker(names, self.config.user_profile),
    )
```
Record **after** a successful send so an undelivered report is not scored. Dry-run prints
`Track record: {n} reviews` in the existing summary line.

`templates/signals.html.j2` — after the cold-start banner `{% endif %}` (line 119), before
`{% if report.macro %}`:
```jinja
{% if report.track_record %}
<tr>
  <td class="section" style="padding: 32px 40px 8px;">
    <p style="margin: 0 0 14px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #86868b;">Track Record</p>
    {% for review in report.track_record %}
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #fefefe; border-radius: 14px; margin-bottom: 14px;">
      <tr><td style="padding: 18px 20px;">
        <p style="margin: 0 0 4px; font-size: 12px; color: #a1a1a6;">{{ review.horizon_days }}-day review &middot; called {{ review.made_on.strftime('%b %-d') }} &middot; {{ review.section | capitalize }}</p>
        <p style="margin: 0 0 8px; font-size: 15px; font-weight: 600; color: #1d1d1f;">{{ review.headline }}</p>
        <p style="margin: 0 0 8px; font-size: 13px; color: #3a3a3c;">
          {% if review.price_change_pct is not none %}<strong>{{ review.ticker }}</strong> {{ '%+.1f' % review.price_change_pct }}% &middot; {% endif %}
          {{ review.mentions_since }} mention{{ 's' if review.mentions_since != 1 }} from {{ review.sources_since }} newsletter{{ 's' if review.sources_since != 1 }} since
        </p>
        {% if review.commentary %}<p style="margin: 0; font-size: 14px; color: #3a3a3c; line-height: 1.7;">{{ review.commentary | nl2br }}</p>{% endif %}
        <div style="margin-top: 10px;">{{ confidence_badge(review.confidence) }}</div>
      </td></tr>
    </table>
    {% endfor %}
  </td>
</tr>
{% endif %}
```
Price colour: green (`#7c9a6a`) for positive, red (`#a13a3a`) for negative — apply inline on the `<strong>`/percentage span.

Tests:
- `tests/unit/test_signals_cadence.py`: patch `agent.trends.track_record.build_track_record` and
  `agent.prices.stooq.StooqPriceFetcher`; assert `record_signal_calls`/`record_reviews` called on
  real runs, **not** on dry-run, and not when the send raises; flag off → `build_track_record` not called.
- `tests/test_digest_builder.py` (or a signals builder test module if one exists — check
  `grep -rl build_signals tests`): section absent when `track_record` empty; renders price and
  mentions; omits price when `None`; commentary optional; pluralization.

### Step 6 — Docs + follow-up note

- README: "Track Record" section — what is scored, the two horizons, that prices come from
  Stooq (free, unauthenticated, daily), that only profile tickers get price scoring, and the
  standing disclaimer.
- `CLAUDE.md` Recent Changes; add `agent/prices/` to the structure notes.
- Add a **Follow-ups** note at the bottom of this plan file when done: `seed_aliases_from_profile`
  in `agent/knowledge/canonicalize.py` is still unwired (`entity_alias` never populated), which
  limits alias resolution in `recent_context`; wiring it at store open is a small later task
  (Phase 6, T076-ish) and would improve both plan 03 badges and this plan's mention stats.

## Out of scope

- Scoring daily-digest BUY/SELL/WATCH lines.
- Any price source other than Stooq; intraday data; FX/crypto symbol mapping beyond the `.us` rule.
- Aggregate hit-rate statistics across all calls (a later feature once there are enough reviews).
- Showing old reviews again — only reviews produced in the current run render.

## Acceptance checklist

- [ ] A v1 `signals.db` opens as v2 with data intact (test proves it).
- [ ] Calls recorded only after a successful, non-dry-run send; never duplicated for the same report date.
- [ ] Reviews computed at exactly 7 and 30 days, once each, for calls ≤ 90 days old.
- [ ] Stooq failure of any kind → price `None`, run continues, no exception escapes `maybe_run_signals`.
- [ ] Commentary only attaches to known call ids; report never fails for lack of commentary.
- [ ] `track_record_enabled: false` → no fetch, no new prompt text, no section.
- [ ] `pytest -q -m "not integration"` green; `ruff check agent/` clean; touched files clean.
- [ ] Manual smoke: `python -m agent --signals-dry-run` on a store with calls older than 7 days prints `Track record: N reviews` and the rendered section is visible via `scripts/signals_preview.py --open` (extend the preview script's `_synthesize` to insert a few back-dated `signal_call` rows so this can be exercised without waiting a week).

## Follow-ups

`seed_aliases_from_profile` in `agent/knowledge/canonicalize.py` is still unwired
(`entity_alias` never populated), which limits alias resolution in
`recent_context`; wiring it at store open is a small later task (Phase 6,
T076-ish) and would improve both plan 03 badges and this plan's mention stats.

Clarifications settled during implementation (2026-09-05): `_PRICE_SLACK_DAYS = 5`
(Step 3 wins over the design table's "< 3 trading days"); `recent_context` runs
with `until` = now date (everything since the call, per the "now date" answer —
`mentions_since`/`sources_since`/`sentiment_since` are cumulative, not capped at
the horizon day); branch kept as `feature/signals-track-record` (plan header wins
over plans/README's `001-` prefix).
