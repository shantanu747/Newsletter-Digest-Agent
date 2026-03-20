# 📬 Newsletter Digest Agent

An AI-powered agent that automatically fetches newsletters from Gmail, summarizes them using Claude, and delivers a consolidated daily digest to your inbox.

---

## Overview

Reading newsletters takes time. This agent solves that by running on a daily schedule, identifying newsletters from your inbox, extracting their content, summarizing each one with Claude (Anthropic), and emailing you a clean digest — all before your morning coffee.

**Target time savings:** reduces daily newsletter reading from 45–90 minutes to a ~15–20 minute digest review.

---

## Features

- **Gmail integration** — connects to Gmail via OAuth 2.0 for secure, quota-managed email fetching
- **Smart newsletter detection** — filters by sender allowlist and/or subject keywords
- **HTML content extraction** — strips boilerplate, headers, footers, and tracking pixels
- **AI summarization** — generates ~200–250 word summaries via Claude API, preserving tone and key insights
- **Daily digest delivery** — consolidates all summaries into a single formatted email
- **Rate limit handling** — built-in backoff and throttling for all external APIs
- **Configurable** — YAML-based config for senders, keywords, schedule, and delivery preferences

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Scheduler (cron / APScheduler)        │
└───────────────────────────┬─────────────────────────────────┘
                            │ triggers daily
                ┌───────────▼───────────┐
                │     Orchestrator       │
                │   (agent/runner.py)    │
                └───────────┬───────────┘
                            │
                   ┌────────▼────────┐
                   │  Gmail Fetcher   │
                   │  (OAuth 2.0)     │
                   └────────┬────────┘
                            │ raw emails
                   ┌────────▼────────┐
                   │  Email Parser    │
                   │  + HTML Stripper │
                   └────────┬────────┘
                            │ clean text
                   ┌────────▼────────┐
                   │  Claude          │
                   │  Summarizer      │
                   │  (Anthropic API) │
                   └────────┬────────┘
                            │ summaries
                   ┌────────▼────────┐
                   │  Digest Builder  │
                   └────────┬────────┘
                            │ formatted digest
                   ┌────────▼────────┐
                   │  Email Delivery  │
                   │  (SMTP / Gmail)  │
                   └─────────────────┘
```

---

## Tech Stack

| Component | Library / API | Reason |
|---|---|---|
| Gmail fetching | `google-api-python-client` + OAuth 2.0 | Official, reliable, quota-managed |
| HTML parsing | `beautifulsoup4` + `html2text` | Industry standard for content extraction |
| AI summarization | `anthropic` SDK | Claude Sonnet — best cost/quality tradeoff for text summarization |
| Email delivery | `smtplib` (stdlib) or SendGrid | SMTP for simplicity; SendGrid for reliability at scale |
| Scheduling | `APScheduler` | Lightweight in-process scheduler; easy cron-like syntax |
| Config management | `PyYAML` + `python-dotenv` | Secrets in `.env`, non-secret config in `config.yaml` |
| Logging | `structlog` | Structured JSON logs; easier to debug agent runs |
| Development workflow | spec-kit | Specification-driven development — `/specify`, `/plan`, `/tasks` commands drive each phase |

---

## Prerequisites

- Python 3.11+
- A Google Cloud project with Gmail API enabled
- An Anthropic API key
- Git

---

## ⚠️ Migration Notice (v2 — Breaking Changes)

If you are upgrading from the previous version, two breaking changes require manual action before running:

### 1. Re-authenticate Gmail (required)

The agent now uses `gmail.modify` scope instead of `gmail.readonly` in order to mark emails as read and move them to trash after delivery. Your existing `token.json` will be rejected for write operations.

```bash
rm token.json
python scripts/gmail_auth.py
```

Follow the browser prompt to grant the updated permission.

### 2. Migrate `config/newsletters.yaml` (required)

The `senders` field changed from a flat list of strings to a list of per-sender objects.

```yaml
# OLD format (v1 — no longer valid):
senders:
  - "newsletter@morningbrew.com"
lookback_hours: 24

# NEW format (v2):
poll_interval_hours: 4
batch_size: 10
senders:
  - address: "newsletter@morningbrew.com"
    display_name: "Morning Brew"
    mode: summarize          # or: pass_through
