# Implementation Plan: Filtering Rollback — Always-On Newsletter Digest

**Branch**: `001-recall-integration` | **Date**: 2026-04-15 | **Spec**: [spec.md](spec.md)

## Summary

Remove the interest-based suppression gate from the idea-based digest format. The `_IDEA_SYSTEM_PROMPT_TEMPLATE` in `agent/summarizer/claude_summarizer.py` currently instructs Claude to output a "No High-Signal Content" stub when it judges a newsletter irrelevant to the user's profile. This prompt instruction — and its matching parser fallback in `_parse_ideas()` — must be replaced so that every newsletter always yields real ideas. The user profile is retained in the prompt for framing context only (portfolio connections mentioned inline), not as a relevance gate.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: `anthropic` SDK (Claude claude-sonnet-4-6), `pytest` + `pytest-mock`  
**Storage**: N/A — no persistence changes  
**Testing**: `pytest` + `pytest-mock`  
**Target Platform**: Local Python CLI / APScheduler daemon  
**Project Type**: CLI agent  
**Performance Goals**: No change — one prompt string modified, no new API calls added  
**Constraints**: Change must not affect the `classic` digest format path  
**Scale/Scope**: Single file, two code locations

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Separation of Concerns | ✅ Pass | Change is isolated to `claude_summarizer.py`; no new cross-module dependencies |
| II. Secrets Management | ✅ Pass | No new secrets or config — existing `ANTHROPIC_API_KEY` unchanged |
| III. Typed Data Transfer | ✅ Pass | `Idea`, `Summary` dataclasses unchanged; no new inter-module types |
| IV. Reliability & Rate Limiting | ✅ Pass | Retry logic and rate limiter untouched |
| V. Observability | ✅ Pass | Existing `structlog` log calls unchanged; `idea_count` log field remains valid |

No violations. No complexity tracking required.

## Project Structure

### Documentation (this feature)

```text
specs/001-recall-integration/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
└── tasks.md             ← Phase 2 output (/speckit.tasks)
```

### Source Code (affected files only)

```text
agent/summarizer/claude_summarizer.py   ← _IDEA_SYSTEM_PROMPT_TEMPLATE, _parse_ideas()
tests/unit/test_summarizer.py           ← new idea-format test cases
```

No new files. No new directories. No data model changes.

---

## Phase 0: Research

*See [research.md](research.md) for full findings.*

**Summary**: No external unknowns to resolve. The change is entirely internal — a prompt string and a parser fallback. Research focused on prompt design best practices for always-on extraction and what the correct parser fallback should be when Claude's response is unparseable.

---

## Phase 1: Design & Contracts

### Change 1 — `_IDEA_SYSTEM_PROMPT_TEMPLATE`

**Location**: `agent/summarizer/claude_summarizer.py`, lines 26–46

**Current behaviour**: Instructs Claude to output a fixed "No High-Signal Content" stub when it finds no relevant ideas.

**New behaviour**: Instructs Claude to always extract all significant ideas from the newsletter text. Where an idea relates to the user's portfolio or interests, Claude notes the connection inline within the idea's summary text. The "no relevant ideas" escape hatch is removed entirely.

**Prompt change summary**:
- Remove: `"For each idea that is relevant to the reader's holdings, interests, or that would make a well-informed person meaningfully more aware"` — the relevance gate phrase
- Replace with: unconditional instruction to extract all discrete, significant ideas from the text
- Remove: the entire `"If no ideas are relevant, output exactly: IDEA: No High-Signal Content / Nothing in this newsletter warrants your attention."` block
- Add: instruction that where an idea connects to the reader's holdings or interests, that connection should be noted in the idea's summary text

### Change 2 — `_parse_ideas()` fallback

**Location**: `agent/summarizer/claude_summarizer.py`, lines 86–90

**Current behaviour**: When Claude's response contains no parseable `IDEA:` blocks, returns a single `Idea(title="No High-Signal Content", ...)` stub — this masks parse errors as content judgments.

**New behaviour**: When Claude's response contains no parseable `IDEA:` blocks, returns a single `Idea(title="Content Unavailable", summary_text="Unable to extract ideas from this newsletter.")` — this accurately represents a parse failure, not a relevance decision.

### Change 3 — `summarize_as_ideas()` docstring

**Location**: `agent/summarizer/claude_summarizer.py`, lines 210–228

Update the docstring: remove "Filters ideas for relevance" language. Replace with accurate description: profile is injected for framing only; all significant ideas are always surfaced.

### No data model changes

`Idea`, `Summary`, `DigestEntry`, and all other dataclasses in `agent/utils/models.py` are unchanged.

### No contract changes

No external interfaces exposed. This is a pure internal prompt behaviour change.

### Test additions

New test cases to add to `tests/unit/test_idea_format.py`:

1. `_parse_ideas()` with empty response returns `Idea(title="Content Unavailable", ...)` — not "No High-Signal Content"
2. `_parse_ideas()` with valid IDEA blocks returns the correct ideas (regression guard)
3. `_IDEA_SYSTEM_PROMPT_TEMPLATE` does not contain the string "No High-Signal Content" — prompt guard
4. `_IDEA_SYSTEM_PROMPT_TEMPLATE` does not contain "warrants your attention" — prompt guard
5. `summarize_as_ideas()` with a mocked Claude response for an off-topic newsletter returns a Summary with at least one real idea (integration-level check)
