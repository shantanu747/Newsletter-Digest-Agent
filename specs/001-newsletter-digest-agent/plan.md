# Implementation Plan: Newsletter Digest Agent

**Branch**: `001-newsletter-digest-agent` | **Date**: 2026-03-09 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-newsletter-digest-agent/spec.md`

## Summary

Build an AI-powered Python agent that fetches newsletters from Gmail, extracts and cleans their content, generates 200–250 word summaries via the Claude API, assembles a consolidated HTML digest email, and delivers it to the user on a daily schedule. The agent is fully configurable via YAML, rate-limited, resilient to transient failures, and testable with mocked external dependencies.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: `anthropic` SDK, `google-api-python-client` + OAuth 2.0, `beautifulsoup4`, `html2text`, `APScheduler`, `PyYAML`, `python-dotenv`, `structlog`, `Jinja2`, `pytest`, `pytest-mock`, `smtplib` (stdlib)
**Storage**: File-based only — `token.json` (OAuth credentials, gitignored), `config/newsletters.yaml` (allowlist + settings), `.env` (secrets, gitignored). No database.
**Testing**: `pytest` + `pytest-mock` — all external calls mocked at the class boundary
**Target Platform**: macOS / Linux developer workstation; long-running process or cron invocation
**Project Type**: CLI tool + scheduled background agent
**Performance Goals**: Process up to 20 newsletters end-to-end (fetch → extract → summarize → deliver) in under 15 minutes; digest delivered within 10 minutes of scheduled trigger
**Constraints**: Stay within Gmail API quota (250 quota units/second); respect Anthropic API rate limits per tier; no persistent cross-run deduplication store; single-user scope
**Scale/Scope**: Single user, up to 20 newsletters/day, one digest recipient

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Separation of Concerns — dedicated fetcher/client classes, no inline API calls | PASS | GmailFetcher, ClaudeSummarizer, EmailDelivery are dedicated classes; no inline requests |
| II. Secrets Management — env vars via python-dotenv, never hardcoded | PASS | All secrets (API keys, SMTP password, OAuth tokens) sourced from `.env` |
| III. Typed Data Transfer — dataclasses + type hints on all public signatures | PASS | Email, Summary, DigestEntry dataclasses defined in `utils/models.py` |
| IV. Reliability & Rate Limiting — rate limit before every Anthropic call, backoff on failures | PASS | TokenBucketLimiter applied before each summarization call; exponential backoff on all external APIs |
| V. Observability — structlog only, no print() | PASS | structlog configured in `utils/logger.py`; print() prohibited in production code |

**Gate result**: All principles satisfied. No violations. Proceed to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/001-newsletter-digest-agent/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── cli.md           # CLI interface contract
│   ├── config-schema.md # newsletters.yaml schema
│   └── data-classes.md  # Email, Summary, DigestEntry interfaces
└── tasks.md             # Phase 2 output (/speckit.tasks command — NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
agent/
├── __init__.py
├── runner.py                   # CLI entry point + orchestrator (NewsletterAgent class)
├── scheduler.py                # APScheduler wrapper (DigestScheduler class)
├── fetchers/
│   ├── __init__.py
│   ├── base_fetcher.py         # Abstract base: fetch_newsletters() -> list[Email]
│   └── gmail_fetcher.py        # GmailFetcher: OAuth 2.0, token refresh, quota backoff
├── parsers/
│   ├── __init__.py
│   └── email_parser.py         # EmailParser, HTMLStripper, BoilerplateRemover
├── summarizer/
│   ├── __init__.py
│   └── claude_summarizer.py    # ClaudeSummarizer: rate-limited Anthropic API calls + chunking
├── digest/
│   ├── __init__.py
│   ├── builder.py              # DigestBuilder: assembles summaries → HTML via Jinja2
│   └── delivery.py             # EmailDelivery: SMTP send with TLS auth
└── utils/
    ├── __init__.py
    ├── models.py               # Email, Summary, DigestEntry dataclasses
    ├── rate_limiter.py         # TokenBucketLimiter (thread-safe)
    └── logger.py               # structlog configuration

config/
└── newsletters.yaml            # Sender allowlist, keywords, schedule, limits

templates/
└── digest.html.j2              # Jinja2 HTML digest email template

scripts/
└── gmail_auth.py               # One-time OAuth consent flow

tests/
├── conftest.py                 # Fixtures: mock emails, mock API responses, mock SMTP
├── test_gmail_fetcher.py
├── test_email_parser.py
├── test_claude_summarizer.py
├── test_digest_builder.py
└── test_delivery.py

.env.example                    # Template for required secrets
.gitignore
pyproject.toml
requirements.txt
README.md
```

**Structure Decision**: Single-project layout. All source code under `agent/` package with clear sub-packages per pipeline stage. Tests mirror the source structure. No monorepo needed — this is a single-user CLI tool.

## Complexity Tracking

> No constitution violations — this section is not required.
