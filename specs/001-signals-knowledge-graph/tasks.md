# Tasks: Signals Report — Persistent Knowledge Layer and Trend-Based Early Warning

**Input**: Design documents from `/specs/001-signals-knowledge-graph/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Test tasks ARE included. `plan.md` lists six new test files as deliverables, and the
majority of this feature (`metrics.py`, `canonicalize.py`, `store.py`) is testable with zero API
calls — which is what makes it cheap to iterate on. Tests are written alongside each unit, not
before it, matching this repository's existing practice.

**Organization**: Tasks are grouped by user story so each can be implemented, tested, and shipped
independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths included in all descriptions

## House Conventions (apply to every task)

- Tests live in `tests/unit/`, use `pytest-mock`, patch with `mocker.patch("anthropic.Anthropic", ...)`
  at **package** level, use module-level `_make_*` factories rather than fixtures, and group into
  plain `Test<Unit>` namespace classes.
- **Do not introduce `@pytest.mark.parametrize`** — it appears nowhere in this repository.
- No `print()` outside `scripts/` (Constitution V). Use `structlog` via `get_logger(__name__)`.
- All new dataclasses are `@dataclass(frozen=True)` with a docstring under each field, matching
  `agent/utils/models.py`.

---

## Phase 1: Setup

**Purpose**: Establish the baseline and the governance/infrastructure changes that authorize
persistent state, before any code depends on it.

- [X] T001 Run `pytest` from the repository root and record the passing test count — this is the green baseline. Without it there is no way to distinguish a pre-existing failure from one this feature introduces. Do not proceed if the suite is already red.
- [X] T002 [P] Add `data/` to `.gitignore` under a new `# === Operational state ===` section, near the existing `# === Local examples & test data ===` block
- [X] T003 [P] Raise the `anthropic` pin in `requirements.txt` from `>=0.40.0` to `>=0.60.0` (required for the `web_search` server tool in US2; installed version is already 0.84.0)
- [X] T004 Amend `.specify/memory/constitution.md` to v1.1.0: add `| Persistence | sqlite3 (stdlib) |` and `| Macro data | FRED API via urllib (stdlib) |` rows to the Tech Stack table; extend Principle II with "Operational state lives in `data/`, is gitignored, and its absence must never fail a run."; update the version footer to `**Version**: 1.1.0 | **Ratified**: 2026-03-08 | **Last Amended**: 2026-09-03` and add a rationale note per the Governance section
- [X] T005 [P] Correct the "No persistent database; stateless per-run" claims in `CLAUDE.md` — the `## Active Technologies` line tagged `(001-newsletter-digest-agent)` and the `Stateless files` line tagged `(001-digest-agent-enhancements)` — to note that `001-signals-knowledge-graph` introduces a local SQLite store at `data/signals.db`
- [X] T006 [P] Add the three new sections to `config/newsletters.yaml` **commented out**, with the full annotated key set from `specs/001-signals-knowledge-graph/contracts/config.md` (`knowledge_graph:`, `signals:`, `macro:`). Commented out is deliberate: an uncommented section would enable the feature for the current user before it exists.

