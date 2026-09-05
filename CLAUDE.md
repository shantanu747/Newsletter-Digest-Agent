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
- 001-signals-knowledge-graph: Added Python 3.11+ + `anthropic` SDK (raise `requirements.txt` from `>=0.40.0` to `>=0.60.0` for the `web_search` server tool), `Jinja2`, `PyYAML`, `structlog`, `pytest` + `pytest-mock`. **No new third-party dependencies.**
- 001-recall-integration: Prompt-only change to `agent/summarizer/claude_summarizer.py` — removes interest-based suppression gate from idea-based digest format; no new dependencies or storage
- 001-idea-digest-format: Added Python 3.11+ + `anthropic` SDK, `Jinja2`, `PyYAML`, `structlog`, `pytest` + `pytest-mock`


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
