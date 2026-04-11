# Feature Specification: Idea-Based Digest Format with No Links

**Feature Branch**: `001-idea-digest-format`  
**Created**: 2026-04-08  
**Status**: Draft  
**Input**: User description: "The links passthrough is something that is not really clicking for me. I think it adds more clutter and very little value to the newsletter digests I think we should take them out. Also for the digest of the actual emails lets break it down like this. Instead of x words total or y% of the original email content how about we make this more intelligent. Break the content of the emails down into individual ideas; for each idea give me a summary so that the important concepts and insights are presented with minimal fluff. Important is gauged as pertaining to one of my stocks, interests, topics, or just something that would make me, the reader, a more informed individual. For agent generating the summary: you are an informed individual, someone who is plugged in into the world about many topics and want others to be informed like you. You are also a shrewd advisor who does not sugarcoat things or add fluff to your communications. You present information in a grounded, rational, and succinct way."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Idea-by-Idea Digest Summary (Priority: P1)

When the digest agent processes a newsletter email, instead of producing a running summary with word/percentage stats, it breaks the email content into discrete ideas. For each idea it generates a tight, opinionated summary that surfaces the insight without filler. Only ideas that are relevant — to the reader's holdings, tracked topics, or general informedness — are included.

**Why this priority**: This is the core change to the digest experience. Every other story depends on this new output shape being in place.

**Independent Test**: Run the agent against a single newsletter email and confirm the output contains a list of labeled ideas, each with a concise summary and no word-count metadata.

**Acceptance Scenarios**:

1. **Given** a newsletter email with five distinct topics, **When** the agent produces the digest, **Then** the output contains up to five idea entries, each with a title and a 1–3 sentence summary, and no "X words / Y% of original" statistics.
2. **Given** a newsletter email where only two of five topics are relevant to the reader's interests, **When** the agent produces the digest, **Then** only those two ideas appear in the output; irrelevant topics are omitted.
3. **Given** a newsletter email with a single long article on one topic, **When** the agent produces the digest, **Then** the output contains one idea entry with a summary that captures the key insight in plain, direct language.

---

### User Story 2 - Remove Links Passthrough (Priority: P2)

All hyperlinks that previously appeared in the digest output are stripped. The digest contains no clickable or literal URLs — only text.

**Why this priority**: This is a presentational cleanup with no dependencies. It can ship independently and immediately improves readability.

**Independent Test**: Run the agent against any newsletter email containing links and confirm the digest output contains no URLs.

**Acceptance Scenarios**:

1. **Given** a newsletter email with embedded article links, **When** the agent produces the digest, **Then** no URLs appear anywhere in the digest output.
2. **Given** a newsletter email where every paragraph contains a "read more" link, **When** the agent produces the digest, **Then** the digest text flows cleanly without link artifacts or brackets.

---

### User Story 3 - Relevance-Filtered Idea Selection (Priority: P3)

The agent applies a relevance filter when deciding which ideas to include. An idea qualifies if it pertains to the reader's tracked stocks, stated interests, or any topic that increases general awareness of important world events, market dynamics, or other high-signal information.

**Why this priority**: Builds on P1 (idea decomposition) by making the selection intelligent rather than exhaustive. Delivers a tighter, higher signal-to-noise digest.