**Checkpoint**: `pytest` still green. `python -c "import yaml; yaml.safe_load(open('config/newsletters.yaml'))"` succeeds and the three new sections parse as absent. `git check-ignore data/` returns 0.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Typed data transfer objects and configuration plumbing that every user story depends
on. Nothing here changes runtime behavior — after this phase the feature is fully defined and
fully inert.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T007 Add `EntityMention` frozen dataclass (`name: str`, `entity_type: str`, `sentiment: str`) to `agent/utils/models.py`, positioned above `Idea`
- [X] T008 Add `entities: tuple[EntityMention, ...] = field(default_factory=tuple)` to the existing `Idea` dataclass in `agent/utils/models.py`. **Must be defaulted** — every existing construction site, including the `Content Unavailable` fallback at `agent/summarizer/claude_summarizer.py:84-87`, must keep working untouched.
- [X] T009 [P] Add `EntityTrend`, `CooccurrenceEdge`, and `TrendBrief` frozen dataclasses to `agent/utils/models.py` per the field tables in `specs/001-signals-knowledge-graph/data-model.md` §2. `EntityTrend.z_score` is `float | None`; `TrendBrief.trends` is already ranked and truncated by the time it is constructed.
- [X] T010 [P] Add `MacroIndicator` and `MacroSnapshot` frozen dataclasses to `agent/utils/models.py`. Define them now even though they are unused until US2 — `SignalsReport.macro` references `MacroSnapshot`, and a forward reference across stories is a needless import problem.
- [X] T011 [P] Add `SignalItem` and `SignalsReport` frozen dataclasses to `agent/utils/models.py`. `SignalsReport` must be constructible with all signal tuples empty and `macro` populated — that combination is a valid deliverable artifact (FR-038).
- [X] T012 Add `KnowledgeConfig`, `SignalsConfig`, and `MacroConfig` dataclasses to `agent/utils/config.py` with the defaults in `data-model.md` §4, plus three `_KNOWN_*_KEYS` allowlists mirroring `_KNOWN_SENDER_KEYS` at `agent/utils/config.py:28-30`
- [X] T013 Add `knowledge: KnowledgeConfig | None = None`, `signals: SignalsConfig | None = None`, `macro: MacroConfig | None = None`, and `fred_api_key: str = ""` fields to `AgentConfiguration` in `agent/utils/config.py`. **All four must have defaults** — `tests/conftest.py::mock_config` constructs a real `AgentConfiguration` without them, and defaulting is what keeps every new code path inert across 100% of the existing suite.
- [X] T014 Add `_parse_knowledge_config`, `_parse_signals_config`, and `_parse_macro_config` helpers to `agent/utils/config.py`, and wire them into `load_config()` near the existing optional-file pattern at `agent/utils/config.py:270-277`. Each returns `None` when its section is absent. Import `get_logger` **locally inside each function**, matching the convention at `agent/utils/config.py:265` that exists to break an import cycle. Raise `ConfigurationError` on unknown keys, on `signals` present without `knowledge_graph`, and warn-and-ignore on `macro` present without `signals`.
- [X] T015 Read `FRED_API_KEY` into `cfg.fred_api_key` in `load_config()` using `os.environ.get("FRED_API_KEY", "")`. **Do NOT add it to `_REQUIRED_ENV` at `agent/utils/config.py:18-26`** — that list raises `ConfigurationError` on any missing entry, so adding it would stop an existing user's agent from starting (FR-035, SC-013).
- [X] T016 [P] Create empty package markers `agent/knowledge/__init__.py` and `agent/trends/__init__.py`
- [X] T017 [P] Add `tests/unit/test_signals_config.py` asserting: all three sections absent → all three config attributes are `None`; unknown key → `ConfigurationError`; `signals` without `knowledge_graph` → `ConfigurationError`; missing `FRED_API_KEY` → `load_config()` succeeds with `fred_api_key == ""`

**Checkpoint**: `pytest` green with the same count as T001 plus the new tests. `python -c "from agent.utils.config import load_config; c=load_config(); print(c.knowledge, c.signals, c.macro)"` prints `None None None`. No behavior has changed anywhere.

---

## Phase 3: User Story 1 — Signals Report From Newsletter History (Priority: P1) 🎯 MVP

**Goal**: Record what each idea is about, accumulate it across runs, compute trends
deterministically, and email a periodic Signals Report — using nothing but the newsletters the
agent already processes.

**Independent Test**: Seed a scratch store with 30 days of synthetic observations via
`python scripts/signals_preview.py --synthesize 30`, then run
`python scripts/signals_preview.py --no-llm` and confirm the rising, emerging, and fading sections
are populated and every named entity exists in the underlying store.

### Canonicalization and Storage

