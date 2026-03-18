# Implementation Plan: Newsletter Digest Agent

**Branch**: `001-newsletter-digest-agent` | **Date**: 2026-03-09 | **Spec**: `specs/001-newsletter-digest-agent/spec.md`
**Input**: Feature specification from `/specs/001-newsletter-digest-agent/spec.md`

---

## Summary

An AI-powered Python agent that connects to Gmail via OAuth 2.0, filters newsletter emails by sender allowlist and subject keywords, extracts and cleans HTML content using BeautifulSoup4 + html2text, generates 200–250 word summaries via the Anthropic API (claude-sonnet-4-6), assembles a Jinja2-rendered HTML digest, and delivers it to the user's inbox via SMTP — with rate limiting, exponential backoff retry, optional `--dry-run` mode, and APScheduler-based daily scheduling.

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: `anthropic` SDK, `google-api-python-client` + OAuth 2.0, `beautifulsoup4`, `html2text`, `APScheduler`, `PyYAML`, `python-dotenv`, `structlog`, `Jinja2`
**Storage**: No persistent database; stateless per-run. `token.json` stores OAuth refresh token. `config/newsletters.yaml` stores non-secret configuration.
**Testing**: `pytest` + `pytest-mock`; all external dependencies mocked at class boundary; integration tests skipped in CI
**Target Platform**: macOS/Linux (Python process, foreground or terminal multiplexer)
**Project Type**: CLI agent / scheduled daemon
**Performance Goals**: Process 20 newsletters (fetch → extract → summarize → deliver) in under 15 minutes; digest delivered within 10 minutes of schedule trigger
**Constraints**: Rate limit Anthropic API calls to 1 req/2s; truncate newsletter content to 8,000 chars to avoid context overflow; cap runs at 20 newsletters
**Scale/Scope**: Single-user personal agent; daily batch of up to 20 newsletters

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|-----------|-------|--------|
| I. Separation of Concerns | All external calls through dedicated classes (GmailFetcher, ClaudeSummarizer, EmailDelivery). Each stage independently unit-testable. | PASS |
| II. Secrets Management | All secrets via `python-dotenv` env vars. YAML for non-secret config. `credentials.json` / `token.json` gitignored. | PASS |
| III. Typed Data Transfer | `Email`, `Summary`, `DigestEntry` dataclasses in `agent/utils/models.py`. No raw dicts across module boundaries. Type hints on all public signatures. | PASS |
| IV. Reliability & Rate Limiting | Token bucket rate limiter before every Anthropic API call. Exponential backoff (3 attempts, base=1s, jitter). Every run start, newsletter processed, and delivery status logged. | PASS |
| V. Observability | `structlog` JSON logger used exclusively. No `print()` in production code (dry-run output excepted — it's intentional user-facing output). | PASS |

**Constitution Check Result**: PASS — no violations. Complexity Tracking table not needed.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-newsletter-digest-agent/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output — all 10 decisions resolved
├── data-model.md        # Phase 1 output — Email, Summary, DigestEntry, AgentConfiguration
├── quickstart.md        # Phase 1 output — setup, auth, dry-run, scheduler
├── contracts/           # Phase 1 output — CLI schema, config schema, data classes
│   ├── cli.md
│   ├── config-schema.md
│   └── data-classes.md
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
agent/
├── __init__.py
├── __main__.py
├── runner.py               # CLI entry point + orchestrator (NewsletterAgent, main())
├── scheduler.py            # APScheduler BlockingScheduler wrapper
├── fetchers/
│   ├── __init__.py
│   ├── base_fetcher.py     # Abstract base class (BaseFetcher)
│   └── gmail_fetcher.py    # Gmail API integration with OAuth 2.0
├── parsers/
│   ├── __init__.py
│   └── email_parser.py     # BS4 + html2text HTML extraction pipeline
├── summarizer/
│   ├── __init__.py
│   └── claude_summarizer.py  # Anthropic API calls + rate limiter + retry
├── digest/
│   ├── __init__.py
│   ├── builder.py          # Jinja2 HTML digest assembly
│   └── delivery.py         # smtplib STARTTLS email delivery
└── utils/
    ├── __init__.py
    ├── config.py            # YAML + env var loader → AgentConfiguration
    ├── models.py            # Email, Summary, DigestEntry, EmailLink dataclasses
    ├── rate_limiter.py      # Token bucket (threading.Lock)
    ├── logger.py            # structlog configuration
    ├── exceptions.py        # ConfigurationError, FetchError, SummarizationError, DeliveryError
    └── eml_loader.py        # Local .eml fixture loader for tests

config/
└── newsletters.yaml         # Non-secret agent configuration

templates/
└── digest.html.j2           # Jinja2 HTML digest template (inline CSS)

scripts/
└── gmail_auth.py            # One-time OAuth consent flow

tests/
├── conftest.py
├── fixtures/
│   ├── __init__.py
│   └── load_eml.py
├── test_gmail_fetcher.py
├── test_email_parser.py
├── test_claude_summarizer.py
├── test_rate_limiter.py
├── test_digest_builder.py
├── test_delivery.py
├── test_runner.py
└── test_scheduler.py
```

**Structure Decision**: Single project layout (Option 1). The `agent/` package is the main source, with `tests/` mirroring its module structure. No frontend or mobile component.

---

## Phase 0: Research Summary

All unknowns resolved. See `specs/001-newsletter-digest-agent/research.md` for full rationale.

| Decision | Resolution |
|----------|------------|
| Gmail API access | `google-api-python-client` + OAuth 2.0 offline access (refresh tokens); `token.json` stored outside repo |
| Newsletter detection | Two-pass: exact sender match → case-insensitive subject keyword scan |
| HTML extraction | BS4 (strip boilerplate) → html2text (convert to Markdown-ish plaintext); 8,000 char truncation cap |
| Summarization | claude-sonnet-4-6; single API call per newsletter; 200–250 word target; retry once if ±20% out of range |
| Rate limiting | Token bucket, 1 req/2s; exponential backoff (base=1s, 3 attempts, jitter) for errors |
| Digest template | Jinja2 HTML with inline CSS; one section per summary, horizontal rule separator |
| Email delivery | `smtplib` STARTTLS (port 587); Gmail App Password |
| Scheduler | APScheduler `BlockingScheduler` + `CronTrigger`; default 6:30 AM; exceptions caught/logged per run |
| Configuration | Single `config/newsletters.yaml`; secrets from env via `python-dotenv` |
| Testing | `pytest-mock` at class boundary; integration tests `@pytest.mark.integration`, skipped in CI |

---

## Phase 1: Design Artifacts

### Data Model

See `specs/001-newsletter-digest-agent/data-model.md` for full field tables and relationship diagrams.

**Pipeline flow**:
```
Gmail API → Email (raw) → EmailParser → Email (plain_text) → ClaudeSummarizer → Summary → DigestBuilder → Digest (HTML) → EmailDelivery (SMTP)
```

**Key entities**:
- `Email` — frozen dataclass; created by `GmailFetcher`; `EmailParser` returns a new enriched instance (immutable pattern)
- `Summary` — frozen dataclass; created by `ClaudeSummarizer`; references `Email.id`
- `DigestEntry` — frozen dataclass; wraps `Summary` + `EmailLink` list + image URLs for rendering
- `AgentConfiguration` — mutable dataclass; loaded once at startup; passed via DI to all components

All `datetime` fields are UTC-aware. No naive datetimes. Deduplication key is `Email.id` (Gmail message ID).

### Interface Contracts

See `specs/001-newsletter-digest-agent/contracts/` for full contract documents.

- **`cli.md`** — CLI command schema (`python -m agent.runner [--dry-run] [--config PATH]`)
- **`config-schema.md`** — `newsletters.yaml` YAML schema + required ENV vars
- **`data-classes.md`** — Public dataclass interfaces for `Email`, `Summary`, `DigestEntry`, `EmailLink`

### Constitution Check (Post-Design)

Re-evaluated after Phase 1. All principles still pass:
- Typed dataclasses used throughout; no raw dicts cross module boundaries
- All secrets remain in environment variables
- Rate limiter wraps every Anthropic API call
- `structlog` used in every component; no `print()` in production paths
- Each component testable in isolation with mocked dependencies

---

## Complexity Tracking

*No constitution violations — table not applicable.*
