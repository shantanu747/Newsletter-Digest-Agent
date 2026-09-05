# Implementation Plan: Signals Report — Persistent Knowledge Layer and Trend-Based Early Warning

**Branch**: `001-signals-knowledge-graph` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/001-signals-knowledge-graph/spec.md`

## Summary

Give the agent memory, and a second analysis pass over it. As each newsletter is decomposed into
ideas, the agent also extracts the concepts and entities each idea concerns plus how it frames
them, and persists those observations to a local SQLite store. Every few days a separate
`TrendAnalyzer` reads deterministically-computed movements out of that store and emails a
**Signals Report** — accelerating risks, opportunities, emerging themes, fading stories, watch
items — as its own email on its own cadence.

The architecture's load-bearing decision: **Python computes every number; the model only
interprets.** `metrics.py` produces a ranked, truncated `TrendBrief`, and that brief is the only
thing the model sees from the store. This makes trend fabrication structurally impossible
(FR-010), makes prompt size O(config) rather than O(history) (FR-053), and makes the majority of
the feature unit-testable with zero API calls.

Delivered as three independently shippable slices. P1 needs nothing external. P2 adds a FRED
macro dashboard and web-search corroboration, each separately switchable. P3 merges cross-source
ideas in the daily digest and is explicitly deferrable.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: `anthropic` SDK (raise `requirements.txt` from `>=0.40.0` to `>=0.60.0` for the `web_search` server tool), `Jinja2`, `PyYAML`, `structlog`, `pytest` + `pytest-mock`. **No new third-party dependencies.**  
**Storage**: SQLite via stdlib `sqlite3` at `data/signals.db` — the project's first persistent state. Macro responses cached to `data/macro_cache.json`. Both gitignored.  
**Testing**: `pytest` + `pytest-mock`; tests in `tests/unit/`, `mocker.patch("anthropic.Anthropic", ...)` at package level, module-level `_make_*` factories, no `parametrize`  
**Target Platform**: macOS/Linux, deployed as a launchd job running `python3 -m agent --once` every 4 hours  
**Project Type**: CLI agent / scheduled pipeline  
**Performance Goals**: Signals analysis prompt stays 3–5k tokens regardless of store size (SC-005). Observation recording adds no measurable latency — extraction is folded into an existing call. Metrics computation over 30k observations completes in under a second on index-backed queries.  
**Constraints**: Ongoing cost ≈ $2.60/month, bounded by three config levers. No new mandatory configuration for existing installs (FR-035). A missing or corrupt store must degrade to today's behavior, never fail a run (FR-033).  
**Scale/Scope**: ~20 newsletters/day × ~6 ideas × ~4 entities ≈ 500 observations/day; ~90k rows at the 180-day retention default.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design. Both passes below.*

| Principle | Status | Notes |
|---|---|---|
| I. Separation of Concerns | PASS | `ObservationStore`, `TrendAnalyzer`, `FredFetcher` are dedicated classes. Entity extraction is folded into `ClaudeSummarizer` — which *is* the dedicated summarization client; no call is made inline from `runner.py`. Each unit is independently testable with mocked dependencies. |
| II. Secrets Management | PASS (amended) | `FRED_API_KEY` from env via `python-dotenv`; three new non-secret sections in `newsletters.yaml`. Requires the Principle II extension below to cover operational state in `data/`. |
| III. Typed Data Transfer | PASS | 9 new frozen dataclasses (`EntityMention`, `EntityTrend`, `CooccurrenceEdge`, `TrendBrief`, `MacroIndicator`, `MacroSnapshot`, `SignalItem`, `SignalsReport`, `Theme`). Type hints on all public signatures. |
| IV. Reliability & Rate Limiting | PASS | `TrendAnalyzer` constructs its own `TokenBucketLimiter` and acquires before every call including `pause_turn` continuations. 3 attempts with exponential backoff on both the analyzer and the FRED fetcher. Logs signals-run start, entity counts, and report delivery. |
| V. Observability | PASS | `structlog` throughout. `print()` appears only in `scripts/signals_preview.py`, and `scripts/` is exempt — `scripts/test_pipeline.py` sets that precedent. |

### Required Amendment — Constitution v1.1.0

The Tech Stack table has no storage row, and `CLAUDE.md` asserts "No persistent database;
stateless per-run" in three places. This feature makes all four statements false. Governance
requires amendments carry a rationale note, so this is **P1 scope, not follow-up cleanup**:

- Tech Stack gains `| Persistence | sqlite3 (stdlib) |` and `| Macro data | FRED API via urllib (stdlib) |`
- Principle II extended: *"Operational state lives in `data/`, is gitignored, and its absence must never fail a run."*
- `CLAUDE.md` statelessness claims corrected
- Version → 1.1.0, MINOR: this adds to the stack and broadens a principle; it revokes nothing

Leaving this undone means every subsequent `/speckit.analyze` flags the feature as a violation,
and the next reader of `CLAUDE.md` is told the system is stateless when it is not.

**Post-Phase-1 re-evaluation**: no new violations. The design introduced no third-party
dependency and no inline API call. **Complexity Tracking is not required.**

## Project Structure

### Documentation (this feature)

```text
specs/001-signals-knowledge-graph/
├── plan.md              ← this file
├── research.md          ← Phase 0: 22 resolved decisions
├── data-model.md        ← Phase 1: schema + dataclasses
├── quickstart.md        ← Phase 1: dev harness, verification, reader setup
├── contracts/
│   ├── cli.md           ← 5 new flags + preview harness
│   ├── config.md        ← 3 optional YAML sections + env
│   └── internal.md      ← never-raises contracts for store, analyzer, fetcher
├── checklists/
│   └── requirements.md  ← 16/16 pass
└── tasks.md             ← Phase 2 (/speckit.tasks — not created here)
```

### Source Code Changes

```text
NEW
agent/knowledge/__init__.py
agent/knowledge/store.py               ← ObservationStore: schema, record, window queries, job_run
agent/knowledge/canonicalize.py        ← normalize_key(), alias resolution, difflib candidates
agent/trends/__init__.py
agent/trends/metrics.py                ← PURE: EntityTrend + TrendBrief. No API calls. No I/O.
agent/trends/analyzer.py               ← TrendAnalyzer: the one interpretive call
agent/fetchers/fred_fetcher.py         ← FredFetcher (peer of BaseFetcher, not a subclass)  [P2]
templates/signals.html.j2              ← sibling of digest.html.j2, not a child
scripts/signals_preview.py             ← --synthesize / --no-llm / --open  (required scope)
tests/unit/test_observation_store.py
tests/unit/test_canonicalize.py
tests/unit/test_metrics.py             ← the largest new suite; zero API calls
tests/unit/test_trend_analyzer.py
tests/unit/test_signals_cadence.py
tests/unit/test_fred_fetcher.py                                                          [P2]

