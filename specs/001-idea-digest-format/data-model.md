# Data Model: Idea-Based Digest Format

**Feature**: 001-idea-digest-format | **Date**: 2026-04-08

## New Entity

### `Idea`

A discrete, self-contained concept extracted from a newsletter email.

| Field | Type | Constraints |
|---|---|---|
| `title` | `str` | ≤8 words; non-empty |
| `summary_text` | `str` | 1–3 sentences; no URLs; non-empty |

**Frozen dataclass.** No relationships to other entities — it is a value object owned by `Summary`.

---

## Modified Entities

### `Summary` (modified)

Gains one optional field:

| Field | Type | Change |
|---|---|---|
| `ideas` | `tuple[Idea, ...] \| None` | New. `None` in classic mode; populated tuple in idea-based mode. |

All existing fields (`email_id`, `sender`, `subject`, `summary_text`, `word_count`, `generated_at`) are **unchanged**. In idea-based mode, `summary_text` is set to `""` (empty string) and `word_count` to `0` — they are not rendered.

---

### `AgentConfiguration` (modified)

Gains one field:

| Field | Type | Default | Source |
|---|---|---|---|
| `digest_format` | `Literal["classic", "idea_based"]` | `"classic"` | `config/newsletters.yaml` → `digest_format` key |

---

## Config Schema Addition

### `config/newsletters.yaml` — new top-level key

```yaml
# Controls the digest summarization format.
# "classic"    — word-count based summary (default)
# "idea_based" — idea decomposition with relevance filtering
digest_format: "idea_based"
```

This key is optional. If absent, `AgentConfiguration.digest_format` defaults to `"classic"`.

---

## Entity Relationships (unchanged)

```
DigestBatch
  └─ entries: list[DigestEntry]
       └─ summary: Summary
            └─ ideas: tuple[Idea, ...] | None   ← NEW (idea_based mode only)
       └─ links: tuple[EmailLink, ...]           ← empty tuple in idea_based mode
```

---

## State Transitions

No lifecycle state transitions. `Idea` objects are immutable value objects created during summarization and consumed during rendering. They are not persisted.

---

## Validation Rules

- `Idea.title` must be non-empty after stripping whitespace.
- `Idea.summary_text` must be non-empty after stripping whitespace.
- `Summary.ideas` is `None` when `digest_format == "classic"`; a non-None tuple (possibly empty, indicating no relevant ideas found) when `digest_format == "idea_based"`.
- `AgentConfiguration.digest_format` must be one of `"classic"` or `"idea_based"`; any other value raises a config validation error at startup.
