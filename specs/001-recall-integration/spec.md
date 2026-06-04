# Feature Specification: Filtering Rollback — Always-On Newsletter Digest

**Feature Branch**: `001-recall-integration`  
**Created**: 2026-04-15  
**Status**: Draft  

## Overview

The current idea-based digest silently drops newsletters it considers "not relevant," producing "No High-Signal Content / Nothing in this newsletter warrants your attention." output. This is too aggressive — the user wants every newsletter summarized regardless of whether its content aligns with their stated portfolio, watchlist, or interests. User profile signals should guide how ideas are framed and ordered, not whether a newsletter is shown at all.

---

## Clarifications

### Session 2026-04-15

- Q: When portfolio-relevant ideas are mixed with general ideas, how should relevance be surfaced in the output? → A: Prompt-level framing only — Claude is instructed to mention portfolio connections in the idea text where applicable; no post-processing, reordering, or labeling of output ideas.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Every Newsletter Gets a Digest Entry (Priority: P1)

The user runs the digest agent and receives a summary for every newsletter in their inbox — including those outside their stated investment portfolio or interest areas. The profile/watchlist context still shapes how ideas are framed (e.g., surfacing portfolio relevance first), but no newsletter is silently dropped.

**Why this priority**: This is a regression fix. The current behavior actively harms the user by hiding content they subscribed to and wanted. Restoring full coverage is the only goal of this feature.

**Independent Test**: Run the agent against a newsletter email that does not match any ticker or interest in the user profile. Confirm a meaningful summary appears in the digest output rather than the "No High-Signal Content" message.

**Acceptance Scenarios**:

1. **Given** a newsletter email unrelated to the user's portfolio or interests, **When** the digest agent processes it, **Then** the output contains a non-trivial summary of the email's actual content.
2. **Given** a newsletter email only partially overlapping with the user's interests, **When** the digest agent processes it, **Then** all significant ideas from the email are surfaced — not just the matching ones.
3. **Given** a newsletter email aligned with the user's portfolio, **When** processed, **Then** Claude notes the portfolio connection within the idea's summary text where applicable — profile context is preserved for framing only, not used to suppress or reorder content.
4. **Given** a genuinely sparse or empty newsletter (e.g., a plain "holiday break" notice), **When** the agent processes it, **Then** the output accurately reflects that there is little content — but this judgment is based on content volume, not interest mismatch.

---

### Edge Cases

- What if a newsletter body is entirely boilerplate (unsubscribe text, navigation labels, no editorial content)? The summary should reflect that there is minimal content — this is acceptable because the judgment is about content volume, not topic alignment.
- What if the user has no profile configured? The agent should summarize all ideas with no filtering applied — same behavior as today when `user_profile.yaml` is absent.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The digest agent MUST produce a non-empty, meaningful summary for every newsletter processed, regardless of whether its content matches the user's stated portfolio, watchlist, or interest areas.
- **FR-002**: The "No High-Signal Content / Nothing in this newsletter warrants your attention" output path MUST be removed from the idea-based digest format.
- **FR-003**: The user profile (portfolio, watchlist, interests) MUST continue to be injected into the summarization prompt to provide framing context, but MUST NOT be used to suppress ideas or declare a newsletter irrelevant.
- **FR-004**: The idea-based digest MUST surface all significant ideas from the newsletter text. Where an idea connects to the user's portfolio or interests, the prompt MUST instruct Claude to note that connection within the idea's text — no post-processing, sorting, or labeling of the output is required.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every newsletter processed by the agent produces a digest entry with at least one idea — the "No High-Signal Content" output no longer appears in any digest output.
- **SC-002**: Newsletters that previously showed relevant ideas continue to show those ideas at the same or better quality — no regressions in the existing idea extraction behavior.
- **SC-003**: A newsletter whose content has zero overlap with the user's portfolio or interests produces a summary that accurately represents what the newsletter actually covered.

---

## Assumptions

- The existing `user_profile.yaml` signals (portfolio, watchlist, interests) remain in the summarization prompt — they are retained for framing, not removed.
- This change only affects the `idea_based` digest format. The `classic` format is unchanged.
- Sparse newsletters (little editorial content) may still produce short or minimal digests — this is correct behavior and distinct from interest-based suppression.
