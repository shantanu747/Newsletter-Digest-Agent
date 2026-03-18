# Developer Quickstart: Newsletter Digest Agent

**Branch**: `001-newsletter-digest-agent` | **Date**: 2026-03-09

---

## Prerequisites

- Python 3.11 or higher
- A Gmail account with Gmail API enabled in Google Cloud Console
- An Anthropic API key
- Git

---

## 1. Clone and set up environment

```bash
git clone https://github.com/YOUR_USERNAME/newsletter-digest-agent.git
cd newsletter-digest-agent

python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

---

## 2. Configure secrets

```bash
cp .env.example .env
```

Edit `.env` and fill in all required values:

```env
ANTHROPIC_API_KEY=sk-ant-...
GMAIL_OAUTH_TOKEN_PATH=token.json
DELIVERY_EMAIL=you@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-16-char-app-password
```

> **Gmail App Password**: Go to your Google Account → Security → 2-Step Verification → App passwords. Generate one for "Mail" and paste it as `SMTP_PASSWORD`. This is not your regular Gmail password.

---

## 3. Authenticate with Gmail

Run the one-time OAuth consent flow:

```bash
python scripts/gmail_auth.py
```

This opens a browser window. Sign in and grant read access to Gmail. Credentials are saved to `token.json` (gitignored). You only need to run this once; the agent will refresh the token automatically on subsequent runs.

---

## 4. Configure newsletters

Edit `config/newsletters.yaml`:

```yaml
senders:
  - "newsletter@morningbrew.com"
  - "digest@tldr.tech"

subject_keywords:
  - "daily digest"
  - "newsletter"

lookback_hours: 24
max_newsletters_per_run: 20
summary_word_target: 225

schedule:
  hour: 6
  minute: 30
  timezone: "America/New_York"
```

Add at least one sender address or keyword to enable newsletter detection.

---

## 5. Test with a dry run

```bash
python -m agent.runner --dry-run
```

This fetches and summarizes newsletters but does **not** send an email. Review the output to confirm newsletters are being detected and summaries look correct.

---

## 6. Run the full agent

```bash
python -m agent.runner
```

Fetches, summarizes, and delivers the digest to `DELIVERY_EMAIL`. Check your inbox within a minute.

---

## 7. Start the daily scheduler (optional)

```bash
python -m agent.scheduler
```

Runs until interrupted. Triggers a full run daily at the configured `schedule.hour:schedule.minute` in the configured timezone. Keep this process alive with `screen`, `tmux`, or a process manager.

---

## Running Tests

```bash
pytest                          # All unit tests (no credentials needed)
pytest -v                       # Verbose output
pytest tests/test_email_parser.py  # Single module
pytest -m integration           # Integration tests (requires real credentials)
```

All unit tests run offline with mocked external dependencies.

---

## Project Layout (quick reference)

| Path | Purpose |
|------|---------|
| `agent/runner.py` | CLI entry point + orchestrator |
| `agent/scheduler.py` | APScheduler wrapper |
| `agent/fetchers/gmail_fetcher.py` | Gmail API integration |
| `agent/parsers/email_parser.py` | HTML stripping + content extraction |
| `agent/summarizer/claude_summarizer.py` | Anthropic API calls |
| `agent/digest/builder.py` | HTML digest assembly |
| `agent/digest/delivery.py` | SMTP delivery |
| `agent/utils/models.py` | Email, Summary, DigestEntry dataclasses |
| `agent/utils/rate_limiter.py` | Token bucket rate limiter |
| `agent/utils/logger.py` | structlog configuration |
| `config/newsletters.yaml` | Non-secret configuration |
| `templates/digest.html.j2` | Jinja2 HTML digest template |
| `scripts/gmail_auth.py` | One-time OAuth setup |
| `tests/` | Pytest test suite |

---

## Common Issues

**"No newsletters found"**: Check that `config/newsletters.yaml` has at least one sender address or keyword, and that matching emails exist in your inbox within the `lookback_hours` window.

**OAuth token error**: Re-run `python scripts/gmail_auth.py` to refresh credentials.

**SMTP authentication failure**: Confirm you're using a Gmail App Password (not your regular password) and that 2-Step Verification is enabled on your Google account.

**Summary word count warnings**: Normal for very short newsletters. The agent retries once if the count is outside the 160–300 word tolerance range.