**Independent Test**: Provide a newsletter with a mix of clearly relevant (e.g., a tracked stock's earnings) and clearly irrelevant content (e.g., a recipe). Confirm only the relevant idea is surfaced.

**Acceptance Scenarios**:

1. **Given** the reader tracks specific stocks and interests, **When** a newsletter covers a topic directly tied to one of those stocks, **Then** that idea is always included in the digest.
2. **Given** a newsletter covering general world news with no direct tie to tracked items, **When** the agent evaluates relevance, **Then** ideas that would make a well-informed person meaningfully more aware are included; trivia and filler are excluded.

---

### Edge Cases

- What happens when a newsletter email contains only links and no substantive text content? The digest should produce a minimal or empty output rather than hallucinating ideas.
- What happens when every idea in a newsletter is deemed irrelevant? The digest entry for that newsletter should be a brief note that no high-signal content was found, rather than being silently empty.
- What happens when a single newsletter article spans multiple overlapping ideas that are hard to separate? The agent should group closely related points under one idea entry rather than producing redundant micro-entries.
- How does the system handle emails that are already very short (one or two sentences)? They should be treated as a single idea without forced decomposition.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The digest MUST decompose each newsletter email into discrete ideas before summarizing, rather than summarizing the email as a whole.
- **FR-009**: A single global config flag MUST control which summary format is active — the new idea-based format or the previous format. Switching the flag produces the alternate output without any other changes required.
- **FR-002**: Each idea entry MUST contain a concise title and a 1–3 sentence summary that presents the core insight directly, without hedging, padding, or transitional filler.
- **FR-003**: The agent MUST adopt the persona of a well-informed, plugged-in individual who communicates in a grounded, rational, and succinct style — not a neutral summarizer.
- **FR-004**: The digest MUST NOT include word counts, character counts, percentage-of-original metrics, or any other quantitative compression statistics in the output.
- **FR-005**: The digest MUST NOT include any content-passthrough URLs or hyperlinks in the output (e.g., article links, "Further Reading" links, "read more" links sourced from the newsletter body). Structural navigation links generated by the digest system itself (e.g., a "View Original Email" link pointing to the source message) are out of scope for this requirement.
- **FR-006**: The agent MUST filter ideas by relevance, including only those that pertain to the reader's tracked stocks, stated interests, or that would meaningfully inform a broadly aware individual.
- **FR-007**: When no relevant ideas are found in a newsletter, the digest MUST produce a brief, explicit note to that effect rather than an empty or absent entry.
- **FR-008**: The agent MUST NOT fabricate or infer ideas that are not present in the source email content.

### Key Entities

- **Idea**: A discrete, self-contained concept or claim extracted from a newsletter email. Has a title and a summary. Is either included or excluded based on relevance.
- **Digest Entry**: The agent's output for a single newsletter email. Contains zero or more ideas, and no metadata about word count or compression ratio.
- **Relevance Signal**: The criteria used to decide if an idea is included — reader's tracked stocks, stated interests, or general informedness value. Sourced from `config/user_profile.yaml`, which already contains `interests`, `portfolio` (with ticker + company name), `watchlist`, and `custom_prompts` sections.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The digest output contains zero URLs across all processed emails.
- **SC-002**: The digest output contains zero word-count or percentage-of-original statistics.
- **SC-003**: Each included idea in the digest is representable as a discrete concept — a human reviewer can confirm no two idea entries in the same email digest cover the same point.
- **SC-004**: For a newsletter with clearly mixed content (relevant + irrelevant), the agent excludes irrelevant ideas in at least 90% of manual spot-check cases.
- **SC-005**: Each idea summary is 1–3 sentences and contains no filler phrases ("it is worth noting", "this is significant because", "in conclusion", etc.) — verifiable by manual review of a sample output. SC-005 is the sole verifiable proxy for FR-003 persona compliance; persona quality is inherently qualitative beyond this banned-phrase check.

## Clarifications

### Session 2026-04-08

- Q: Does `config/user_profile.yaml` already exist with stocks/interests, or does this feature need to define that structure? → A: Already exists — `config/user_profile.yaml` contains `interests`, `portfolio` (ticker + name), `watchlist`, and `custom_prompts`.
- Q: Full replacement of the current summary format, or opt-in per source/global toggle? → A: Global toggle — a single config flag switches between the old format and the new idea-based format, enabling before/after comparison.
- Q: Maximum number of ideas per email, or unbounded? → A: Unbounded — agent surfaces as many relevant ideas as it finds; no hard cap.

## Assumptions

- The reader's tracked stocks and interests are already captured in `config/user_profile.yaml` under `interests`, `portfolio`, `watchlist`, and `custom_prompts`. This feature reads from that file but does not modify its structure.
- "General informedness" relevance is a judgment call delegated to the agent's persona. There is no exhaustive list of qualifying topics — the agent applies the standard: "would a plugged-in, informed individual consider this worth knowing?"
- The removal of links applies to the digest output only. The original emails are not modified.
- Idea decomposition is performed per-email, not across the full digest batch. Each email is processed independently.
