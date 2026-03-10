# Data Model: Newsletter Digest Agent

**Branch**: `001-newsletter-digest-agent` | **Date**: 2026-03-09
**Source**: `specs/001-newsletter-digest-agent/spec.md` → Key Entities section

---

## Overview

The agent passes data between pipeline stages using typed dataclasses. All inter-module data transfer uses these types — no raw dicts or untyped tuples across module boundaries (constitution principle III).

```
Gmail API
   │
   ▼
Email (raw)
   │
   ▼ EmailParser
Email (with plain_text populated)
   │
   ▼ ClaudeSummarizer
Summary
   │
   ▼ DigestBuilder
Digest
   │
   ▼ EmailDelivery
(SMTP send)
```

---

## Entity: Email

**Module**: `agent/utils/models.py`
**Represents**: A single newsletter email fetched from Gmail, before or after content extraction.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `str` | Yes | Unique Gmail message ID (used for deduplication) |
| `source` | `str` | Yes | Always `"gmail"` for current implementation |
| `sender` | `str` | Yes | Full sender address, e.g. `"hello@stratechery.com"` |
| `subject` | `str` | Yes | Original email subject line |
| `received_at` | `datetime` | Yes | UTC timestamp when email was received |
| `raw_html` | `str` | Yes | Raw HTML body of the email (may be empty string if plain-text only) |
| `plain_text` | `str \| None` | No | Extracted plain text after parsing; `None` until `EmailParser` runs |

**Validation rules**:
- `id` must be non-empty
- `received_at` must be timezone-aware (UTC)
- At least one of `raw_html` or a non-None `plain_text` must be present for summarization to proceed

**State transitions**:
- Created by `GmailFetcher` with `plain_text=None`
- `EmailParser` populates `plain_text` from `raw_html`; returns a new `Email` instance (immutable pattern)

---

## Entity: Summary

**Module**: `agent/utils/models.py`
**Represents**: An AI-generated summary of a single newsletter email.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email_id` | `str` | Yes | References `Email.id` — links summary to source email |
| `sender` | `str` | Yes | Copied from source `Email.sender` |
| `subject` | `str` | Yes | Copied from source `Email.subject` |
| `summary_text` | `str` | Yes | Generated summary prose, target 200–250 words |
| `word_count` | `int` | Yes | Actual word count of `summary_text` |
| `generated_at` | `datetime` | Yes | UTC timestamp when summary was generated |

**Validation rules**:
- `summary_text` must be non-empty
- `word_count` should fall within 160–300 words (200–250 target ± 25% tolerance before retry)
- `generated_at` must be timezone-aware (UTC)

---

## Entity: DigestEntry

**Module**: `agent/utils/models.py`
**Represents**: A single entry in the assembled digest — a summary enriched with optional metadata for rendering.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `summary` | `Summary` | Yes | The underlying summary object |
| `original_email_url` | `str \| None` | No | Optional web-view URL for the original newsletter (if available in headers) |

**Notes**: `DigestEntry` is intentionally thin — it wraps `Summary` and adds only presentation-layer metadata. The `DigestBuilder` converts a `list[DigestEntry]` into the final HTML.

---

## Entity: Digest

**Module**: Assembled in `agent/digest/builder.py` — not a persistent dataclass; represents the output of a single run.

| Field | Type | Description |
|-------|------|-------------|
| `entries` | `list[DigestEntry]` | All successfully summarized newsletters, ordered by `received_at` descending |
| `run_date` | `datetime` | UTC timestamp of when this run was initiated |
| `total_found` | `int` | Number of newsletters found in inbox matching the filter |
| `total_summarized` | `int` | Number successfully summarized (= `len(entries)`) |
| `failed_subjects` | `list[str]` | Subjects of newsletters that failed after all retries |

**Notes**: `Digest` is used for rendering the HTML template and for the log summary at run end. Not persisted to disk.

---

## Entity: AgentConfiguration

**Module**: Loaded by `agent/runner.py` from `config/newsletters.yaml` + environment variables.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `senders` | `list[str]` | YAML | Exact sender email addresses to include |
| `subject_keywords` | `list[str]` | YAML | Case-insensitive subject keywords for fallback detection |
| `lookback_hours` | `int` | YAML | How many hours back to search (default: 24) |
| `max_newsletters_per_run` | `int` | YAML | Cap on newsletters processed per run (default: 20) |
| `summary_word_target` | `int` | YAML | Target word count per summary (default: 225) |
| `schedule_hour` | `int` | YAML | Hour of day for scheduled run (default: 6) |
| `schedule_minute` | `int` | YAML | Minute of hour for scheduled run (default: 30) |
| `schedule_timezone` | `str` | YAML | Timezone string, e.g. `"America/New_York"` |
| `delivery_recipient` | `str` | ENV (`DELIVERY_EMAIL`) | Destination email for digest delivery |
| `anthropic_api_key` | `str` | ENV (`ANTHROPIC_API_KEY`) | Anthropic API key |
| `gmail_token_path` | `str` | ENV (`GMAIL_OAUTH_TOKEN_PATH`) | Path to `token.json` OAuth credentials |
| `smtp_host` | `str` | ENV (`SMTP_HOST`) | SMTP server hostname |
| `smtp_port` | `int` | ENV (`SMTP_PORT`) | SMTP port (587 for STARTTLS) |
| `smtp_user` | `str` | ENV (`SMTP_USER`) | SMTP authentication username |
| `smtp_password` | `str` | ENV (`SMTP_PASSWORD`) | SMTP authentication password (App Password) |

**Validation**: All ENV fields must be present and non-empty at startup. Missing fields cause the agent to exit immediately with a descriptive error. YAML fields use defaults if not specified.

---

## Relationships

```
AgentConfiguration
       │ configures
       ▼
GmailFetcher ──produces──▶ Email[]
                                │
                          EmailParser ──produces──▶ Email[] (plain_text populated)
                                                        │
                                               ClaudeSummarizer ──produces──▶ Summary[]
                                                                                    │
                                                                          DigestBuilder ──produces──▶ Digest
                                                                                                        │
                                                                                               EmailDelivery
```

---

## Key Constraints

- All `datetime` fields are UTC-aware (`datetime.timezone.utc`). No naive datetimes.
- Deduplication key is `Email.id` (Gmail message ID) — guaranteed unique per Gmail account.
- `Email`, `Summary`, and `DigestEntry` are treated as immutable after creation. Pipeline stages return new instances rather than mutating existing ones.
- `AgentConfiguration` is loaded once at startup and passed via dependency injection to all components. No global state.
