# Research: Filtering Rollback — Always-On Newsletter Digest

**Feature**: `001-recall-integration` | **Date**: 2026-04-15

## Overview

No external unknowns required resolution. All research is internal — focused on (1) the correct replacement prompt design and (2) the correct parser fallback when Claude returns an unparseable response.

---

## Decision 1: Prompt design for always-on idea extraction

**Decision**: Remove the relevance gate from `_IDEA_SYSTEM_PROMPT_TEMPLATE`. Replace "For each idea that is **relevant** to the reader's holdings, interests, or that would make a well-informed person meaningfully more aware" with an unconditional extraction instruction: identify and output every discrete, significant idea in the newsletter.

**Rationale**: The relevance gate is the root cause of the regression. Claude interprets the gate as permission to skip a newsletter entirely. Removing it forces Claude to always enumerate ideas. The profile section remains injected so Claude can note portfolio connections inline — this is additive context, not a filter.

**Alternatives considered**:
- Soften the gate (e.g., "prefer ideas relevant to the reader but include others") — rejected because "prefer" is too ambiguous and Claude may still suppress content it deems marginally relevant.
- Remove the profile section entirely — rejected because the user wants portfolio connections noted inline (FR-004, clarification Q1-A).

---

## Decision 2: Parser fallback when Claude response is unparseable

**Decision**: Replace the `"No High-Signal Content"` fallback Idea with `Idea(title="Content Unavailable", summary_text="Unable to extract ideas from this newsletter.")`.

**Rationale**: The original fallback conflates two distinct cases: (a) Claude judging no ideas relevant (prompt-level decision) and (b) Claude returning a response that the regex parser cannot split into IDEA blocks (parse-level failure). After removing case (a) from the prompt, the only remaining trigger for the fallback is case (b) — a genuine parse error. Renaming it to "Content Unavailable" makes the failure mode explicit and distinguishable in logs and digest output.

**Alternatives considered**:
- Return an empty tuple and let the caller handle it — rejected because `Summary.ideas` being an empty tuple would require changes in the builder and templates.
- Retry the API call on parse failure — rejected as scope creep; the existing retry logic already handles transient API errors. A parse failure on a successful API response is rare and better surfaced explicitly.

---

## Decision 3: Prompt wording for inline portfolio mentions

**Decision**: Add to the prompt: "Where an idea directly relates to the reader's holdings or interests, note the connection briefly within the idea's summary text."

**Rationale**: This is the minimal addition that satisfies FR-004 and clarification Q1 (prompt-only, no post-processing). It gives Claude latitude to mention relevance naturally rather than requiring structured output that would need post-processing.

**Alternatives considered**:
- No instruction at all (rely on profile context implicitly) — rejected because Claude may not mention relevance unless explicitly instructed.
- Structured tag output like `[PORTFOLIO]` — rejected per clarification Q1 (no post-processing or labeling).
