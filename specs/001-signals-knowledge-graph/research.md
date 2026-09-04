# Research: Signals Report — Persistent Knowledge Layer and Trend-Based Early Warning

**Feature**: 001-signals-knowledge-graph | **Date**: 2026-09-03

## Resolved Questions

All unknowns were resolved through direct codebase exploration plus verification of the
deployed launchd job. No item remains marked NEEDS CLARIFICATION.

---

### R-001: Storage Substrate

**Decision**: SQLite via the stdlib `sqlite3` module, one file at `data/signals.db`.

**Rationale**: Every access pattern this feature needs is a *windowed aggregate query* —
"count observations for entity X between date A and date B, grouped by sender". That is the
single thing an append-only log is worst at. SQLite adds no third-party dependency: it stands
in exactly the same relation to the project as `smtplib`, which the Tech Stack table already
blesses as stdlib. It gives transactional writes, a `UNIQUE` constraint for idempotency
(FR-006), cheap pruning (FR-009), and index-backed windowed counts for free.

**Alternatives considered**:
- *JSONL append-only log* — rejected. Pruning, alias merges, and dedup all require reading and
  rewriting the entire file. Idempotency would need an in-memory seen-set rebuilt on every run.
- *No persistence, recompute from Gmail* — impossible. `runner.py` calls `move_to_trash` on
  every delivered source email; the history is destroyed by design.
- *DuckDB / a server database* — rejected. New dependency, new operational surface, for a
  dataset that will hold tens of thousands of rows.

---

### R-002: Where Entity Extraction Happens

**Decision**: Fold extraction into the existing `summarize_as_ideas` call by appending one
`ENTITIES:` line per idea to the prompt's output contract. No second model call.

**Rationale**: This is the highest-leverage cost decision in the feature. A separate extraction
call must re-transmit 4–8k input tokens of newsletter text per newsletter to recover information
the model already had in context one call earlier.

| Approach | Marginal cost/newsletter | ~Monthly (realistic volume) | At configured cap |
|---|---|---|---|
| Separate extraction call | ~6k input + ~300 output | ~$5.40 | ~$65 |
| Folded into existing call | ~300 output only | ~$0.80 | ~$8 |

Roughly **7× cheaper**, and it removes an entire failure mode: there is no second call to
retry, rate-limit, or have partially succeed. Constitution I is not violated — that principle
governs external API calls going through dedicated client classes rather than being made
inline, and this call stays inside `ClaudeSummarizer`, which is that class.

**Alternatives considered**:
- *Separate `EntityExtractor` client class* — rejected on the cost table above. Cleaner on
  paper; the cleanliness buys nothing the folded version lacks.
- *Local NER (spaCy)* — rejected. New heavy dependency, and it cannot produce the
  positive/negative framing that FR-002 requires, which is the half that makes a trend
  interpretable.

---

### R-003: Extraction Output Format

**Decision**: A single delimited line appended after each idea body:

```
IDEA: Nvidia Faces New Export Limits
Washington extended chip export controls to two more jurisdictions...
ENTITIES: Nvidia (company, negative); export controls (policy, negative); China (country, neutral)
```

**Rationale**: Delimited, not JSON — and this is not a style preference. **This response is the
user's digest.** If the model truncates or malforms JSON, a JSON parse takes the whole batch of
ideas down with it. With line-delimited output, a truncated response loses one entity from one
idea and the digest still ships. It also matches the existing `IDEA:` convention exactly, so
`_parse_ideas` gains a sibling parser rather than a new paradigm.

**Alternatives considered**: JSON output — rejected on the blast-radius argument above. Tool-use
/ structured output — rejected; adds a round trip and forces the digest call to depend on a
schema the digest itself does not need.

---

### R-004: Entity Canonicalization

**Decision**: Three tiers, all stdlib.

1. **Deterministic** `normalize_key()` — NFKD fold, casefold, strip possessives, strip corporate
   suffixes (`Inc`, `Corp`, `Ltd`, `PLC`, `NV`, `SA`, `AG`, `Co`). Resolves
   `Nvidia` ≡ `NVIDIA Corp.` ≡ `Nvidia's`.
