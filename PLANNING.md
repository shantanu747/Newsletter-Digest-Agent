# Newsletter Digest Agent — Project Planning Docs

---

## Component Breakdown & API Selection

| Component | Library / API | Justification |
|---|---|---|
| **Gmail Fetcher** | `google-api-python-client` + OAuth 2.0 | Official Google library. OAuth 2.0 is required by Google — no workaround. Stable, well-documented, quota-managed. |
| **Newsletter Filter** | Custom (Python) | Simple sender allowlist + subject keyword matching. No external dependency needed. Regex for keyword matching. |
| **HTML Parser / Content Extractor** | `beautifulsoup4` + `html2text` | BS4 for DOM traversal and stripping; `html2text` for clean markdown-ish plaintext. Handles malformed HTML gracefully. |
| **AI Summarizer** | `anthropic` Python SDK | Claude Sonnet balances cost and quality well for summarization tasks. Native streaming support for long newsletters. |
| **Rate Limiter** | Custom token bucket (stdlib `threading`) | Simple, dependency-free. Controls Anthropic API call frequency to stay within tier limits. |
| **Digest Builder** | Custom (Python + Jinja2) | Jinja2 templates for HTML digest email. Keeps presentation logic separate from business logic. |
| **Email Delivery** | `smtplib` (stdlib) | No external dependency for MVP. Upgrade path to SendGrid if deliverability becomes an issue. |
| **Scheduler** | `APScheduler` | Lightweight in-process scheduler. Avoids needing a separate cron process. Supports timezone-aware scheduling. |
| **Config** | `PyYAML` + `python-dotenv` | Industry standard. Secrets in `.env` (never committed), non-secret config in `config.yaml`. |
| **Logging** | `structlog` | Structured JSON logs make it easy to understand agent run history and debug failures. |
| **Testing** | `pytest` + `pytest-mock` | Standard Python testing stack. Mock external API calls to keep tests fast and offline. |
| **Spec-Kit** | spec-kit CLI | Specification-driven development tool. `/specify` captures architectural intent; `/plan` produces phased tasks; `/tasks` manages execution. Constitution lives in this file. |

---

## Implementation Plan

| Phase | Task | Estimated Time | Risk / Notes |
|---|---|---|---|
| **Phase 1: Foundation** | Repo setup, virtual env, pyproject.toml, .gitignore, .env.example | 1–2 hrs | Low. Pure scaffolding. |
| | Gmail OAuth setup script + credential storage | 2–3 hrs | Medium. OAuth consent screen setup in Google Cloud Console can be fiddly the first time. |
| **Phase 2: Fetching** | `GmailFetcher` class — list, filter by sender/subject, fetch body | 3–4 hrs | Medium. Gmail API returns base64-encoded MIME parts; decoding multipart emails requires care. |
| | Newsletter filter logic (allowlist + keyword matching) | 1–2 hrs | Low. |
| **Phase 3: Parsing** | `EmailParser` — HTML stripping, boilerplate removal, plaintext extraction | 3–5 hrs | High. Newsletter HTML varies wildly. Some have complex layouts; footers/unsubscribe links need aggressive stripping. Plan for iteration here. |
| **Phase 4: Summarization** | `ClaudeSummarizer` class — prompt design, API call, response parsing | 2–3 hrs | Low-Medium. Prompt engineering to hit the 200–250 word target consistently may take a few iterations. |
| | Rate limiter utility | 1–2 hrs | Low. |
| | Error handling for API failures (retry, backoff) | 1–2 hrs | Low. |
| **Phase 5: Digest & Delivery** | `DigestBuilder` — Jinja2 HTML email template | 2–3 hrs | Low. |
| | `EmailDelivery` — SMTP send via Gmail | 1–2 hrs | Low. Use Gmail App Password; avoid OAuth for outbound sending to keep it simple. |
| **Phase 6: Orchestration** | `runner.py` — wires all components together, `--dry-run` flag | 2–3 hrs | Low. |
| | `scheduler.py` — APScheduler daily trigger | 1–2 hrs | Low. |
| **Phase 7: Testing** | Unit tests for parser, summarizer, fetchers (mocked) | 4–6 hrs | Medium. Mocking IMAP and Gmail API responses takes setup but is important for reliability. |
| **Phase 8: Polish** | Logging, README finalization, .env.example, code comments | 2–3 hrs | Low. |
| **Total Estimate** | | **~25–35 hrs** | Spread over 2–3 weekends realistically. |

### Key Risks

1. **Newsletter HTML variance** — Some newsletters (e.g., heavy visual ones) have very little extractable text. Consider a fallback that passes raw HTML directly to Claude with a "extract and summarize" prompt.
2. **Claude token limits** — Very long newsletters could exceed context. Implement a chunking strategy in the parser that trims to the first N characters or top-level sections.
3. **Gmail OAuth token expiry** — Access tokens expire. Implement auto-refresh using the `google-auth` library's built-in token refresh, and store refresh tokens securely.
4. **Spam/delivery issues** — Programmatic email via SMTP can land in spam. Use Gmail SMTP authenticated with your own account to maximize deliverability.

