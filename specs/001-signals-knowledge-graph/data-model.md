# Data Model: Signals Report — Persistent Knowledge Layer

**Feature**: 001-signals-knowledge-graph | **Date**: 2026-09-03

Three layers, deliberately separated:

1. **Persisted schema** — SQLite tables in `data/signals.db`. The only durable state.
2. **Transfer dataclasses** — frozen dataclasses in `agent/utils/models.py`, per Constitution III.
3. **Configuration dataclasses** — in `agent/utils/config.py`, all optional, absent means disabled.

---

## 1. Persisted Schema (`data/signals.db`)

### `entity`

The canonical subject. One row per real-world thing, regardless of how many spellings reach it.

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | PRIMARY KEY |
| `canonical_name` | TEXT | NOT NULL — display form, e.g. `Nvidia` |
| `norm_key` | TEXT | NOT NULL **UNIQUE** — output of `normalize_key()` |
| `entity_type` | TEXT | NOT NULL — `company` \| `person` \| `country` \| `policy` \| `sector` \| `technology` \| `asset` \| `institution` \| `event` \| `concept` |
| `first_seen` | TEXT | ISO-8601 date |
| `last_seen` | TEXT | ISO-8601 date |

`norm_key` UNIQUE is what makes canonicalization tier 1 (R-004) structurally enforced rather
than merely attempted.

### `entity_alias`

| Column | Type | Constraints |
|---|---|---|
| `alias_key` | TEXT | PRIMARY KEY — normalized alias |
| `entity_id` | INTEGER | NOT NULL, FK → `entity.id` |
| `source` | TEXT | `profile` \| `adjudicated` \| `manual` |

Seeded from `user_profile.yaml` portfolio/watchlist so `UAL` resolves to `United Airlines`
(R-004 tier 2). `source` exists so an adjudication mistake can be found and removed without
disturbing profile-derived aliases.

### `observation`

The atomic unit of memory. One row per (entity, idea).

| Column | Type | Constraints |
|---|---|---|
| `id` | INTEGER | PRIMARY KEY |
| `entity_id` | INTEGER | NOT NULL, FK → `entity.id` |
| `email_id` | TEXT | NOT NULL |
| `idea_index` | INTEGER | NOT NULL — position of the idea within the email |
| `sender` | TEXT | NOT NULL — the newsletter source; drives `source_breadth` |
| `observed_date` | TEXT | NOT NULL — ISO-8601 date |
| `sentiment` | TEXT | NOT NULL — `positive` \| `negative` \| `neutral` |
| `claim_text` | TEXT | the idea body, for traceability (SC-003) |

```sql
UNIQUE (email_id, idea_index, entity_id)
INDEX  (observed_date)
INDEX  (entity_id, observed_date)
```

**The UNIQUE constraint is the feature's most load-bearing line of schema** (FR-006, SC-002,
R-005). Combined with `INSERT OR IGNORE`, re-processing an email under `--preview` is a no-op
rather than a source of fabricated acceleration.

`claim_text` is what makes SC-003 verifiable: every entity in a report traces back to a sentence
a newsletter actually wrote.

### `cooccurrence`

| Column | Type | Constraints |
|---|---|---|
| `entity_a_id` | INTEGER | NOT NULL, FK → `entity.id` |
| `entity_b_id` | INTEGER | NOT NULL, FK → `entity.id` |
| `email_id` | TEXT | NOT NULL |
| `idea_index` | INTEGER | NOT NULL |
| `observed_date` | TEXT | NOT NULL |

```sql
UNIQUE (email_id, idea_index, entity_a_id, entity_b_id)
```

**Idea-scoped, not email-scoped** (R-006). Store the pair with `entity_a_id < entity_b_id`
always, so an edge has exactly one representation.

### `entity_daily`

Survives pruning; preserves long-horizon trend shape after raw observations are gone (R-018).

| Column | Type | Constraints |
|---|---|---|
| `entity_id` | INTEGER | NOT NULL, FK → `entity.id` |
| `day` | TEXT | NOT NULL — ISO-8601 date |
| `mentions` | INTEGER | NOT NULL |
| `distinct_senders` | INTEGER | NOT NULL |
| `net_sentiment` | REAL | NOT NULL — (positive − negative) / total |

```sql
PRIMARY KEY (entity_id, day)
```

### `job_run`

The store-backed cron (R-010). Replaces a second scheduler job, which could never fire under the
deployed launchd configuration.

