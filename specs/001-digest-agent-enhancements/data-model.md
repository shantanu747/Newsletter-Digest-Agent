# Data Model: Newsletter Digest Agent Enhancements

**Phase**: 1 | **Date**: 2026-03-19 | **Branch**: `001-digest-agent-enhancements`

---

## Modified Entities

### `SenderConfig` (new — replaces flat sender list in `AgentConfiguration`)

Represents the per-sender processing rules. Lives in `config/newsletters.yaml` under each sender entry.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `address` | `str` | Yes | — | Sender email address (matching key, case-insensitive) |
| `display_name` | `str` | No | Derived from From header | Human-readable name shown in digest |
| `mode` | `Literal["pass_through", "summarize"]` | Yes | `"summarize"` | Processing mode |
| `summary_word_target` | `int` | No | Global default (225) | Custom word target for `summarize` mode |
| `include_images` | `bool` | No | `True` | Whether to include qualifying images |
| `max_images` | `int` | No | Global default (10) | Max images to include from this sender |

**Validation rules**:
- `address` must be a valid email format
- `mode` must be exactly `"pass_through"` or `"summarize"`
- `summary_word_target` must be ≥ 50 if provided
- `max_images` must be ≥ 0 if provided

**Pre-configured pass-through senders** (in default `config/newsletters.yaml`):
- Superhuman (`mode: pass_through`)
- The Rundown AI (`mode: pass_through`)
- The Code (`mode: pass_through`)

---

### `AgentConfiguration` (extended)

Adds polling configuration and replaces `senders: list[str]` with `senders: list[SenderConfig]`.

| New/Changed Field | Type | Default | Description |
|---|---|---|---|
| `senders` | `list[SenderConfig]` | — | **Changed**: was `list[str]`, now list of SenderConfig objects |
| `poll_interval_hours` | `int` | `4` | How often the agent polls Gmail (in hours) |
| `batch_size` | `int` | `10` | Max emails per digest email |
| `lookback_hours` | `int` | **Removed** | Replaced by unread-inbox fetch (no time bound) |

---

### `Email` (extended)

Adds the Gmail message ID needed for post-delivery label operations.

| New Field | Type | Description |
|---|---|---|
| `gmail_message_id` | `str` | Raw Gmail message ID (used for mark-as-read and trash API calls) |
| `is_pass_through` | `bool` | Whether this email was processed in pass-through mode |

---

### `DigestEntry` (extended)

| New Field | Type | Description |
|---|---|---|
| `is_pass_through` | `bool` | Whether content was passed through (not AI-summarized) |
| `display_name` | `str` | Human-readable sender name for template rendering |
| `gmail_message_id` | `str` | Propagated from `Email` for post-delivery operations |

---

### `DigestBatch` (new)

Represents a group of up to 10 emails assembled into one digest email.

| Field | Type | Description |
|-------|------|-------------|
| `batch_index` | `int` | 0-based index of this batch in the current poll run |
| `entries` | `list[DigestEntry]` | Processed entries in this batch (max 10) |
| `gmail_message_ids` | `list[str]` | Source email IDs for post-delivery label operations |
| `total_batches` | `int` | Total number of batches in this poll run (for logging/TOC) |

**State transitions** (in-memory only per poll run):
```
pending → processing → delivered → [mark_read → trashed]
                    ↘ failed (source emails remain unread, not trashed)
```

No persistent state — Gmail's read/unread label IS the state.

---

## Config YAML Schema (updated)

```yaml
# Global defaults
poll_interval_hours: 4       # NEW: how often to poll Gmail
batch_size: 10               # NEW: max emails per digest
summary_length_mode: "percentage"
summary_percentage: 18
summary_min_words: 100
summary_max_words: 500
summary_word_target: 225

# Per-sender rules (NEW structure — replaces flat sender list)
senders:
  - address: "newsletter@morningbrew.com"
    display_name: "Morning Brew"
    mode: summarize

  - address: "digest@tldr.tech"
    display_name: "TLDR"
    mode: summarize

  - address: "superhuman@mail.superhuman.com"
    display_name: "Superhuman"
    mode: pass_through

  - address: "rundown@therundown.ai"
    display_name: "The Rundown AI"
    mode: pass_through

  - address: "newsletter@thecode.media"   # placeholder — update to actual address
    display_name: "The Code"
    mode: pass_through

# Subject keywords (still used as secondary matching)
subject_keywords:
  - "daily digest"
  - "weekly roundup"
  - "newsletter"

# Schedule
schedule:
  timezone: "America/Los_Angeles"
```

---

## Image Classification Signal Model

Not a stored entity, but documents the classification logic layers applied per image during parsing.

**Exclusion signals** (first match wins):
1. Source URL matches known tracking domain → EXCLUDE
2. Dimensions: width ≤ 1 AND height ≤ 1 → EXCLUDE (tracking pixel)
3. CSS class or ID contains: `banner`, `header`, `logo`, `icon`, `social`, `ad`, `advertisement`, `promo`, `footer`, `brand`, `sponsor` → EXCLUDE
4. Parent element is `<header>`, `<footer>`, or `<nav>` → EXCLUDE
5. Alt text contains: `logo`, `icon`, `badge`, `banner`, `social` → EXCLUDE
6. Width < 100px AND aspect ratio between 0.8 and 1.2 (near-square) AND not on trusted CDN → EXCLUDE

**Inclusion signals**:
- Source URL matches trusted CDN (Bloomberg, Beehiiv, Substack) AND passes exclusion checks → INCLUDE
- Parent is `<article>`, `<section>`, `<main>`, or `<p>` AND width ≥ 200px → INCLUDE
- Alt text contains: `chart`, `graph`, `data`, `visualization`, `meme` → INCLUDE

**Default**: EXCLUDE (opt-in policy)