---

## Code Structure

```
newsletter-digest-agent/
│
├── agent/                          # Core application package
│   ├── __init__.py
│   │
│   ├── runner.py                   # Entry point / orchestrator
│   │   └── NewsletterAgent         # Main class: fetch → parse → summarize → deliver
│   │
│   ├── scheduler.py                # APScheduler wrapper
│   │   └── DigestScheduler         # Configures and starts the daily job
│   │
│   ├── fetchers/                   # Email retrieval layer
│   │   ├── __init__.py
│   │   ├── base_fetcher.py         # Abstract base class: fetch_newsletters() -> list[Email]
│   │   └── gmail_fetcher.py
│   │       └── GmailFetcher        # Uses google-api-python-client, handles OAuth token refresh
│   │
│   ├── parsers/                    # Content extraction layer
│   │   ├── __init__.py
│   │   └── email_parser.py
│   │       ├── EmailParser         # Orchestrates parsing pipeline
│   │       ├── HTMLStripper        # BS4-based HTML → plaintext
│   │       └── BoilerplateRemover  # Strips unsubscribe blocks, headers, footers
│   │
│   ├── summarizer/                 # AI summarization layer
│   │   ├── __init__.py
│   │   └── claude_summarizer.py
│   │       └── ClaudeSummarizer    # Anthropic API calls, prompt templates, chunking
│   │
│   ├── digest/                     # Output assembly + delivery layer
│   │   ├── __init__.py
│   │   ├── builder.py
│   │   │   └── DigestBuilder       # Assembles summaries into HTML digest via Jinja2
│   │   └── delivery.py
│   │       └── EmailDelivery       # SMTP send, handles auth + TLS
│   │
│   └── utils/                      # Shared utilities
│       ├── __init__.py
│       ├── rate_limiter.py
│       │   └── TokenBucketLimiter  # Thread-safe rate limiting for API calls
│       ├── logger.py               # structlog configuration
│       └── models.py               # Dataclasses: Email, Summary, DigestEntry
│
├── config/
│   └── newsletters.yaml            # Sender allowlist, keywords, schedule config
│
├── templates/
│   └── digest.html.j2              # Jinja2 template for digest email
│
├── scripts/
│   └── gmail_auth.py               # One-time OAuth consent + token generation
│
├── tests/
│   ├── conftest.py                 # Pytest fixtures (mock emails, mock API responses)
│   ├── test_gmail_fetcher.py
│   ├── test_email_parser.py
│   ├── test_claude_summarizer.py
│   └── test_digest_builder.py
│
├── .specify/
│   └── memory/
│       └── constitution.md         # Spec-Kit architectural rules (see Spec-Kit section below)
├── .claude/
│   └── commands/                   # Spec-Kit slash commands for Claude Code
├── .env.example                    # Template for required secrets
├── .gitignore
├── pyproject.toml                  # Project metadata + dependencies
├── requirements.txt                # Pinned dependencies for reproducibility
└── README.md
```

### Key Data Models (`utils/models.py`)

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Email:
    id: str
    source: str              # "gmail"
    sender: str
    subject: str
    received_at: datetime
    raw_html: str
    plain_text: str | None = None

@dataclass
class Summary:
    email_id: str
    sender: str
    subject: str
    summary_text: str        # ~200-250 words
    word_count: int
    generated_at: datetime

@dataclass
class DigestEntry:
    summary: Summary
    original_email_url: str | None = None
```

---

## Spec-Kit — Workflow & Constitution

This project uses [spec-kit](https://github.com/github/spec-kit) as its development workflow tool. Rather than maintaining ad-hoc task lists, each phase of the Implementation Plan above is driven through spec-kit's three commands:

- `/specify` — captures or updates the project specification; run when requirements change or a new phase begins
- `/plan` — generates a phased breakdown aligned to the current spec; the Implementation Plan table above was seeded from this output
- `/tasks` — produces the actionable task list for the current phase; use this as your daily work queue

The constitution below governs all code produced in this project. Paste it as your `/speckit.constitution` prompt when initializing:

```
This project is a Python agent (3.11+).
Tech stack: anthropic SDK, google-api-python-client, beautifulsoup4,
html2text, APScheduler, PyYAML, python-dotenv, structlog, Jinja2, pytest.

Architectural rules:
- All external API calls go through dedicated fetcher/client classes, never inline
- Secrets only from environment variables via python-dotenv, never hardcoded
- Use dataclasses for all inter-module data transfer (Email, Summary, DigestEntry)
- Each component is independently unit-testable with mocked dependencies
- Rate limiting must be applied before every Anthropic API call
- Log every agent run start, each newsletter processed, and delivery status
- No print() statements in production code — use structlog logger exclusively
- Follow PEP 8; use type hints on all public function signatures
```

Run `/specify` first whenever you return to this project after a break — it re-orients the session to the current architectural state before any code is written or modified.