```

The `lookback_hours` field is removed. The agent now fetches all unread emails from configured senders regardless of age.

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/shantanu747/newsletter-digest-agent.git
cd newsletter-digest-agent
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
.venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Gmail (fetching + delivery)
GMAIL_OAUTH_TOKEN_PATH=token.json
DELIVERY_EMAIL=you@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-gmail-app-password
```

### 5. Configure Gmail OAuth

```bash
python scripts/gmail_auth.py
```

This opens a browser window for OAuth consent. Credentials are saved to `token.json` (gitignored).

### 6. Initialize spec-kit

This project uses [spec-kit](https://github.com/github/spec-kit) for specification-driven development. Once your environment is ready, use these commands to drive each phase:

```bash
/specify   # define or review the project specification
/plan      # generate or update the phased implementation plan
/tasks     # break the current phase into actionable tasks
```

The architectural rules governing this project are captured in the **Spec-Kit Constitution** section of `PLANNING.md`. Paste that constitution as your `/speckit.constitution` prompt when initializing.

### 7. Configure newsletters

Edit `config/newsletters.yaml`:

```yaml
senders:
  - "newsletter@morningbrew.com"
  - "digest@tldr.tech"
  - "hello@stratechery.com"

subject_keywords:
  - "daily digest"
  - "weekly roundup"
  - "newsletter"

lookback_hours: 24
max_newsletters_per_run: 20
summary_word_target: 225
```

### 8. Run manually (test)

```bash
python -m agent.runner --dry-run    # fetches and summarizes, no email sent
python -m agent.runner              # full run, sends digest
```

### 9. Schedule daily runs

```bash
python -m agent.scheduler           # starts APScheduler process
```

Or add to crontab (runs at 6:30am daily):

```
30 6 * * * /path/to/.venv/bin/python -m agent.runner
```

---

## Project Structure

```
newsletter-digest-agent/
├── agent/
│   ├── __init__.py
│   ├── runner.py              # orchestrator entry point
│   ├── scheduler.py           # APScheduler wrapper
│   ├── fetchers/
│   │   ├── __init__.py
│   │   └── gmail_fetcher.py   # Gmail API integration
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── email_parser.py    # HTML stripping, content extraction
│   ├── summarizer/
│   │   ├── __init__.py
│   │   └── claude_summarizer.py  # Anthropic API calls
│   ├── digest/
│   │   ├── __init__.py
│   │   ├── builder.py         # assembles digest from summaries
│   │   └── delivery.py        # SMTP email sending
│   └── utils/
│       ├── __init__.py
│       ├── rate_limiter.py    # token bucket / backoff utilities
│       └── logger.py          # structlog setup
├── config/
│   └── newsletters.yaml       # sender/keyword allowlists
├── scripts/
│   └── gmail_auth.py          # one-time OAuth setup
├── tests/
│   ├── test_fetchers.py
│   ├── test_parser.py
│   └── test_summarizer.py
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Configuration Reference

| Key | Type | Default | Description |
|---|---|---|---|
| `senders` | list[str] | `[]` | Email addresses to treat as newsletters |
| `subject_keywords` | list[str] | `[]` | Subject line keywords for fallback detection |
| `lookback_hours` | int | `24` | How many hours back to search for newsletters |
| `max_newsletters_per_run` | int | `20` | Cap to avoid hitting API rate limits |
| `summary_word_target` | int | `225` | Target word count per summary |

---

## Rate Limits & API Quotas

| Service | Limit | Handling |
|---|---|---|
| Gmail API | 250 quota units/second | Exponential backoff via `googleapiclient.errors.HttpError` |
| Anthropic API | Varies by tier | Token bucket rate limiter + retry with backoff |

---

## Roadmap

- [ ] Web UI for reviewing/editing summaries before sending
- [ ] Support for Outlook / Microsoft Graph API
- [ ] Vector store for deduplication across newsletters
- [ ] Slack delivery option
- [ ] Per-newsletter tone/length customization

---

## Contributing

Pull requests are welcome. For major changes, open an issue first to discuss what you'd like to change.

---

## License

MIT — see [LICENSE](LICENSE) for details.
