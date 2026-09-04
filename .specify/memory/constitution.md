# Newsletter Digest Agent Constitution

## Core Principles

### I. Separation of Concerns
All external API calls go through dedicated fetcher/client classes — never inline. Each component (fetching, parsing, summarizing, delivery) is independently unit-testable with mocked dependencies.

### II. Secrets Management
Secrets only from environment variables via `python-dotenv`, never hardcoded. Non-secret configuration lives in `config/newsletters.yaml`. Operational state lives in `data/`, is gitignored, and its absence must never fail a run.

### III. Typed Data Transfer
Use dataclasses for all inter-module data transfer (`Email`, `Summary`, `DigestEntry`). Follow PEP 8; use type hints on all public function signatures.

### IV. Reliability & Rate Limiting
Rate limiting must be applied before every Anthropic API call. Implement exponential backoff for all external API failures. Log every agent run start, each newsletter processed, and delivery status.

### V. Observability
No `print()` statements in production code — use `structlog` logger exclusively. Structured JSON logs make agent run history and failures easy to debug.

## Tech Stack

| Layer | Library |
|---|---|
| Language | Python 3.11+ |
| Gmail fetching | `google-api-python-client` + OAuth 2.0 |
| HTML parsing | `beautifulsoup4` + `html2text` |
| AI summarization | `anthropic` SDK |
| Email delivery | `smtplib` (stdlib) |
| Scheduling | `APScheduler` |
| Digest templates | `Jinja2` |
| Config | `PyYAML` + `python-dotenv` |
| Logging | `structlog` |
| Testing | `pytest` + `pytest-mock` |
| Persistence | sqlite3 (stdlib) |
| Macro data | FRED API via urllib (stdlib) |

## Development Workflow

This project uses spec-kit for Specification-Driven Development:
- `/speckit.specify` — define or update the specification before writing any code
- `/speckit.plan` — generate a phased technical plan from the spec
- `/speckit.tasks` — derive an ordered task list for the current phase
- `/speckit.implement` — implement against the tasks

Run `/speckit.specify` first whenever returning to the project after a break.

## Governance

This constitution supersedes all other practices. All code changes must comply with the principles above. Amendments require updating this file with a rationale note.

### Amendment History

- **v1.1.0** (2026-09-03): Added `Persistence` (sqlite3) and `Macro data` (FRED API via urllib)
  rows to the Tech Stack table, and extended Principle II to cover operational state in `data/`.
  Rationale: `001-signals-knowledge-graph` introduces the project's first persistent state (a
  local SQLite store at `data/signals.db`, cached FRED responses at `data/macro_cache.json`).
  MINOR bump — this adds to the stack and broadens a principle; it revokes nothing.

**Version**: 1.1.0 | **Ratified**: 2026-03-08 | **Last Amended**: 2026-09-03