2. **Alias table**, seeded from `user_profile.yaml` portfolio and watchlist entries. Resolves
   `UAL` ≡ `United Airlines` — a ticker/name pair no string algorithm can bridge.
3. **Adjudicated near-duplicates** — `difflib.SequenceMatcher` proposes candidate pairs above a
   ratio threshold; they are appended to the trend-analysis call, which is already running, and
   confirmed merges are written to the alias table.

**Rationale**: Failing to canonicalize is the quiet way this feature dies: a single real trend
splits three ways across spellings, each fragment falls below the FR-014 threshold, and the
report goes empty while the store is full. Tier 1 catches most of it deterministically at zero
cost. Tier 3 rides an existing call, so it adds no new API surface.

**Alternatives considered**: Embedding similarity — rejected, new dependency and a vector store
for a problem three stdlib tiers solve. Asking the model to canonicalize at extraction time —
rejected, it has no cross-newsletter view at that point.

---

### R-005: Idempotency

**Decision**: `UNIQUE(email_id, idea_index, entity_id)` on the `observation` table, all writes
via `INSERT OR IGNORE`, plus a `has_email(email_id)` short-circuit that skips the write path
entirely for an already-recorded email.

**Rationale**: `--preview` delivers the digest but deliberately skips `move_to_trash`
([runner.py:223-229](../../agent/runner.py#L223-L229)), so the same emails are re-processed on
every 4-hour poll — up to six times a day. Without the constraint, one newsletter mentioning an
entity once would register as six mentions, and the metrics layer would report a fabricated
6× acceleration. The failure is worse than a missing feature: it is a *confident false alarm*,
which is precisely what FR-014 and FR-019 exist to prevent.

**Alternatives considered**: Skipping writes under `--preview` — rejected; preview is how the
user actually runs the agent during evaluation, and it would leave the store empty exactly when
they are trying to assess the feature.

---

### R-006: Co-occurrence Scope

**Decision**: Record co-occurrence at **idea** granularity, not email granularity.

**Rationale**: Email-scoped co-occurrence would link the Federal Reserve to a crypto story
because both appeared in the same Monday newsletter. That is not a relationship; that is a
shared inbox. Idea-scoped edges mean two entities are linked only when one 1–3 sentence claim
concerned both — which is what makes FR-013 ("newly-formed relationships") a meaningful signal
rather than noise.

---

### R-007: Where the Trend Math Lives

**Decision**: A pure module `agent/trends/metrics.py` computes everything numeric. The model
receives only computed movements and is asked exclusively for interpretation.

Computed per entity: current-window count, prior-window count, delta, velocity (rate of change),
`source_breadth` (count of distinct senders), z-score against that entity's own daily history,
`is_new`, `is_fading`. Plus new co-occurrence edges for the window.

**Rationale**: This is the spec's central non-negotiable (FR-010). A language model asked to
count occurrences across a long list will produce plausible numbers that are wrong, and the
wrongness is undetectable in the output. Pure-Python metrics are also unit-testable with zero
API calls, which is what makes the whole feature cheap to iterate on.

`source_breadth` is the single most important field: it is the mechanical implementation of
FR-014, and the difference between "five newsletters are worried" and "one author has a hobby
horse".

**Guard**: return `z_score = None` when fewer than 8 daily buckets exist — a z-score over 3 data
points is theatre, and FR-016 forbids presenting it.

---

### R-008: Keeping Prompt Size Flat as History Grows

**Decision**: `metrics.compute_brief()` ranks all eligible entities by a composite salience
score and truncates to `max_entities_in_prompt` (default 40) before anything reaches the model.

**Rationale**: This makes prompt size **O(config), not O(history)** — stable at ~3–5k tokens
whether the store holds 300 observations or 300,000. It is what makes FR-053 and SC-005 true,
and it is the reason the feature's cost does not grow over the years it runs. It also happens to
improve output quality: 40 ranked movements produce sharper analysis than 4,000 unranked ones.

---

### R-009: Analysis Model Selection

**Decision**: `claude-opus-5` for `TrendAnalyzer`. `claude-sonnet-4-6` stays everywhere else.

**Rationale**: This is one call every few days over a small, dense, pre-computed brief —
roughly $1.50/month. It is also the only genuinely reasoning-critical call in the system: every
other call summarizes text that is already in front of it, whereas this one must infer causal
mechanism and second-order consequence from bare numbers. Economizing here would degrade the
one output the feature exists to produce, to save about a dollar a month.

---

### R-010: Report Cadence Mechanism

**Decision**: Store-backed cron. A `job_run` table records the last run per job name;
`NewsletterAgent.maybe_run_signals(now)` consults `store.job_due("signals_report",
interval_days, now)`.

**Rationale — this was verified, not assumed.** The deployed launchd job
(`com.newsletter-digest-agent.plist`, gitignored) has `ProgramArguments` of
`python3 -m agent --once` with `StartInterval 14400`. **The process exits after every run.**
An APScheduler job with a 3-day interval would therefore never fire in production — the
scheduler would be torn down 20 seconds after being constructed, 18 times before the interval
elapsed. `DigestScheduler` is effectively dead code in the real deployment.

Store-backed cadence works identically under launchd and under `DigestScheduler`, satisfying
FR-027 without caring which one is running.

`mark_job_run` is called on **both success and failure** (FR-028). A persistently broken
signals job that reset only on success would retry every 4 hours and burn the user's budget on
a call that cannot succeed.

**Alternatives considered**: A second `scheduler.add_job(...)` — rejected on the evidence above,
and it would additionally break `tests/test_scheduler.py:13-34`, which asserts on
`add_job.call_args` (the *last* call).

---

### R-011: The Quiet-Day Gap

**Decision**: Restructure the early return at
[runner.py:71-73](../../agent/runner.py#L71-L73) so the signals due-check runs on the
no-emails path.

**Rationale**: `run()` currently does:

```python
if not emails:
    log.info("poll_complete_no_emails")
    return
```

A `maybe_run_signals` call appended to the end of `run()` would silently never fire on days
with no unread newsletters — and those quiet stretches are exactly when a trend report is most
useful, because there is no daily digest arriving to inform the reader. This is FR-026 and
SC-006. Implement by extracting the digest body into `_run_digest()` and calling
`maybe_run_signals` in a `finally`, so a digest exception also cannot suppress the report.

---

### R-012: Macroeconomic Data Source

**Decision**: FRED (Federal Reserve Economic Data), free API key, ~15 series.

| Fear from the spec | Series |
|---|---|
| Recession | `T10Y3M`, `T10Y2Y`, `SAHMREALTIME`, `ICSA`, `UNRATE` |
| Currency crash | `DTWEXBGS` (broad dollar), `DEXINUS` |
| Economic headwinds | `BAMLH0A0HYM2` (HY credit spread), `NFCI`, `T5YIFR`, `DFF`, `DCOILWTICO`, `VIXCLS`, `MORTGAGE30US` |

**Rationale**: FRED is the only free source covering all three of the user's stated fears in one
schema behind one key. `BAMLH0A0HYM2` deserves particular note: high-yield credit spreads are
the best single early-warning indicator of financial stress and typically move before equities.

Alarm thresholds live in a module-level table as **domain knowledge, not user preference** —
a user should not have to know that a 10y-3m spread below zero is the inversion signal.

**Alternatives considered**: Paid market-data APIs — rejected, cost and key management for data
FRED already has. Yahoo Finance scraping — rejected, unofficial and fragile.

---

### R-013: HTTP Client for FRED

**Decision**: stdlib `urllib.request`.

**Rationale**: 15 unauthenticated GETs to a single host, twice a week. That needs no connection
pooling, no async, no HTTP/2. Adding `httpx` or `requests` would introduce the project's **first
general-purpose HTTP dependency**, which would require a Constitution Tech Stack amendment to
justify — a large governance cost for zero functional gain. Cache to `data/macro_cache.json`
with a 12-hour TTL, written via atomic `os.replace`.

---

### R-014: Web Search Integration — Three Things That Break

**Decision**: Use the Anthropic server-side `web_search` tool
(`web_search_20260209`), `max_uses` bound from config. `anthropic` 0.84.0 is installed;
`requirements.txt` must be raised from `>=0.40.0` to `>=0.60.0`.

Three failure modes must be handled explicitly, because the naive implementation is subtly
broken rather than obviously broken:

1. **`response.content[0].text` stops working.** The pattern used at
   [analyzer.py:145](../../agent/advisor/analyzer.py#L145) and
   [claude_summarizer.py:175,251](../../agent/summarizer/claude_summarizer.py#L175) assumes
   block 0 is text. With a server tool enabled, responses lead with tool-use and tool-result
   blocks. Requires an `_extract_text()` helper that iterates and concatenates blocks where
   `block.type == "text"`. **This helper must be local to `TrendAnalyzer`** — changing the
   shared pattern would break `_make_api_response` in the existing tests.
2. **`stop_reason == "pause_turn"`** must be looped on, appending the response content and
   re-calling. Bound at 3 continuations so a pathological search loop cannot run away.
3. **Search errors return HTTP 200** with an error *object* where a *list* is expected. Branch
   on `isinstance(block.content, list)` before iterating, or a failed search raises a
   `TypeError` deep inside result parsing.

**Constitution IV**: `TrendAnalyzer` constructs its own `TokenBucketLimiter` and acquires before
each call *including continuations*. `AdvisorAnalyzer` currently skips rate limiting; with
`pause_turn` continuations a single logical analysis can become 4 API calls, so the principle
genuinely bites here.

---

### R-015: Report Template Strategy

**Decision**: A new sibling template `templates/signals.html.j2` and a new method
`DigestBuilder.build_signals()`. Extract the shared Jinja environment construction into
`_make_env()`. Do **not** use template inheritance from `digest.html.j2`, and do **not**
parameterize `build()`'s template name.

**Rationale**: `digest.html.j2` is 385 lines of table-based email HTML built entirely around a
`DigestBatch`. The Signals Report shares a header and a footer with it and nothing else.
Inheritance would force a base template whose blocks are mostly empty in one child or the other.
Parameterizing `build()` is worse: its render kwargs (`total_found`, `failed_subjects`,
`batch_index`) are digest-specific and meaningless to a report.

**Test constraint**: `tests/test_digest_builder.py` (13 methods) patches
`jinja2.Environment.get_template` at **class** level. Extracting `_make_env()` keeps that patch
target valid; replacing Jinja's loader or constructing the environment differently would break
all 13.

`EmailDelivery.send(html_body, subject, config)` is already fully generic and is reused
**unchanged**.

---

### R-016: Configuration Shape

**Decision**: Three optional top-level sections in `config/newsletters.yaml` —
`knowledge_graph:`, `signals:`, `macro:` — following the `user_profile` precedent at
[config.py:270-277](../../agent/utils/config.py#L270-L277): absent means disabled.

**Rationale — the hard constraint**: `tests/conftest.py::mock_config` constructs a **real**
`AgentConfiguration` with a fixed set of kwargs. Every new field must therefore have a default,
and the three section objects must default to `None`. That single decision makes every new code
path inert in 100% of the existing test suite, which is what makes SC-001 provable rather than
hoped for.

**`FRED_API_KEY` must NOT be added to `_REQUIRED_ENV`** ([config.py:18-26](../../agent/utils/config.py#L18-L26)).
That list raises `ConfigurationError` on any missing entry, so adding it would mean an existing
user who pulls this change finds their agent refusing to start. That is FR-035 and SC-013.

Parser helpers import the logger **locally inside the function**, matching the existing
convention at [config.py:265](../../agent/utils/config.py#L265) that exists to dodge an import
cycle.

`.gitignore` gains `data/`.

---

### R-017: Anti-Hallucination Validation

**Decision**: Validate inside `_parse_response`, before a `SignalsReport` is ever constructed.

- Drop any `SignalItem` naming an entity absent from the `TrendBrief` (FR-019).
- Downgrade `HIGH` confidence to `MEDIUM` when the item carries no evidence or citation (FR-020).
- Render `z_score` only when non-`None` (FR-016).

**Rationale**: An invented entity is the single failure most likely to destroy the reader's
trust in this feature permanently. A report that says less is recoverable; a report that
confidently names a company that no newsletter mentioned is not. The validator is deterministic
Python and costs nothing.

---

### R-018: Retention and Pruning

**Decision**: Prune raw `observation` rows older than `retention_days` (default 180). Maintain
an `entity_daily` rollup table that is never pruned.

**Rationale**: Claim text is what ages; trend shape is what the reader wants over long horizons.
Keeping the rollup means a two-year-old seasonal pattern is still visible after the underlying
sentences are gone, at a few bytes per entity per day.

---

### R-019: Developer Preview Harness

**Decision**: `scripts/signals_preview.py` is **required scope, not a nice-to-have**, with
`--synthesize N` (generate N days of plausible fake observations), `--no-llm` (render from
metrics alone), and `--open`. Writes to a scratch database, never to `data/signals.db`.

**Rationale**: A fresh install has zero history. Without synthesis the entire feature is
invisible and un-iterable for a week or more — you cannot tune the trend prompt, verify the
metrics, or lay out the template against an empty store. This is FR-030 and SC-011, and it is
also what makes the implementation itself tractable. `scripts/` is exempt from the `print()`
prohibition; the existing `scripts/test_pipeline.py` establishes that precedent.

---

### R-020: P3 Clustering Approach

**Decision**: Cluster the batch's ideas by shared canonical entities from P1's extraction, then
send one merge call per cluster. Require ≥2 **distinct senders** for a cluster to become a theme.

**Rationale**: This is why the P1→P3 ordering matters. With P1's entities already attached to
every idea, clustering is a set-intersection over data that already exists — nearly free. Without
it, P3 would need its own embedding or classification pass over every idea, which is the
expensive version of the same feature.

The distinct-sender requirement (FR-049) is the same principle as FR-014: one author making the
same point in three ideas is not corroboration and must not be presented as a merged theme.

---

### R-021: Constitution Amendment

**Decision**: Amend to **v1.1.0** as part of P1, not as follow-up cleanup.

- Tech Stack gains `| Persistence | sqlite3 (stdlib) |` and `| Macro data | FRED API via urllib (stdlib) |`.
- Principle II extended: "Operational state lives in `data/`, is gitignored, and its absence must never fail a run."
- `CLAUDE.md` asserts "No persistent database; stateless per-run" in three places; all three become false.

**Rationale**: Governance requires amendments carry a rationale note. Leaving this undone means
every subsequent `/speckit.analyze` flags the feature as a constitution violation, and the next
person reading `CLAUDE.md` is told the system is stateless when it is not. MINOR bump, not
MAJOR: this adds to the Tech Stack and broadens a principle; it revokes nothing.

---

### R-022: Existing-Test Trip-Wires

Ranked by likelihood of being tripped:

1. `tests/unit/test_idea_format.py:43,46` assert on `_IDEA_SYSTEM_PROMPT_TEMPLATE` directly.
   Safe **only** via an `{entity_section}` placeholder that renders to `""` when disabled. Add a
   matching guard test asserting byte-identity of the disabled render.
2. `tests/unit/test_idea_format.py:51-60` — `_parse_ideas` on input with no `ENTITIES:` line must
   still yield identical titles and bodies plus `entities=()`.
3. `tests/test_digest_builder.py` — patches `jinja2.Environment.get_template` at class level; the
   `_make_env()` extraction must keep that target valid (R-015).
4. `tests/test_scheduler.py:13-34` — asserts on the last `add_job` call. Avoided entirely by
   store-backed cadence (R-010); only bites if someone adds a second `add_job`.
5. `tests/conftest.py::mock_config` is a real `AgentConfiguration` — every new field needs a
   default (R-016).

**House test style to match**: tests live in `tests/unit/`; `pytest-mock` with
`mocker.patch("anthropic.Anthropic", ...)` at **package** level; module-level `_make_*`
factories rather than fixtures; plain `Test<Unit>` namespace classes; **no `@pytest.mark.parametrize`
anywhere in this repository** — do not introduce it.
