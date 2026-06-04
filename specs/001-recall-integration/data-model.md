# Data Model: Filtering Rollback — Always-On Newsletter Digest

**Feature**: `001-recall-integration` | **Date**: 2026-04-15

## No data model changes

This feature makes no changes to any dataclass or data transfer object.

All existing models are used as-is:

| Model | Location | Role | Changed? |
|-------|----------|------|----------|
| `Idea` | `agent/utils/models.py` | Represents one extracted idea (title + summary_text) | No |
| `Summary` | `agent/utils/models.py` | Wraps ideas for a single newsletter | No |
| `DigestEntry` | `agent/utils/models.py` | Wraps Summary for template rendering | No |
| `Email` | `agent/utils/models.py` | Input to summarizer | No |

The only change is to the **prompt string** and **parser fallback** inside `agent/summarizer/claude_summarizer.py`. No fields added, removed, or renamed. No schema migrations, config file additions, or storage changes.
