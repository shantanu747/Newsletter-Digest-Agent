# Contract: Configuration Schema

**File**: `config/newsletters.yaml`
**Loaded by**: `agent/runner.py` at startup

---

## Full Schema

```yaml
# config/newsletters.yaml

# Newsletter detection
senders:
  - "newsletter@example.com"      # Exact sender email addresses (case-insensitive match)
  - "digest@example.org"

subject_keywords:
  - "daily digest"                # Case-insensitive substring match against subject
  - "weekly roundup"
  - "newsletter"

# Fetch behaviour
lookback_hours: 24                # int, default: 24 — how far back to search inbox
max_newsletters_per_run: 20       # int, default: 20 — hard cap on newsletters per run

# Summarization
summary_word_target: 225          # int, default: 225 — target word count per summary

# Scheduling (used by python -m agent.scheduler)
schedule:
  hour: 6                         # int, 0–23
  minute: 30                      # int, 0–59
  timezone: "America/New_York"    # IANA timezone string
```

---

## Field Reference

| Key | Type | Required | Default | Constraints |
|-----|------|----------|---------|-------------|
| `senders` | `list[str]` | No | `[]` | Email addresses; empty list means sender-based detection disabled |
| `subject_keywords` | `list[str]` | No | `[]` | Substrings; empty list means keyword detection disabled |
| `lookback_hours` | `int` | No | `24` | Must be ≥ 1 |
| `max_newsletters_per_run` | `int` | No | `20` | Must be ≥ 1 and ≤ 100 |
| `summary_word_target` | `int` | No | `225` | Must be between 100 and 500 |
| `schedule.hour` | `int` | No | `6` | 0–23 |
| `schedule.minute` | `int` | No | `30` | 0–59 |
| `schedule.timezone` | `str` | No | `"UTC"` | Must be a valid IANA timezone string |

---

## Validation Behaviour

- At least one of `senders` or `subject_keywords` must be non-empty; both empty logs a WARNING and the run produces 0 newsletters (not an error).
- Unknown keys are ignored (forward compatibility).
- Type mismatches (e.g., `lookback_hours: "24"` as a string) raise a `ConfigurationError` at startup with the offending key and value.

---

## Secrets (NOT in YAML)

The following are loaded exclusively from environment variables. They must never appear in `newsletters.yaml`:

| Environment Variable | Description |
|---------------------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GMAIL_OAUTH_TOKEN_PATH` | Path to OAuth token file |
| `DELIVERY_EMAIL` | Digest recipient address |
| `SMTP_HOST` | SMTP server |
| `SMTP_PORT` | SMTP port |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP App Password |