| Column | Type | Constraints |
|---|---|---|
| `job_name` | TEXT | PRIMARY KEY — e.g. `signals_report` |
| `last_run_at` | TEXT | NOT NULL — ISO-8601 timestamp |
| `last_status` | TEXT | `success` \| `failure` |

### `schema_meta`

| Column | Type | Constraints |
|---|---|---|
| `key` | TEXT | PRIMARY KEY |
| `value` | TEXT | NOT NULL |

Holds `schema_version`. Present from v1 so a later migration has somewhere to look; the
alternative is inferring version from table shape, which does not survive a partial migration.

---

## 2. New Transfer Dataclasses (`agent/utils/models.py`)

All frozen, all stdlib, docstring under each field — matching the existing file's convention.

### `EntityMention`

Extracted alongside an idea; not yet canonicalized.

| Field | Type |
|---|---|
| `name` | `str` |
| `entity_type` | `str` |
| `sentiment` | `str` |

### `EntityTrend`

One entity's deterministically computed movement. **Nothing here is produced by a model.**

| Field | Type | Notes |
|---|---|---|
| `entity_id` | `int` | |
| `name` | `str` | |
| `entity_type` | `str` | |
| `current_count` | `int` | mentions in the current window |
| `prior_count` | `int` | mentions in the preceding window |
| `delta` | `int` | `current − prior` |
| `velocity` | `float` | rate of change |
| `source_breadth` | `int` | distinct senders — enforces FR-014 |
| `z_score` | `float \| None` | `None` when < 8 daily buckets (FR-016) |
| `net_sentiment` | `float` | −1.0 … 1.0 |
| `is_new` | `bool` | first appearance this window (FR-012) |
| `is_fading` | `bool` | previously active, now silent (FR-012) |
| `sample_claims` | `tuple[str, ...]` | up to 3 quotes, for traceability |

### `CooccurrenceEdge`

| Field | Type |
|---|---|
| `entity_a` | `str` |
| `entity_b` | `str` |
| `count` | `int` |
| `is_new` | `bool` |

### `TrendBrief`

What the analysis model receives — and the **only** thing it receives from the store.

| Field | Type | Notes |
|---|---|---|
| `window_days` | `int` | |
| `window_start` | `datetime` | |
| `window_end` | `datetime` | |
| `trends` | `tuple[EntityTrend, ...]` | ranked, truncated to `max_entities_in_prompt` |
| `new_edges` | `tuple[CooccurrenceEdge, ...]` | |
| `total_observations` | `int` | full store count, for the cold-start check |
| `distinct_senders` | `int` | |
| `is_cold_start` | `bool` | history spans < 2 windows (FR-022) |
| `alias_candidates` | `tuple[tuple[str, str], ...]` | near-duplicate pairs for adjudication |

Truncation happens when this object is built, not at render time. That is what makes prompt
size O(config) rather than O(history) (FR-053, SC-005, R-008).

### `MacroIndicator`

| Field | Type | Notes |
|---|---|---|
| `series_id` | `str` | |
| `label` | `str` | human-readable |
| `value` | `float` | |
| `as_of` | `str` | ISO-8601 date (FR-037) |
| `direction` | `str` | `rising` \| `falling` \| `flat` |
| `alarm` | `bool` | threshold crossed (FR-037) |
| `note` | `str` | plain-language reading |

### `MacroSnapshot`

| Field | Type | Notes |
|---|---|---|
| `indicators` | `tuple[MacroIndicator, ...]` | |
| `fetched_at` | `datetime` | |
| `partial` | `bool` | some series failed (FR-039) |

`MacroSnapshot | None` — `None` when unconfigured, and the template renders nothing at all
rather than an empty section (FR-001 of story 2, acceptance scenario 1).

### `SignalItem`

| Field | Type | Notes |
|---|---|---|
| `headline` | `str` | |
| `body` | `str` | mechanism, not restatement |
| `confidence` | `str` | `HIGH` \| `MEDIUM` \| `LOW` (FR-018) |
| `entities` | `tuple[str, ...]` | validated against the brief (FR-019) |
| `citations` | `tuple[str, ...]` | populated only when web search ran (FR-042) |

### `SignalsReport`

| Field | Type | Notes |
|---|---|---|
| `generated_at` | `datetime` | |
| `window_days` | `int` | |
| `macro` | `MacroSnapshot \| None` | |
| `risks` | `tuple[SignalItem, ...]` | |
| `opportunities` | `tuple[SignalItem, ...]` | |
| `emerging` | `tuple[SignalItem, ...]` | |
| `fading` | `tuple[SignalItem, ...]` | |
| `watch` | `tuple[SignalItem, ...]` | |
| `divergences` | `tuple[SignalItem, ...]` | narrative vs. indicators (FR-044) |
| `is_cold_start` | `bool` | (FR-022) |
| `observation_count` | `int` | |

