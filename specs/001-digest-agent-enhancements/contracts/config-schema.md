# Config Schema Contract: newsletters.yaml

**Feature**: 001-digest-agent-enhancements | **Date**: 2026-03-19

## Breaking Changes from Previous Version

- `senders` field type changed from `list[str]` → `list[SenderConfig]`
- `lookback_hours` field removed (no longer time-bounded)
- New required fields: each sender entry must have `address` and `mode`

## Full Schema

```yaml
# --- Polling ---
poll_interval_hours: 4          # int, default 4, minimum 1
batch_size: 10                  # int, default 10, range 1–50

# --- Summarization Defaults ---
summary_length_mode: "percentage"   # "fixed" | "percentage"
summary_percentage: 18              # int, 1–100 (used when mode=percentage)
summary_min_words: 100              # int, ≥ 1
summary_max_words: 500              # int, ≥ summary_min_words
summary_word_target: 225            # int, ≥ 50 (used when mode=fixed)

# --- Senders (REQUIRED, min 1 entry) ---
senders:
  - address: "sender@example.com"   # str, required, valid email
    display_name: "Name"            # str, optional
    mode: "summarize"               # "summarize" | "pass_through", required
    summary_word_target: 300        # int, optional, overrides global
    include_images: true            # bool, optional, default true
    max_images: 5                   # int, optional, default 10

# --- Subject Keywords (secondary match) ---
subject_keywords:                  # list[str], optional
  - "daily digest"

# --- Schedule ---
schedule:
  timezone: "America/Los_Angeles"   # IANA timezone string
```

## Validation Rules

| Field | Rule |
|-------|------|
| `poll_interval_hours` | Integer ≥ 1 |
| `batch_size` | Integer 1–50 |
| `senders` | Non-empty list; each entry must have `address` (valid email) and `mode` |
| `mode` | Must be exactly `"summarize"` or `"pass_through"` |
| `summary_word_target` (per-sender) | Integer ≥ 50 |
| `max_images` | Integer ≥ 0 |
| Unknown keys | Warn at startup, ignore (no hard failure) |