- [X] T018 [US1] Implement `normalize_key(name: str) -> str` in `agent/knowledge/canonicalize.py`: NFKD normalize, casefold, strip possessive `'s`, strip trailing corporate suffixes (`inc`, `corp`, `corporation`, `ltd`, `limited`, `plc`, `nv`, `sa`, `ag`, `co`, `llc`), collapse whitespace and punctuation. Must resolve `Nvidia` ≡ `NVIDIA Corp.` ≡ `Nvidia's` to one key.
- [X] T019 [US1] Implement `seed_aliases_from_profile(profile: UserProfile) -> list[tuple[str, str]]` in `agent/knowledge/canonicalize.py`, mapping each portfolio and watchlist entry's `ticker` to its `name` so `UAL` resolves to `United Airlines` — a pair no string algorithm can bridge
- [X] T020 [US1] Implement `find_alias_candidates(names: list[str], threshold: float = 0.86) -> list[tuple[str, str]]` in `agent/knowledge/canonicalize.py` using `difflib.SequenceMatcher`. Returns candidate pairs only; it does not merge. Adjudication rides the trend call in T033.
- [X] T021 [P] [US1] Add `tests/unit/test_canonicalize.py` covering: the three Nvidia spellings collapsing to one key; ticker/name alias seeding from a `_make_profile()` factory; `find_alias_candidates` proposing `Fed` / `Federal Reserve` but not `Apple` / `Applied Materials`
- [X] T022 [US1] Create `agent/knowledge/store.py` with the `ObservationStore` class and `_ensure_schema()` creating all seven tables from `data-model.md` §1: `entity`, `entity_alias`, `observation`, `cooccurrence`, `entity_daily`, `job_run`, `schema_meta`. **`UNIQUE(email_id, idea_index, entity_id)` on `observation` is mandatory** — it is what makes FR-006 structural rather than aspirational. Add indexes on `observation(observed_date)` and `observation(entity_id, observed_date)`. Seed `schema_meta.schema_version = "1"`.
- [X] T023 [US1] Implement the connection strategy in `agent/knowledge/store.py`: a `@contextmanager _connect()` opening per call with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=10000`. No long-lived connection — a manual invocation may run concurrently with the scheduled one.
- [X] T024 [US1] Implement the never-raises contract in `agent/knowledge/store.py`: wrap every public method so any `sqlite3.Error` (corrupt file, locked database, read-only filesystem) is logged via `structlog`, sets `self._enabled = False`, and turns every subsequent method into a no-op returning an empty result. `job_due()` returns `False` when disabled. **Never auto-delete or auto-recreate a corrupt store** (FR-034) — losing months of history to a transient disk error is not acceptable automatic recovery.
- [X] T025 [US1] Implement `has_email(email_id) -> bool` and `record_summary(summary: Summary) -> int` in `agent/knowledge/store.py`. `record_summary` resolves each `EntityMention` through `normalize_key` → alias table → existing `entity` row (inserting when new), writes observations with `INSERT OR IGNORE`, writes idea-scoped `cooccurrence` pairs with `entity_a_id < entity_b_id` always, and upserts `entity_daily`. Returns the count of newly inserted observations. `has_email` short-circuits the whole path for an already-recorded email.
- [X] T026 [US1] Implement `compute_window(start, end) -> list[EntityTrend]` and `new_edges(start, end) -> list[CooccurrenceEdge]` in `agent/knowledge/store.py` as index-backed aggregate queries. `compute_window` returns raw per-entity counts, distinct-sender counts, sentiment sums, and up to 3 `sample_claims` per entity; it does **not** rank, threshold, or truncate — that is `metrics.py`'s job.
- [X] T027 [P] [US1] Add `tests/unit/test_observation_store.py` covering: schema creation on a `tmp_path` database; `record_summary` inserting the expected row count; **calling `record_summary` twice with the same `Summary` leaves the count unchanged (SC-002)**; co-occurrence pairs stored with `a < b`; a deliberately corrupted database file making every method a silent no-op and `job_due` return `False` (SC-007); a read-only directory not raising

### Entity Extraction (folded into the existing summarization call)

- [X] T028 [US1] Add a `{entity_section}` placeholder to `_IDEA_SYSTEM_PROMPT_TEMPLATE` in `agent/summarizer/claude_summarizer.py` and a `_build_entity_section(knowledge_config) -> str` helper that returns `""` when the config is `None` or disabled. **The disabled render must be byte-identical to today's prompt** — `tests/unit/test_idea_format.py:43,46` assert on this template directly, and byte-identity is what makes SC-001 provable rather than hoped for.
- [X] T029 [US1] Write the enabled `entity_section` text in `agent/summarizer/claude_summarizer.py` instructing one trailing line per idea: `ENTITIES: Nvidia (company, negative); export controls (policy, negative)`. Cap at `max_entities_per_idea`. Enumerate the permitted types (`company`, `person`, `country`, `policy`, `sector`, `technology`, `asset`, `institution`, `event`, `concept`) and the three sentiments. Instruct that sentiment reflects **the idea's framing of that entity**, not the newsletter's overall tone.
- [X] T030 [US1] Extend `_parse_ideas()` in `agent/summarizer/claude_summarizer.py` to split a trailing `ENTITIES:` line off each idea body into a tuple of `EntityMention`. **A body with no `ENTITIES:` line must produce the identical `title` and `summary_text` as today plus `entities=()`** — `tests/unit/test_idea_format.py:51-60` depends on this. Malformed entries are skipped individually, never raised: this response is the user's digest, and one bad entity must not cost them the batch.
- [X] T031 [US1] Thread the knowledge config into `summarize_as_ideas()` in `agent/summarizer/claude_summarizer.py` and through the `ClaudeSummarizer.__init__` signature, defaulting to `None`
- [X] T032 [P] [US1] Add extraction cases to `tests/unit/test_idea_format.py`: disabled render is byte-identical to the pre-change template (guard for T028); an `ENTITIES:` line parses into the right mentions; a response with no `ENTITIES:` line yields unchanged titles/bodies and `entities=()`; a malformed entity entry is skipped while its siblings survive

### Deterministic Trend Metrics

- [X] T033 [US1] Implement `compute_brief(store, config, now) -> TrendBrief` in `agent/trends/metrics.py`. **This module is pure: no API calls, no file I/O beyond the store handle passed in.** For each entity compute `delta`, `velocity`, `source_breadth`, `net_sentiment`, `is_new`, `is_fading`, and `z_score` against that entity's own `entity_daily` history. Apply the FR-014 gate (`min_mentions` AND `min_sources`) before anything is eligible. Rank by a composite salience score and **truncate to `max_entities_in_prompt`** — this is what makes prompt size O(config) not O(history). Set `is_cold_start` when history spans fewer than two windows. Attach `find_alias_candidates` output.
- [X] T034 [US1] Enforce the z-score guard in `agent/trends/metrics.py`: return `z_score = None` when the entity has fewer than 8 daily buckets (FR-016). A z-score over three data points is theatre, and the report must not present one.
- [X] T035 [P] [US1] Add `tests/unit/test_metrics.py` — the largest new suite, and it makes **zero API calls**. Cover: an entity with 5 mentions from 1 sender is excluded while 5 from 4 senders is included (SC-004); `is_new` and `is_fading` flags; `z_score is None` below 8 buckets; **truncation to `max_entities_in_prompt` holding the brief's size within 20% between a 300-observation store and a 30,000-observation store (SC-005)**; `is_cold_start` true below two windows

### Trend Analysis

- [X] T036 [US1] Create `agent/trends/analyzer.py` with `TrendAnalyzer`, structurally mirroring `agent/advisor/analyzer.py:118-171`: 3 attempts, exponential backoff with jitter, `structlog` logging, and an empty-result return on exhaustion. It constructs **its own `TokenBucketLimiter`** and acquires before every call — `AdvisorAnalyzer` skips this, but here a single logical analysis can become several API calls (Constitution IV).
- [X] T037 [US1] Write the system prompt in `agent/trends/analyzer.py`. Hand the model the pre-computed brief and ask **only for interpretation** — which movements are real, the causal mechanism, and what opportunity or risk follows. State explicitly that it must not compute or restate counts, and that every entity it names must come from the brief. Request delimited sections (`---RISKS---`, `---OPPORTUNITIES---`, `---EMERGING---`, `---FADING---`, `---WATCH---`, `---DIVERGENCE---`), not JSON, matching the delimiter convention at `agent/advisor/analyzer.py:20-21`. Include the alias-candidate adjudication ask.
- [X] T038 [US1] Implement `_extract_text(response) -> str` in `agent/trends/analyzer.py` that iterates content blocks and concatenates those with `block.type == "text"`. **Must not reuse the `response.content[0].text` pattern** from `agent/advisor/analyzer.py:145` — that assumes block 0 is text, which stops being true in US2 once a server-side tool is enabled. Keep this helper local to `TrendAnalyzer`; changing the shared pattern would break `_make_api_response` in the existing tests.
- [X] T039 [US1] Implement `_parse_response()` in `agent/trends/analyzer.py` with the deterministic validator running **before** a `SignalsReport` is constructed: drop any `SignalItem` naming an entity absent from the brief (FR-019, SC-003); downgrade `HIGH` confidence to `MEDIUM` when the item carries no evidence (FR-020). An invented entity is the failure most likely to destroy trust permanently — a report that says less is recoverable; one that confidently names a company no newsletter mentioned is not.
- [X] T040 [US1] Implement `analyze(brief, macro) -> SignalsReport` in `agent/trends/analyzer.py`. On retry exhaustion it returns a `SignalsReport` with empty signal tuples but `macro` passed through unchanged, and **never raises** (FR-029).
- [X] T041 [P] [US1] Add `tests/unit/test_trend_analyzer.py` covering: a well-formed delimited response parsing into the right sections; an item naming an entity absent from the brief being dropped; evidence-free `HIGH` downgraded to `MEDIUM`; three consecutive `anthropic.APIError` raises returning an empty report rather than propagating; the rate limiter being acquired before each attempt

### Report Rendering and Delivery

- [X] T042 [US1] Extract the Jinja environment construction from `DigestBuilder.build()` into `_make_env()` in `agent/digest/builder.py`, preserving the existing `FileSystemLoader` path, the `_nl2br` filter, and the `_safe_url` filter. **`tests/test_digest_builder.py` patches `jinja2.Environment.get_template` at class level across 13 methods** — that target must stay valid.
- [X] T043 [US1] Add `build_signals(report: SignalsReport, run_date: datetime) -> str` to `agent/digest/builder.py` using `_make_env()`. Do **not** parameterize `build()`'s template name: its render kwargs (`total_found`, `failed_subjects`, `batch_index`) are digest-specific and meaningless to a report.
- [X] T044 [US1] Create `templates/signals.html.j2` as a **sibling** of `digest.html.j2`, not a child. Sections in most-actionable-first order: Macro Dashboard (renders nothing when `report.macro is None`), Accelerating Risks, Opportunities, Emerging Themes, **Fading Stories**, Watch Items. Every item shows its confidence level (FR-018). Render the cold-start banner when `report.is_cold_start` (FR-022). Footer states plainly that this is a reading assistant and not investment advice (FR-021). Match the existing table-based email HTML and inline-CSS approach — do not introduce a stylesheet.
- [X] T045 [P] [US1] Add `tests/unit/test_signals_builder.py` covering: a report with all sections empty and `macro=None` still rendering valid HTML; the cold-start banner appearing only when `is_cold_start`; the advice disclaimer always present; confidence levels rendered for every item

### Runner Integration and Cadence

- [X] T046 [US1] Add the observation-recording hook to `agent/runner.py` immediately after the advisor block at `agent/runner.py:141-148`: lazily import `ObservationStore`, gate on `self.config.knowledge is not None and not self.dry_run`, and call `record_summary` for each entry. **It must run before delivery and `move_to_trash`** — after trashing, the email is gone and the observation is unrecoverable (FR-007). `--dry-run` must write nothing (FR-008); `--preview` **does** write, which is exactly why T022's UNIQUE constraint exists.
- [X] T047 [US1] Restructure `agent/runner.py`: extract the body of `run()` from the fetch onward into `_run_digest()`, so the early return at `agent/runner.py:71-73` no longer governs the whole method. `run()` becomes: call `_run_digest()` inside `try`, then call `maybe_run_signals(now)` in a `finally`. **This is the gap that makes FR-026 and SC-006 real** — a due report must fire on days with zero unread newsletters, which are exactly the quiet stretches when a trend report is most useful because no digest is arriving either. A digest exception must also not suppress it.
- [X] T048 [US1] Implement `job_due(job_name, interval_days, now) -> bool` and `mark_job_run(job_name, status, now)` in `agent/knowledge/store.py` against the `job_run` table. **`mark_job_run` must be called on both success and failure** (FR-028) — a persistently broken analysis that reset only on success would retry every 4 hours and drain the user's budget on a call that cannot succeed.
- [X] T049 [US1] Implement `maybe_run_signals(now)` on `NewsletterAgent` in `agent/runner.py`: return early unless `config.signals` is enabled and `store.job_due(...)`; then build the brief, run the analyzer, render, send via the **unchanged** `EmailDelivery.send()` with a distinct subject line (FR-024), and `mark_job_run` in a `finally`. Wrap the whole body so no exception can escape into `run()` (FR-029).
- [X] T050 [P] [US1] Add `tests/unit/test_signals_cadence.py` covering: `job_due` false before the interval elapses and true after; `mark_job_run` called on both the success and the failure path; **`maybe_run_signals` invoked when `fetch_newsletters` returns an empty list (SC-006)**; `maybe_run_signals` invoked even when `_run_digest` raises; an analyzer exception not propagating out of `run()`

### CLI and Developer Harness

- [X] T051 [US1] Add `--signals`, `--signals-dry-run`, and `--skip-signals` to `_parse_args()` in `agent/runner.py:243-265`, and wire them in `main()` at `agent/runner.py:268-287`. `--signals` and `--signals-dry-run` run **no digest** — coupling them to a fetch would consume unread emails as a side effect of a diagnostic command. `--signals` beats `--skip-signals` when both are given: an explicit request beats blanket suppression.
- [X] T052 [US1] Create `scripts/signals_preview.py` with `--synthesize N`, `--no-llm`, `--open`, and `--db PATH`. **Required scope, not a nice-to-have**: a fresh install has zero history, so without synthesis the feature is invisible and un-iterable for a week — you cannot tune the trend prompt, verify the metrics, or lay out the template against an empty store (FR-030, SC-011). `--synthesize` generates plausible multi-sender observations with deliberate rising, fading, and new-entity patterns so every report section is exercised. Defaults to a temp database and **must never write to `data/signals.db`**. `print()` is permitted here — `scripts/` is exempt from Constitution V, per `scripts/test_pipeline.py`.

**Checkpoint — User Story 1 is complete and independently shippable.** Verify:

```bash
pytest                                                    # green, count ≥ T001 baseline
python -m agent --dry-run && test ! -d data/              # SC-001: digest unchanged, no data/ created
python scripts/signals_preview.py --synthesize 30 --no-llm   # metrics end-to-end, zero API calls
python scripts/signals_preview.py --open                  # full report rendered and inspected
python -m agent --signals-dry-run                         # end-to-end, nothing sent
python -m agent --preview && sqlite3 data/signals.db "select count(*) from observation"
python -m agent --preview && sqlite3 data/signals.db "select count(*) from observation"   # SC-002: identical
```

---

## Phase 4: User Story 2 — Ground The Signals In External Reality (Priority: P2)

**Goal**: Anchor the report in measured data — a macroeconomic dashboard and live web-search
corroboration — and surface divergence when the newsletters' narrative disagrees with the numbers.

**Independent Test**: With `FRED_API_KEY` unset, confirm the report renders identically to its US1
form with no empty dashboard section. With it set and responses simulated, confirm every configured
indicator renders with its alarm state, and that the dashboard survives a total analyzer failure.

### Macro Dashboard

- [ ] T053 [US2] Create `agent/fetchers/fred_fetcher.py` with `FredFetcher` using stdlib `urllib.request`, a 10-second per-request timeout, and 3 attempts with exponential backoff. **A peer of `BaseFetcher`, not a subclass** — that ABC's contract is `fetch_newsletters(config) -> list[Email]`, and inheriting would mean implementing a method that returns emails from an economic data API.
- [ ] T054 [US2] Add the module-level alarm-threshold table to `agent/fetchers/fred_fetcher.py` covering all 15 series in `contracts/config.md`, with a plain-language `note` per series. These are **domain knowledge, not user preference** — a user should not have to know that a 10y-3m spread below zero is the inversion signal.
- [ ] T055 [US2] Implement `fetch_snapshot() -> MacroSnapshot | None` in `agent/fetchers/fred_fetcher.py`: returns `None` when no API key is configured; computes `direction` from the trailing observations; sets `alarm` from the threshold table; sets `partial=True` when some series fail and at least one succeeds (FR-039). **Never raises.**
- [ ] T056 [US2] Add the 12-hour JSON cache to `agent/fetchers/fred_fetcher.py` at `data/macro_cache.json`, written via atomic `os.replace`. A cache read failure falls through to a live fetch rather than raising.
- [ ] T057 [US2] Fetch the snapshot in `maybe_run_signals` in `agent/runner.py` **before** calling `TrendAnalyzer.analyze`, and pass it through. It must be rendered even when the analyzer returns an empty report (FR-038, SC-009) — the dashboard is deterministic and has no reason to die with the model call.
- [ ] T058 [US2] Add the Macro Dashboard block to `templates/signals.html.j2`: one row per indicator with value, as-of date, direction, and note (FR-037); alarm rows visually distinguished; a "data is partial" line when `partial`; **the entire section omitted when `report.macro is None`** — an empty dashboard section reads as breakage, an absent one reads as "not configured"
- [ ] T059 [P] [US2] Add `tests/unit/test_fred_fetcher.py` covering: no API key → `None`; all series succeeding → a full snapshot with correct alarm states; some series failing → `partial=True` with the survivors present; a network error on every series → `None` rather than a raise; a fresh cache short-circuiting the fetch

### Web Search Corroboration

- [ ] T060 [US2] Add the `web_search_20260209` server tool to the request in `agent/trends/analyzer.py`, gated on `config.web_search_enabled` and bounded by `max_uses=config.web_search_max_uses`
- [ ] T061 [US2] Handle `stop_reason == "pause_turn"` in `agent/trends/analyzer.py` by appending the response content and re-calling, **bounded at 3 continuations** so a pathological search loop cannot run away. Acquire the rate limiter before each continuation (Constitution IV).
- [ ] T062 [US2] Guard search-error blocks in `agent/trends/analyzer.py` with `isinstance(block.content, list)` before iterating. **Search errors return HTTP 200 with an error object where a list is expected** — without this guard a failed search raises a `TypeError` deep inside result parsing, which is the subtly-broken failure rather than the obviously-broken one.
- [ ] T063 [US2] Populate `SignalItem.citations` from `web_search_result` blocks in `agent/trends/analyzer.py`, and render them in `templates/signals.html.j2` (FR-042). A search failure or exhausted ceiling leaves citations empty and the report still ships (FR-043).
- [ ] T064 [US2] Add divergence detection to the prompt and `_parse_response` in `agent/trends/analyzer.py`: when the newsletters' collective narrative on a topic contradicts a related indicator's direction, emit it into `SignalsReport.divergences` as its own finding rather than averaging it away (FR-044). Render the section in `templates/signals.html.j2`.
- [ ] T065 [P] [US2] Add web-search cases to `tests/unit/test_trend_analyzer.py`: a response leading with tool-use blocks still extracting text correctly (the `content[0].text` regression); a single `pause_turn` continuation completing; 4 consecutive `pause_turn` responses stopping at the bound; a search-error block with a non-list `content` not raising; `web_search_enabled=False` sending no tools at all

**Checkpoint**: Both grounding forms work and both are independently switchable. With
`FRED_API_KEY` unset and `web_search_enabled: false`, the report is byte-identical to its US1 form.

---

## Phase 5: User Story 3 — Cross-Newsletter Theme Synthesis (Priority: P3, deferrable)

**Goal**: Merge the day's ideas across newsletters into deduplicated themes that cite their sources
and state where those sources disagree, so a story covered by four newsletters is read once.

**Independent Test**: Process a batch in which four newsletters cover the same story and confirm the
digest contains one merged theme naming all four sources, with those four ideas no longer appearing
in their per-newsletter sections.

> **Deferrable by design.** If this never ships, the daily digest is unchanged and US1/US2 are
> unaffected. It is cheap *because* US1 shipped — clustering is a set intersection over entities
> that already exist. Without US1 it would need its own classification pass over every idea.

- [ ] T066 [US3] Add the `Theme` frozen dataclass to `agent/utils/models.py` per `data-model.md` §2, and `themes: tuple[Theme, ...] = field(default_factory=tuple)` to `DigestBatch`. Defaulted, so US1/US2 behavior is untouched.
- [ ] T067 [US3] Add `synthesis_enabled: bool = False` to `SignalsConfig` (or a new `synthesis` section) in `agent/utils/config.py`, defaulting to off so the digest is unchanged until explicitly enabled (FR-050)
- [ ] T068 [US3] Implement `cluster_ideas(entries) -> list[list[tuple[str, int]]]` in `agent/trends/synthesis.py`, grouping ideas by shared canonical entities from US1's extraction. **Require ≥2 distinct senders per cluster** (FR-049) — one author making the same point in three ideas is not corroboration and must not be presented as a merged theme.
- [ ] T069 [US3] Implement `synthesize_themes(clusters, api_key)` in `agent/trends/synthesis.py`: one Claude call per cluster producing a merged title and body that names every contributing source (FR-046) and **states explicitly where the sources disagree** (FR-047) rather than smoothing it into a single narrative. Mirror the retry and never-raises shape of `TrendAnalyzer`; on failure the cluster simply does not become a theme and its ideas render normally.
- [ ] T070 [US3] Call synthesis in `agent/runner.py` after summarization and before `DigestBuilder.build()`, gated on the config flag, and populate `DigestBatch.themes`
- [ ] T071 [US3] Add the theme block to `templates/digest.html.j2` above the per-newsletter entries, and suppress absorbed ideas using `Theme.absorbed_idea_keys` (FR-048). Suppress at render time — do **not** mutate any `Summary`, which is frozen and is also what gets recorded to the store.
- [ ] T072 [P] [US3] Add `tests/unit/test_synthesis.py` covering: four senders on one story producing one theme naming four sources; three ideas from a single sender **not** clustering; absorbed ideas absent from their per-newsletter sections while unabsorbed ideas render unchanged; synthesis disabled producing byte-identical digest HTML (FR-050)

**Checkpoint**: All three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: The P1 items `plan.md` identifies as able to slip without the user noticing, plus
final validation.

- [ ] T073 [P] Implement `prune(retention_days, now) -> int` in `agent/knowledge/store.py`: delete `observation` and `cooccurrence` rows older than the cutoff while leaving `entity_daily` untouched (FR-009). Claim text is what ages; trend shape is what the reader wants over long horizons.
- [ ] T074 Call `prune()` from `maybe_run_signals` in `agent/runner.py` after a successful report, so pruning rides an operation that already runs on a cadence
- [ ] T075 [P] Add `--store-stats` to `agent/runner.py` printing observation count, entity count, distinct senders, date range, and database size via `ObservationStore.stats()`. Read-only.
- [ ] T076 [P] Add `--rebuild-store` to `agent/runner.py`, **prompting for confirmation** before recreating the schema. The only destructive operation in the feature, and never automatic (FR-034).
- [ ] T077 Implement alias-candidate adjudication in `agent/trends/analyzer.py`: parse confirmed merges out of the response and write them to `entity_alias` with `source='adjudicated'` via a new `ObservationStore.merge_alias()`. Rides the existing call, so it adds no new API surface.
- [ ] T078 [P] Update `README.md` with a Signals Report section: what it is, how to enable it, the cold-start expectation, and the three cost levers
- [ ] T079 Run the full verification sequence in `specs/001-signals-knowledge-graph/quickstart.md`, including the corrupt-store degradation check and the two-run idempotency check
- [ ] T080 Run `pytest && ruff check .` from the repository root — the repo's standing polish pair

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T004/T005 (governance) can proceed alongside T002/T003/T006.
- **Foundational (Phase 2)**: Depends on Setup. **Blocks all user stories.**
- **US1 (Phase 3)**: Depends on Foundational. No dependencies on other stories.
- **US2 (Phase 4)**: Depends on **US1** — it extends `TrendAnalyzer.analyze()` and `signals.html.j2`, neither of which exists until US1 ships. This is a genuine dependency, not a preference.
- **US3 (Phase 5)**: Depends on **US1's entity extraction** (T028–T032) but not on the rest of US1, and not on US2 at all. Could in principle start once T032 lands.
- **Polish (Phase 6)**: Depends on US1 at minimum.

### Critical Path Within US1

```text
T018–T021 (canonicalize) → T022–T027 (store) → T028–T032 (extraction) → T046 (record hook)
                                             ↘ T033–T035 (metrics) → T036–T041 (analyzer)
                                                                    ↘ T042–T045 (render)
                                                                    → T047–T050 (cadence)
                                                                    → T051–T052 (CLI + harness)