An empty `SignalsReport` with `macro` populated is a **valid, deliverable** report — that is how
FR-038 and SC-009 are satisfied when the model call fails entirely.

### `Theme` *(P3 only)*

| Field | Type |
|---|---|
| `title` | `str` |
| `body` | `str` |
| `sources` | `tuple[str, ...]` |
| `disagreement` | `str \| None` |
| `absorbed_idea_keys` | `tuple[tuple[str, int], ...]` |

`absorbed_idea_keys` holds `(email_id, idea_index)` pairs so the renderer can suppress absorbed
ideas from their per-newsletter sections (FR-048) without mutating any `Summary`.

---

## 3. Modified Existing Dataclasses

### `Idea` (modified)

| Field | Type | Change |
|---|---|---|
| `entities` | `tuple[EntityMention, ...]` | **New.** `field(default_factory=tuple)` |

Defaulted, so every existing construction site — including the fallback `Content Unavailable`
idea at [claude_summarizer.py:84-87](../../agent/summarizer/claude_summarizer.py#L84-L87) —
keeps working untouched.

### `DigestBatch` (modified, P3 only)

| Field | Type | Change |
|---|---|---|
| `themes` | `tuple[Theme, ...]` | **New.** `field(default_factory=tuple)` — empty in P1/P2 |

### `AgentConfiguration` (modified)

| Field | Type | Default |
|---|---|---|
| `knowledge` | `KnowledgeConfig \| None` | `None` |
| `signals` | `SignalsConfig \| None` | `None` |
| `macro` | `MacroConfig \| None` | `None` |
| `fred_api_key` | `str` | `""` |

All four defaulted. `tests/conftest.py::mock_config` constructs a real `AgentConfiguration`
without them, so defaults are what keep 100% of the existing suite inert (R-016).

`fred_api_key` is read from the environment per Constitution II but **must not** join
`_REQUIRED_ENV` (FR-035, SC-013).

---

## 4. Configuration Dataclasses (`agent/utils/config.py`)

### `KnowledgeConfig`

| Field | Type | Default |
|---|---|---|
| `enabled` | `bool` | `True` |
| `db_path` | `str` | `"data/signals.db"` |
| `retention_days` | `int` | `180` |
| `max_entities_per_idea` | `int` | `8` |

### `SignalsConfig`

| Field | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | `bool` | `True` | |
| `interval_days` | `int` | `3` | cost lever (FR-051) |
| `window_days` | `int` | `7` | |
| `min_mentions` | `int` | `3` | FR-014 |
| `min_sources` | `int` | `2` | FR-014 |
| `max_entities_in_prompt` | `int` | `40` | cost lever (FR-051, FR-053) |
| `web_search_enabled` | `bool` | `False` | P2 |
| `web_search_max_uses` | `int` | `5` | cost lever (FR-051) |
| `model` | `str` | `"claude-opus-5"` | |

### `MacroConfig`

| Field | Type | Default |
|---|---|---|
| `enabled` | `bool` | `True` |
| `series` | `list[str]` | the 15 defaults from R-012 |
| `cache_hours` | `int` | `12` |

Each section gets a `_KNOWN_*_KEYS` allowlist mirroring `_KNOWN_SENDER_KEYS`
([config.py:28-30](../../agent/utils/config.py#L28-L30)), so a typo'd key is caught at load
rather than silently ignored.

---

## 5. Entity Relationships

```text
Email ──1:N──> Idea ──1:N──> EntityMention
                 │
                 └── (canonicalized) ──> entity ──1:N──> observation
                                            │                 │
                                            │                 └── rolls up to entity_daily
                                            └──N:M── cooccurrence

entity_daily + observation ──> metrics.compute_brief() ──> TrendBrief   [pure Python, no model]
                                                              │
                                    MacroSnapshot ────────────┤
                                                              ▼
                                                  TrendAnalyzer.analyze()
                                                              │
                                                              ▼
                                                       SignalsReport
                                                              │
                                                              ▼
                                    DigestBuilder.build_signals() ──> EmailDelivery.send()
```

The model sits at exactly one point in this chain, downstream of every number. It cannot see an
`observation`, and it is never asked to produce a count (FR-010).