MODIFIED
agent/utils/models.py                  ← 9 new dataclasses; Idea gains defaulted `entities`
agent/utils/config.py                  ← KnowledgeConfig/SignalsConfig/MacroConfig + parsers
agent/summarizer/claude_summarizer.py  ← {entity_section} placeholder; ENTITIES: line parsing
agent/runner.py                        ← record hook; _run_digest() extraction; maybe_run_signals; 5 flags
agent/digest/builder.py                ← _make_env() extraction + build_signals()
templates/digest.html.j2               ← theme block                                     [P3]
config/newsletters.yaml                ← three commented-out sections
requirements.txt                       ← anthropic >=0.60.0
.gitignore                             ← data/
.specify/memory/constitution.md        ← v1.1.0
CLAUDE.md                              ← statelessness claims corrected
```

**Structure Decision**: The existing package layout is kept — `agent/<concern>/` with a flat
`tests/`. Two new concerns get their own packages (`agent/knowledge/`, `agent/trends/`) because
they are genuinely new responsibilities rather than extensions of fetching, parsing,
summarization, or delivery. `FredFetcher` joins `agent/fetchers/` since it fetches, but does not
subclass `BaseFetcher`, whose contract returns `Email` objects.

## Phase 0: Research

See [research.md](research.md) — 22 decisions with rationale and rejected alternatives. The four
that most shape the implementation:

- **R-002** Entity extraction is folded into the existing `summarize_as_ideas` call rather than
  made separately: ~7× cheaper, because a separate call re-sends 4–8k input tokens per newsletter
  to recover context the model already had.
- **R-007/R-008** All trend arithmetic is pure Python; the brief is ranked and truncated to 40
  entities before the model sees it. Prompt size becomes a function of config, not of history.
- **R-010** Cadence is store-backed, not an APScheduler job. **Verified**: the deployed launchd
  job runs `python3 -m agent --once`, so the process exits after every run and a 3-day
  APScheduler interval could never fire.
- **R-014** Enabling `web_search` breaks `response.content[0].text` — the pattern used in three
  places today. `TrendAnalyzer` needs its own `_extract_text()`, `pause_turn` looping, and an
  `isinstance` guard for search errors that arrive as HTTP 200.

## Phase 1: Design

See [data-model.md](data-model.md), [contracts/](contracts/), and [quickstart.md](quickstart.md).

### Design Decisions

**1. SQLite, and the one constraint that matters**  
Seven tables. `UNIQUE(email_id, idea_index, entity_id)` on `observation` plus `INSERT OR IGNORE` is
the feature's most load-bearing schema line. `--preview` deliberately skips `move_to_trash`
([runner.py:223-229](../../agent/runner.py#L223-L229)), so the same emails are re-processed up to
six times a day. Without the constraint, one mention would register as six and the metrics layer
would report a fabricated 6× acceleration — a *confident false alarm*, which is worse than no
feature at all.

**2. Extraction folded into the existing prompt, gated by a placeholder**  
`_IDEA_SYSTEM_PROMPT_TEMPLATE` gains `{entity_section}`, rendering to `""` when the knowledge
layer is off. This is not cosmetic: `tests/unit/test_idea_format.py:43,46` assert on that
template directly, and a byte-identical disabled render is what keeps them green and makes SC-001
provable. Output is one delimited line per idea —
`ENTITIES: Nvidia (company, negative); export controls (policy, negative)` — not JSON, because
**this response is the user's digest**: a truncated delimited line loses one entity, a truncated
JSON object loses the entire batch of ideas.

**3. Metrics are pure; the model is downstream of every number**  
`agent/trends/metrics.py` has no I/O and no API calls. It computes velocity, acceleration,
z-score, `source_breadth`, new/fading flags, and new co-occurrence edges, then ranks and
truncates. `source_breadth` is the mechanical implementation of FR-014 and the single most
important field in the model — the difference between "five sources are worried" and "one author
has a hobby horse". `z_score` returns `None` below 8 daily buckets (FR-016); a z-score over three
points is theatre.

**4. Store-backed cadence, and the quiet-day gap**  
`store.job_due("signals_report", interval_days, now)` works identically under launchd and under
`DigestScheduler`. `mark_job_run` fires on **both success and failure** (FR-028), so a
persistently broken analysis does not retry every 4 hours and drain the budget.

> **Gap found during design.** `run()` returns early at
> [runner.py:71-73](../../agent/runner.py#L71-L73) when there are no unread emails. A
> `maybe_run_signals` call appended to the end of `run()` would silently never fire on quiet
> days — precisely when a trend report is most useful, because no digest is arriving either.
> Extract the digest body into `_run_digest()` and call `maybe_run_signals` in a `finally`, so
> neither an empty inbox nor a digest exception can suppress a due report. FR-026, SC-006.

**5. Everything degrades; nothing new can break the digest**  
`ObservationStore` never raises — any `sqlite3.Error` disables it and every method becomes a
no-op. `TrendAnalyzer` never raises — it returns an empty `SignalsReport` with `macro` still
populated, which is a valid deliverable artifact (FR-038, SC-009). `FredFetcher` never raises —
`None` when unconfigured, `partial=True` when some series fail. A disabled store is never
auto-deleted (FR-034): losing months of history to a transient disk error is not an acceptable
automatic recovery.

**6. Report template is a sibling, not a child**  
`digest.html.j2` is 385 lines built entirely around a `DigestBatch`; it shares a header and
footer with the Signals Report and nothing else. New `signals.html.j2` plus
`DigestBuilder.build_signals()`, with the Jinja environment extracted to `_make_env()` — an
extraction chosen specifically because `tests/test_digest_builder.py` patches
`jinja2.Environment.get_template` at class level across 13 methods, and that target must stay
valid. `EmailDelivery.send()` is already generic and is reused **unchanged**.

**7. Anti-hallucination validation is deterministic and free**  
Inside `_parse_response`, before a `SignalsReport` exists: drop any `SignalItem` naming an entity
absent from the brief (FR-019); downgrade evidence-free `HIGH` to `MEDIUM` (FR-020). An invented
entity is the failure most likely to destroy trust permanently — a report that says less is
recoverable, one that confidently names a company no newsletter mentioned is not.

**8. Config defaults are what make the existing suite inert**  
`tests/conftest.py::mock_config` constructs a **real** `AgentConfiguration`. Every new field must
default, and the three section objects default to `None`. That one decision makes every new code
path unreachable in 100% of existing tests. `FRED_API_KEY` must **not** join `_REQUIRED_ENV`
([config.py:18-26](../../agent/utils/config.py#L18-L26)) — that list raises on missing entries,
so adding it would stop an existing user's agent from starting (FR-035, SC-013).

**9. The preview harness is required scope**  
A fresh install has zero history, so without `scripts/signals_preview.py --synthesize 30` the
feature is invisible and un-iterable for a week. You cannot tune the trend prompt, verify the
metrics, or lay out the template against an empty store. FR-030, SC-011 — and it is also what
makes the implementation itself tractable.

### Implementation Order

**P1 — irreducible core, in dependency order.** `models.py` dataclasses → `canonicalize.py` →
`store.py` (schema, `record_summary`, `has_email`) → folded extraction + `_parse_ideas` extension
→ `runner.py` record hook → `metrics.py` → `analyzer.py` → `signals.html.j2` +
`build_signals()` → `job_due`/`mark_job_run` + the `_run_digest()` restructure → config sections
→ CLI flags → `signals_preview.py` → constitution amendment.

Pruning, `--store-stats`, `--rebuild-store`, and tier-3 alias adjudication are polish within P1
that can slip without the user noticing.

**P2 — macro half first.** `FredFetcher` + dashboard is purely additive and carries no API-shape
risk. Web search second, because it changes response parsing (R-014).

**P3 — after P1 is verified in production.** Clusters on P1's entities, which is why it is cheap
if P1 shipped and expensive if it did not.

### Test Trip-Wires

Ranked in [research.md](research.md#r-022-existing-test-trip-wires). Highest risk:
`tests/unit/test_idea_format.py:43,46` (prompt-regression asserts — safe only via the
`{entity_section}` → `""` placeholder) and `tests/conftest.py::mock_config` (a real
`AgentConfiguration`, so every new field needs a default).

**Run `pytest` from the repo root before writing any new code** to establish the green baseline.
Without it, there is no way to tell a pre-existing failure from one this feature introduced.

## Complexity Tracking

Not required — Constitution Check passed on both the pre-Phase-0 and post-Phase-1 evaluations
with no violations. The one governance action needed is the v1.1.0 amendment described above,
which is a planned amendment rather than a violation to be justified.
