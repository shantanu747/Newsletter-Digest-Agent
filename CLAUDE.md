# Newsletter-Digest-Agent Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-09

## Active Technologies
- `token.json` stores OAuth refresh token. `config/newsletters.yaml` stores non-secret configuration. As of `001-signals-knowledge-graph`, a local SQLite store at `data/signals.db` adds the project's first persistent state — see below; still stateless per-run otherwise. (001-newsletter-digest-agent)
- Python 3.11+ + `anthropic` SDK, `google-api-python-client` + OAuth 2.0, `beautifulsoup4` + `html2text`, `APScheduler`, `Jinja2`, `PyYAML` + `python-dotenv`, `structlog`, `smtplib` (stdlib) (001-digest-agent-enhancements)
- Files — `token.json` (OAuth), `config/newsletters.yaml` (config), plus `data/signals.db` (SQLite, added by `001-signals-knowledge-graph`). (001-digest-agent-enhancements)
- Python 3.11+ + `anthropic` SDK, `Jinja2`, `PyYAML`, `structlog`, `pytest` + `pytest-mock` (001-idea-digest-format)
- Files only — `config/newsletters.yaml` (format toggle), `config/user_profile.yaml` (relevance signals). No schema migrations. (001-idea-digest-format)
- Python 3.11+ + `anthropic` SDK (raise `requirements.txt` from `>=0.40.0` to `>=0.60.0` for the `web_search` server tool), `Jinja2`, `PyYAML`, `structlog`, `pytest` + `pytest-mock`. **No new third-party dependencies.** (001-signals-knowledge-graph)
- SQLite via stdlib `sqlite3` at `data/signals.db` — the project's first persistent state. Macro responses cached to `data/macro_cache.json`. Both gitignored. (001-signals-knowledge-graph)

- Python 3.11+ + `anthropic` SDK, `google-api-python-client` + OAuth 2.0, `beautifulsoup4`, `html2text`, `APScheduler`, `PyYAML`, `python-dotenv`, `structlog`, `Jinja2`, `pytest`, `pytest-mock`, `smtplib` (stdlib) (001-newsletter-digest-agent)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes
- 003-digest-store-context: Daily digest memory — added `EntityContext` dataclass and `entity_context` field on `DigestBatch`, `ObservationStore.recent_context()` window query (one query per batch, chunked IN-clause, alias-aware, never raises), `agent/knowledge/context.py` helpers (7-day window, 3-mentions/2-senders thresholds, `badge_for_idea`, `recurring_lines`), advisor `RECURRING THIS WEEK` prompt block, `Recurring · …` badge line under qualifying idea titles, store opened for reads in `--dry-run` (recording stays gated). No new config keys, no new dependencies.
- 002-theme-synthesis: Cross-newsletter theme synthesis (P3) — added `Theme` dataclass and `themes` field to `DigestBatch`, `knowledge_graph.synthesis_enabled` config flag, `agent/trends/synthesis.py` with `cluster_ideas()` (union-find on shared entities ≥2, ≥2 senders required) and `ThemeSynthesizer` (one Claude call per cluster, retry/backoff, never raises), runner hook after summarization with dry-run preview, builder computes absorbed idea lookup, template renders "Today's Themes" block with source attribution and disagreement lines, absorbed ideas hidden from per-newsletter sections with "Covered in" note. All behind flag, default off. No new dependencies.
- 001-model-upgrade-sonnet-5: Upgraded per-newsletter summarization and the daily advisor section to `claude-sonnet-5` (configurable via the new top-level `model` config key; `signals.model` stays separate), fixed `ClaudeSummarizer` to receive `knowledge_config` from the runner so entity extraction actually runs, added a shared `agent/utils/anthropic_text.py::extract_text` helper so responses are read safely when thinking/tool blocks precede the text block, and added rate limiting to `AdvisorAnalyzer`. No new dependencies.
- 001-signals-knowledge-graph: Added Python 3.11+ + `anthropic` SDK (raise `requirements.txt` from `>=0.40.0` to `>=0.60.0` for the `web_search` server tool), `Jinja2`, `PyYAML`, `structlog`, `pytest` + `pytest-mock`. **No new third-party dependencies.**
- 001-recall-integration: Prompt-only change to `agent/summarizer/claude_summarizer.py` — removes interest-based suppression gate from idea-based digest format; no new dependencies or storage
- 001-idea-digest-format: Added Python 3.11+ + `anthropic` SDK, `Jinja2`, `PyYAML`, `structlog`, `pytest` + `pytest-mock`


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
