# Plan 03 — Give the daily digest its memory: store context for the advisor + "Recurring" badge

**Branch:** `feature/digest-store-context` (cut from `main` after plan 02 merges)

**Depends on:** plan 01 (entities recorded; `extract_text`; `config.model`), plan 02 (template
"context above entries" pattern and `absorbed` variable in the builder)
**Unblocks:** plan 04 (reuses the `recent_context` query shape for "mentions since the call")

## Why

The `data/signals.db` store already knows how often each entity has appeared, from how many
newsletters, and with what sentiment — but only the weekly Signals Report reads it. The daily
`AdvisorAnalyzer` sees **today's summaries only** ([agent/advisor/analyzer.py:93-98](../agent/advisor/analyzer.py#L93-L98)),
so it cannot tell "third time this week" from "first mention." An advisor who has been reading
all week should.

Two user-facing outputs from **one** store query per batch:

1. **Advisor context** — the advisor prompt gains a `RECURRING THIS WEEK` block so relevance and
   signals reflect persistence, not just today's volume.
2. **Idea badge** — under an idea's title, a quiet line such as
   *Recurring · Nvidia · 5 mentions from 3 newsletters this week*, telling the reader at a glance
   that this thread has been building. It **prioritizes; it never hides** anything.

## Design decisions

| Question | Decision | Reason |
|---|---|---|
| Window | Trailing **7 days**, ending at `run_date`, excluding today's own batch. Constant `_WINDOW_DAYS = 7`. | Matches the weekly Signals cadence; "this week" is the phrase readers understand. |
| Threshold for "recurring" | `mentions >= 3` **and** `distinct_senders >= 2`. Constants `_MIN_MENTIONS = 3`, `_MIN_SOURCES = 2`. | One newsletter repeating itself is not a trend (same rule as FR-049). |
| Config keys | **None** new. Behaviour is on whenever `knowledge_graph.enabled: true`. | Constants first; promote to config only if tuning proves necessary. |
| Which entities are looked up | Every entity on every idea in the batch, resolved via `normalize_key` + `entity_alias`. | One query, chunked IN-clause. |
| Badge per idea | At most **one**: the qualifying entity with the highest mention count (tie → alphabetical). | Keeps the digest calm. |
| Store access in `--dry-run` | Open the store for **reads** in dry-run; only `record_summary` stays gated. | Preview must show badges; reads have no side effects. Note: `ObservationStore.__init__` creates the schema file if missing — acceptable, `data/` is gitignored and the constitution allows it. |
| Ordering of work per batch | summarize → **record** today's summaries → query context (`until` = start of today, so today's mentions are excluded) → advisor (with context) → synthesis → build. | Recording first keeps FR-007 ("record before trash") true. Today's mentions are excluded from the window so a story mentioned 4 times *today* does not badge itself as "recurring". |

## Files

| File | Change |
|---|---|
| `agent/utils/models.py` | `EntityContext` dataclass; `DigestBatch.entity_context`. |
| `agent/knowledge/store.py` | `recent_context(norm_keys, since, until)`. |
| `agent/knowledge/context.py` | **New.** Thresholds, `collect_norm_keys(entries)`, `is_recurring(ctx)`, `badge_for_idea(idea, context)`. |
| `agent/advisor/analyzer.py` | `analyze(summaries, entity_context=None)`; prompt block. |
| `agent/runner.py` | Store opened for reads in dry-run; query + wiring; dry-run prints badges. |
| `agent/digest/builder.py` | Compute `badges` and pass to the template. |
| `templates/digest.html.j2` | Badge line under idea title. |
| Tests | `tests/unit/test_observation_store.py`, new `tests/unit/test_context.py`, `tests/test_advisor_analyzer.py`, `tests/test_digest_builder.py`, runner tests. |

## Steps

### Step 1 — Model

`agent/utils/models.py`, near `EntityTrend`:
```python
@dataclass(frozen=True)
class EntityContext:
    """What the store remembers about one entity over the trailing digest window."""

    name: str                # canonical_name from the store
    mentions: int            # observation rows in the window
    distinct_senders: int
    days_active: int         # distinct observed_date values in the window
    net_sentiment: float     # (positive - negative) / mentions, in [-1, 1]
```
`DigestBatch`: add `entity_context: dict[str, EntityContext] = field(default_factory=dict)` —
keyed by **norm_key** — after `themes`.

### Step 2 — Store query

