# Implementation Plans — Advisor Upgrade Series


Four plans, implemented **in order**, each on its own branch cut from `main` after the previous
plan's branch has merged. Each plan is self-contained: it names its branch, lists every file it
touches, gives function signatures, and specifies the tests that prove it works.

| # | Plan | Branch | Depends on |
|---|------|--------|------------|
| 1 | [Model upgrade + knowledge-extraction wiring fix](01-model-upgrade.md) | `001-model-upgrade-sonnet-5` | — |
| 2 | [Cross-newsletter theme synthesis (P3)](02-theme-synthesis.md) | `001-theme-synthesis` | 1 |
| 3 | [Digest store context + recurring badge](03-digest-store-context.md) | `001-digest-store-context` | 1, 2 |
| 4 | [Signals track record (calls scored against price + mentions)](04-signals-track-record.md) | `001-signals-track-record` | 1, 3 |

## Why this series exists

The agent's job is to be an avid reader with sharp observation and analytical skill who surfaces
insights to act upon and cuts noise. It already has memory (`data/signals.db`) and trend analysis
(the Signals Report). What it does **not** yet do:

1. Read a story once when four newsletters cover it (plan 2).
2. Use its memory while writing the *daily* digest — today the advisor only sees today's summaries (plan 3).
3. Remember what it told you and check whether it was right (plan 4).

Plan 1 is a prerequisite: the per-newsletter calls run a previous-generation model, and a wiring
bug means entity extraction never actually runs in production, so the store stays empty.

## Decisions already made (do not re-litigate; ask the user if one blocks you)

These were settled with the user before the plans were written.

| Topic | Decision |
|---|---|
| Model for summarizer / advisor / grading script | `claude-sonnet-5` (cheaper and stronger than `claude-sonnet-4-6`). Signals Report stays on `claude-opus-5` via `signals.model`. |
| Calls tracked in the track record | Signals Report items only (RISKS/OPPORTUNITIES/EMERGING/FADING/WATCH). Daily BUY/SELL/WATCH free-text lines are **not** tracked. |
| How "played out" is judged | Price change (Stooq daily CSV via stdlib `urllib`) **and** subsequent mention/sentiment activity from the store. Numbers are computed in code; Claude only writes 1–2 sentences of interpretation. |
| Entity → ticker mapping | Profile tickers only (`config/user_profile.yaml` portfolio + watchlist). Entities that don't map to a profile ticker get the mention-based retrospective without a price. |
| Where the retrospective renders | A "Track Record" section at the top of the Signals Report, at fixed horizons of 7 and 30 days after the call. Not in the daily digest. |
| Features "advisor gets store context" and "trending badge" | Merged into one plan (plan 3) sharing one store query. |
| Order | 1 → 2 → 3 → 4 as tabled above. |

## Conventions every plan follows

**Repository rules (from `.specify/memory/constitution.md`)**
- External API calls only inside dedicated client classes. Rate limiter (`TokenBucketLimiter.acquire()`) **before every** Anthropic call, exponential backoff on failure.
- Dataclasses for all inter-module data (`agent/utils/models.py`), frozen, type-hinted.
- `structlog` via `agent.utils.logger.get_logger` — no `print()` in production code (the `--dry-run` console output in `runner.py` is the one sanctioned exception).
- `ObservationStore` **never raises**. Every new public method is wrapped in `@_guarded(default=...)`.
- Secrets only from `.env`; operational state only under `data/` (gitignored); absence of `data/` must never fail a run.
- **No new third-party dependencies.** Plan 4's price fetch uses `urllib` + `csv` from the stdlib.

**Config rules**
- Any new YAML key must be added to the matching `_KNOWN_*_KEYS` set in `agent/utils/config.py`, or `load_config` raises `ConfigurationError` on it.
- New behavior defaults to whatever keeps the current output unchanged unless the plan says otherwise.
- Never edit `config/user_profile.yaml` (gitignored, contains real holdings). Tests construct `UserProfile` directly.

**Testing rules**
- Baseline before you start: `.venv/bin/python -m pytest -q -m "not integration"` → **274 passed** on `main` at commit `a886fe1`. It must stay green plus your additions.
- Zero real API or network calls in tests. Mock `anthropic.Anthropic` (`mocker.patch("anthropic.Anthropic", return_value=mock_client)`) and, after plan 1, build response mocks as `MagicMock(type="text", text=...)` content blocks.
- Store tests use a real SQLite file under `tmp_path` — do not mock `sqlite3`.
- Test names describe behavior (`test_three_ideas_from_one_sender_do_not_cluster`), grouped in classes by unit.
- `ruff check` has **42 pre-existing errors**, all in `tests/` and `scripts/` (unused imports etc.). Rule: `ruff check agent/` must be clean, and every file you touch must be clean. Do not fix unrelated lint in files you didn't otherwise change.

**Style rules**
- Readable over clever. Module-level constants for thresholds, promoted to config only when a plan says so.
- Docstrings on every public function; a one-paragraph module docstring saying what the module is for and what it deliberately does not do.
- Follow existing patterns: the retry loop shape in `agent/trends/analyzer.py::TrendAnalyzer.analyze`, the `_guarded` decorator in the store, the delimiter-section output format for Claude responses.

**Process rules**
- Read the plan fully, then read every file it names, before editing.
- Implement in the step order given; each step ends with a runnable test suite.
- Commit per step using the repo's conventional-commit style (`feat(trends): …`, `fix(runner): …`, `test(store): …`).
- Finish with the plan's acceptance checklist; do not open a PR with unchecked boxes.
- If something in a plan contradicts what you find in the code, stop and ask rather than guess.