```

T033 (`metrics.py`) depends on T026 (`compute_window`) but on nothing downstream — it is pure, and
most of it can be written and tested against a hand-built store before the analyzer exists.

### Parallel Opportunities

- **Phase 1**: T002, T003, T005, T006 all touch different files
- **Phase 2**: T009, T010, T011 are independent dataclass additions; T016 and T017 are independent
- **Phase 3**: the four `[P]` test tasks (T021, T027, T032, T035, T041, T045, T050) each pair with a
  unit that is complete by the time they run
- **Across stories**: US3 can be built by a second person once T032 lands, in parallel with the rest
  of US1 — it needs the entities, not the report

### Parallel Example: US1 Storage Layer

```bash
# Once T018–T020 land, these are independent files:
Task: "Add tests/unit/test_canonicalize.py"                      # T021
Task: "Create agent/knowledge/store.py schema"                   # T022

# Once T026 lands:
Task: "Add tests/unit/test_observation_store.py"                 # T027
Task: "Implement compute_brief in agent/trends/metrics.py"       # T033
```

---

## Implementation Strategy

### MVP: User Story 1 only (T001–T052)

1. Phase 1 Setup — **T001 first**, always. The green baseline is what distinguishes a failure this
   feature caused from one that was already there.
2. Phase 2 Foundational — after this the feature is fully defined and fully inert.
3. Phase 3 US1 — the complete loop, using nothing but the newsletters already processed.
4. **STOP and VALIDATE** against the Phase 3 checkpoint, especially the two-run idempotency check.
5. Run in production for at least two analysis windows before starting US2. The cold-start period is
   not a bug to engineer around — it is the honest state of a store with no history, and watching
   it fill is how you find out whether the trends mean anything.

### Incremental Delivery

| Increment | Tasks | Delivers |
|---|---|---|
| MVP | T001–T052 | Signals Report from newsletter history alone |
| +Grounding | T053–T065 | Macro dashboard + web-search corroboration + divergence |
| +Synthesis | T066–T072 | Story read once instead of four times |
| +Polish | T073–T080 | Pruning, diagnostics, alias merging, docs |

Each increment is independently shippable and independently reversible: removing a config section
returns the system to the prior increment's behavior with no code change.

### The Three Things Most Likely To Go Wrong

1. **T028's placeholder is not byte-identical when disabled** → `tests/unit/test_idea_format.py:43,46`
   go red and SC-001 becomes unprovable. Check this the moment T028 lands.
2. **T022's UNIQUE constraint is omitted or misordered** → `--preview` manufactures 6× fake
   acceleration daily. The failure presents as a *confident false alarm*, which is worse than a
   missing feature and much harder to notice.
3. **T047's restructure is skipped** and `maybe_run_signals` is simply appended to `run()` → reports
   silently never fire on quiet days, and nothing in the logs says so.