`agent/knowledge/store.py`:
```python
@_guarded(default={})
def recent_context(self, norm_keys: Sequence[str], since: datetime, until: datetime) -> dict[str, EntityContext]:
    """Window statistics for the given normalized entity keys.

    Resolves each key through ``entity.norm_key`` and ``entity_alias`` (same path as
    ``_resolve_entity``). Keys with no observations in [since, until) are absent from the result.
    Dates compare on ``observed_date`` (ISO ``YYYY-MM-DD``), so pass date-aligned boundaries.
    """
```
- Dedupe the input; return `{}` for empty input without opening a connection.
- SQL sketch (per chunk of ≤ 400 keys — SQLite's default variable limit is 999):
  ```sql
  SELECT e.norm_key, e.canonical_name,
         COUNT(*)                        AS mentions,
         COUNT(DISTINCT o.sender)        AS distinct_senders,
         COUNT(DISTINCT o.observed_date) AS days_active,
         SUM(CASE o.sentiment WHEN 'positive' THEN 1 WHEN 'negative' THEN -1 ELSE 0 END) AS net
  FROM entity e
  JOIN observation o ON o.entity_id = e.id
  WHERE e.id IN (
      SELECT id FROM entity WHERE norm_key IN (?, …)
      UNION
      SELECT entity_id FROM entity_alias WHERE alias_norm_key IN (?, …)
  )
    AND o.observed_date >= ? AND o.observed_date < ?
  GROUP BY e.id
  ```
  Read the `entity_alias` column names from the schema at
  [agent/knowledge/store.py:36](../agent/knowledge/store.py#L36) before writing the query and
  check the exact sentiment vocabulary used by `record_summary` — mirror whatever
  `compute_window` does for `net_sentiment`.
- Result key: the **requested** norm_key that matched (if resolution went through an alias, key
  by the alias key the caller asked for, so the caller's lookups succeed). Simplest: return a
  second mapping internally, or compute `alias_norm_key -> entity_id` first and then map back.

Tests (`tests/unit/test_observation_store.py`, class `TestRecentContext`, real SQLite in `tmp_path`,
seed with `record_summary` using `Summary` + `Idea(entities=...)` exactly as existing tests do):
- `test_counts_mentions_senders_days_and_sentiment_in_window`
- `test_observations_outside_window_are_excluded` (both before `since` and on/after `until`)
- `test_unknown_key_absent_from_result`
- `test_empty_input_returns_empty_dict`
- `test_alias_key_resolves_to_canonical_entity` (insert an `entity_alias` row directly with `sqlite3`)
- `test_more_than_400_keys_are_chunked` (450 keys, 2 seeded — result has exactly 2)
- `test_disabled_store_returns_empty_dict` (reuse the corrupted-file pattern at line 134)

### Step 3 — Context helpers

`agent/knowledge/context.py`:
```python
_WINDOW_DAYS = 7
_MIN_MENTIONS = 3
_MIN_SOURCES = 2

def context_window(run_date: datetime) -> tuple[datetime, datetime]:
    """[start of (run_date - 7 days), start of run_date) in UTC — today's batch is excluded."""

def collect_norm_keys(entries: Sequence[DigestEntry]) -> list[str]:
    """Unique normalize_key() of every entity on every idea, in first-seen order."""

def is_recurring(ctx: EntityContext) -> bool:
    return ctx.mentions >= _MIN_MENTIONS and ctx.distinct_senders >= _MIN_SOURCES

def badge_for_idea(idea: Idea, context: Mapping[str, EntityContext]) -> str | None:
    """'Recurring · {name} · {n} mentions from {k} newsletters this week' for the strongest
    recurring entity on the idea, else None. Singular/plural handled ('1 newsletter' cannot
    occur given _MIN_SOURCES, but '3 mentions' vs a hypothetical '1 mention' should read right)."""

def recurring_lines(context: Mapping[str, EntityContext], limit: int = 10) -> list[str]:
    """Prompt lines for the advisor, strongest first:
    '- Nvidia: 5 mentions, 3 newsletters, 4 days, sentiment +0.6'."""
```
Tests (`tests/unit/test_context.py`): each function; window boundaries at midnight UTC;
`badge_for_idea` picks highest mentions and breaks ties alphabetically; returns `None` when no
entity qualifies; `recurring_lines` respects `limit` and formats sentiment with sign.

### Step 4 — Advisor prompt

`agent/advisor/analyzer.py`:
- `analyze(self, summaries, entity_context: Mapping[str, EntityContext] | None = None)`.
- `_build_user_message(summaries, entity_context)`: after the summaries, when
  `recurring_lines(...)` is non-empty, append:
  ```
  RECURRING THIS WEEK (from the reader's newsletter history, excluding today):
  - Nvidia: 5 mentions, 3 newsletters, 4 days, sentiment +0.6
  ...
  ```
- `_SYSTEM_PROMPT`: add one sentence before `READER PROFILE:`:
  `"When a RECURRING THIS WEEK list is provided, weigh persistence: a topic several newsletters have returned to across days matters more than a single day's volume. Say so explicitly when it changes your read.\n\n"`
- Log `recurring_count=len(lines)` in `advisor_analysis_complete`.

Tests (`tests/test_advisor_analyzer.py`): `test_user_message_has_no_recurring_block_when_context_none`,
`test_user_message_has_no_recurring_block_when_nothing_qualifies`,
`test_user_message_lists_recurring_entities_strongest_first`, and an assertion that the system
prompt is **unchanged except for the added sentence** is unnecessary — but do keep existing
prompt tests green.

### Step 5 — Runner

`agent/runner.py::_run_digest`:
- Line 96–99: open the store whenever `self.config.knowledge is not None and self.config.knowledge.enabled`
  (drop the `not self.dry_run` condition). Update the comment at lines 177–178.
- Recording: `if observation_store is not None and not self.dry_run: record_summary(...)`.
- After recording:
  ```python
  entity_context = {}
  if observation_store is not None:
      since, until = context_window(run_date)
      entity_context = observation_store.recent_context(collect_norm_keys(entries), since, until)
  ```
- Move the advisor call **below** this and pass `entity_context=entity_context`.
- Pass `entity_context=entity_context` into `DigestBatch`.
- Dry-run: under each idea title print the badge when `badge_for_idea(idea, digest_batch.entity_context)` is not `None`.

Tests (runner module from plan 01): `test_store_opened_for_reads_in_dry_run_but_record_not_called`,
`test_advisor_receives_entity_context`, `test_context_window_excludes_run_date`.

### Step 6 — Builder + template

`agent/digest/builder.py::build`: compute
`badges = {(entry.summary.email_id, i): badge for each idea i where badge_for_idea(...) is not None}`
and pass `badges=badges` (default `{}` at the top of the template like `absorbed`).

`templates/digest.html.j2`, inside the visible-ideas loop from plan 02, directly under the
`idea-title` paragraph:
```jinja
{% set badge = badges.get((entry.summary.email_id, idx)) %}
{% if badge %}
<p style="margin: 0 0 6px; font-size: 11px; font-weight: 600; color: #7c9a6a; letter-spacing: 0.02em;">{{ badge }}</p>
{% endif %}
```
(`idx` is the original idea index carried in the `visible` list from plan 02.) Absorbed ideas
have no badge (they aren't rendered); themes do not get badges in this plan.

Tests (`tests/test_digest_builder.py`, class `TestDigestBuilderBadges`):
- `test_no_context_renders_identical_html_to_previous_plan` (batch without `entity_context` vs with `{}`)
- `test_badge_rendered_under_qualifying_idea`
- `test_only_one_badge_per_idea_even_with_two_recurring_entities`
- `test_no_badge_below_threshold`
- `test_absorbed_idea_gets_no_badge`

### Step 7 — Docs

README: a short "Memory in the daily digest" paragraph (what the badge means, the 3-mentions /
2-newsletters / 7-days rule, that it never hides content). `CLAUDE.md` Recent Changes line.

## Out of scope

- Any new YAML keys (thresholds are constants).
- Suppressing, reordering, or filtering ideas or newsletters by context.
- Badges on themes; sentiment arrows in the badge.
- Writing to `entity_alias` (still unwired; see plan 04's note).

## Acceptance checklist

- [ ] `knowledge_graph` absent or disabled → HTML byte-identical to plan 02 output (test proves it).
- [ ] One store query per batch (`recent_context` called once — assert `call_count == 1` in the runner test).
- [ ] Advisor prompt carries `RECURRING THIS WEEK` only when something qualifies.
- [ ] Badge text is deterministic and matches `Recurring · {name} · {n} mentions from {k} newsletters this week`.
- [ ] `--dry-run` shows badges and does **not** write observations.
- [ ] `pytest -q -m "not integration"` green; `ruff check agent/` clean; touched files clean.
