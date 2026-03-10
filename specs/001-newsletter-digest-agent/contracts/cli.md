# Contract: CLI Interface

**Module**: `agent/runner.py`
**Invocation**: `python -m agent.runner [OPTIONS]`

---

## Commands

### Run (default)

Executes a full agent run: fetch → parse → summarize → deliver.

```
python -m agent.runner
```

**Behaviour**:
- Loads config from `config/newsletters.yaml` and environment variables
- Fetches newsletters from Gmail within the configured `lookback_hours` window
- Parses, summarizes, assembles, and delivers the digest email
- Exits 0 on success (even if some newsletters failed — partial success is success)
- Exits 1 on fatal errors (config missing, Gmail auth failure, SMTP failure after retry)

---

### Dry Run

Executes all steps except email delivery. Outputs digest content to stdout/log.

```
python -m agent.runner --dry-run
```

**Behaviour**:
- Identical to default run through the summarization step
- Instead of sending email: logs digest content at INFO level and prints to terminal
- Always exits 0 unless a fatal config/auth error occurs
- Safe to run repeatedly without side effects

---

### Scheduler

Starts the in-process scheduler that triggers a full run on a daily cron schedule.

```
python -m agent.scheduler
```

**Behaviour**:
- Reads `schedule.hour`, `schedule.minute`, and `schedule.timezone` from config
- Runs indefinitely until interrupted (Ctrl+C / SIGTERM)
- Each scheduled run is equivalent to `python -m agent.runner`
- Exceptions from individual runs are caught and logged; the scheduler continues

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (full or partial — at least 0 newsletters processed without fatal error) |
| 1 | Fatal error (config missing/invalid, Gmail auth failure, unrecoverable SMTP error) |

---

## Environment Variables (required at runtime)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude summarization |
| `GMAIL_OAUTH_TOKEN_PATH` | Path to `token.json` OAuth credentials file |
| `DELIVERY_EMAIL` | Recipient email address for digest delivery |
| `SMTP_HOST` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP port (e.g. `587`) |
| `SMTP_USER` | SMTP authentication username |
| `SMTP_PASSWORD` | SMTP App Password |

---

## Logging Output

All output uses structured JSON logging (structlog). Key log events:

| Event | Level | Fields |
|-------|-------|--------|
| Agent run started | INFO | `run_id`, `dry_run`, `lookback_hours` |
| Newsletter found | INFO | `message_id`, `sender`, `subject` |
| Newsletter summarized | INFO | `message_id`, `word_count`, `attempt` |
| Newsletter failed | WARNING | `message_id`, `subject`, `error`, `attempts` |
| Digest delivered | INFO | `recipient`, `newsletter_count`, `failed_count` |
| Digest skipped (dry run) | INFO | `newsletter_count` |
| No newsletters found | INFO | `lookback_hours` |
| Fatal error | ERROR | `error`, `traceback` |
