# Feature Specification: Newsletter Digest Agent Enhancements

**Feature Branch**: `001-digest-agent-enhancements`
**Created**: 2026-03-19
**Updated**: 2026-03-19
**Status**: Draft
**Input**: Enhance newsletter digest agent with per-sender rules (pass-through for digest newsletters), strict image filtering (graphs/charts/memes only), unread-based inbox fetching, post-delivery email trashing, and rate-limited batch digest sending

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Per-Sender Processing Rules (Pre-Digested Pass-Through) (Priority: P1)

Certain newsletters (Superhuman, The Rundown AI, The Code) are themselves curated digests — they arrive already structured with headlines, summaries, and sections. When the agent re-summarizes them, it loses the original structure and produces inferior output. These senders should be configured to pass their content through to the digest unchanged. Other newsletters (non-digest style) continue to be AI-summarized as before. The configuration must support a per-sender `mode` that can be set to `pass_through` or `summarize`.

**Why this priority**: This is the root cause of the user's dissatisfaction with output quality. Getting this right for named senders is the highest-value fix and establishes the per-sender rule system that all other rules build on.

**Independent Test**: Configure Superhuman, The Rundown AI, and The Code as `pass_through` senders. Run the agent against one unread email from each. Verify the digest output contains the newsletter's original text structure — not an AI-generated summary.

**Acceptance Scenarios**:

1. **Given** a sender configured as `pass_through`, **When** the agent processes an email from that sender, **Then** the original content (text, headings, bullet points) is included in the digest without AI summarization
2. **Given** a sender configured as `summarize`, **When** the agent processes an email from that sender, **Then** the content is AI-summarized using the configured word target
3. **Given** the config lists Superhuman, The Rundown AI, and The Code as `pass_through`, **When** the agent runs, **Then** all three are processed in pass-through mode by default
4. **Given** a sender not in the config list, **When** an email arrives from that sender, **Then** the agent skips it — unlisted senders are never processed
5. **Given** a mix of pass-through and summarize senders in one run, **When** the digest is assembled, **Then** both types appear in the same digest email with their respective content intact

---

### User Story 2 - Strict Content-Only Image Filtering (Priority: P1)

The current image extractor passes through banner images, logos, branding graphics, sponsor/advertiser images, and social media icons. The user only wants graphs, charts, and memes to appear in the digest. All decorative, branding, and advertising images must be filtered out, even if they pass the current size and CDN checks.

**Why this priority**: Irrelevant images clutter the digest and make it harder to read. Branding/ad images add no informational value. This affects every newsletter and digest entry.

**Independent Test**: Run the agent against a newsletter known to have a banner image and at least one chart (e.g., a data-focused newsletter). Verify the output digest contains the chart but not the banner.

**Acceptance Scenarios**:

1. **Given** a newsletter with a banner/header image at the top, **When** the agent extracts images, **Then** the banner is excluded from the digest
2. **Given** a newsletter with a sender logo or brand icon, **When** the agent extracts images, **Then** the logo/icon is excluded
3. **Given** a newsletter with a sponsored content block containing an advertiser image, **When** the agent extracts images, **Then** the advertiser image is excluded
4. **Given** a newsletter with social media icons (Twitter/X, LinkedIn, Instagram), **When** the agent extracts images, **Then** all social icons are excluded
5. **Given** a newsletter containing a graph or chart (e.g., a line chart, bar chart, data visualization), **When** the agent extracts images, **Then** the chart is included in the digest
6. **Given** a newsletter containing a meme (an image with overlaid text in a recognizable meme format), **When** the agent extracts images, **Then** the meme is included in the digest
7. **Given** a newsletter with no graphs, charts, or memes, **When** the agent processes it, **Then** no images section appears in the digest output

---

### User Story 3 - Unread Inbox Processing with Trash-After-Delivery (Priority: P1)

The current agent fetches emails from the last 24 hours. The user has accumulated ~100 unread emails from monitored senders. The agent should instead fetch all unread emails from configured senders in the inbox (not time-bounded), process them in batches of 10 per digest email, send each digest email, and then move the processed emails to Gmail trash. This keeps the inbox clean while preserving emails in trash for 30 days for reference.

**Why this priority**: The unread backlog means the current 24-hour window misses most emails. Trash-after-delivery is the desired state management behavior once digests are confirmed delivered.

**Independent Test**: With 15+ unread emails from one sender in the inbox, run the agent. Verify: (1) exactly 2 digest emails are sent (10 + 5), (2) all 15 source emails are moved to trash, (3) no emails are trashed if the digest send fails.

**Acceptance Scenarios**:

1. **Given** 25 unread emails from configured senders in the inbox, **When** the agent runs, **Then** 3 digest emails are sent (10 + 10 + 5) before any trashing occurs
2. **Given** a digest email is successfully delivered, **When** delivery is confirmed, **Then** the source emails included in that digest batch are moved to Gmail trash
3. **Given** a digest email delivery fails, **When** the failure is detected, **Then** the source emails from that batch are NOT moved to trash and remain unread in the inbox
4. **Given** emails are moved to trash, **When** a user checks Gmail trash, **Then** the original emails are present and readable for up to 30 days
5. **Given** 0 unread emails from a configured sender, **When** the agent runs, **Then** no digest is sent for that sender and no error is reported

---

### User Story 4 - Rate-Limited Batch Digest Processing (Priority: P2)

With ~100 unread emails to process in a single run, the agent must send multiple digest emails and make many AI summarization calls. The system must pace itself to stay within Gmail API and AI service rate limits — spreading out requests over time when necessary — rather than hammering both services at once and failing mid-run.

**Why this priority**: A single run that processes 100 emails unconstrained will hit rate limits, fail partway through, and leave the inbox in a partially-processed inconsistent state. Rate limiting ensures the full backlog is processed reliably.

**Independent Test**: Seed the inbox with 30+ unread emails from configured senders. Run the agent. Verify all emails are eventually processed without any rate-limit errors appearing in the logs, and all processed batches result in delivered digests.

**Acceptance Scenarios**:

1. **Given** 100 unread emails from monitored senders, **When** the agent runs, **Then** it sends 10 digest emails (10 emails per digest) in sequence, pacing calls to respect limits
2. **Given** a rate limit or transient error occurs mid-run, **When** the error is detected, **Then** the agent pauses, retries the affected operation, and continues processing remaining batches
3. **Given** a batch is mid-processing when a rate limit is hit, **When** the run resumes or retries, **Then** already-delivered batches are not re-processed (no duplicate digests)
4. **Given** the agent is running with a large backlog, **When** viewed by the user, **Then** progress is logged so the user can see how many batches have been sent and how many remain

---

### User Story 5 - Redesigned Email Template (Priority: P3)

The current email template is functional but visually plain. The digest should look polished and professional — better typography, clear visual hierarchy between newsletter entries, and a layout that works well on both desktop and mobile email clients.

**Why this priority**: Visual quality affects how much the user actually reads and acts on the digest. This is a quality-of-life improvement after the core processing logic is correct.

**Independent Test**: Render a test digest with 3+ entries (mix of pass-through and summarized) on Gmail web and on a mobile device. Verify: clear separation between entries, readable fonts, no layout breakage, tappable links.

**Acceptance Scenarios**:

1. **Given** a digest with multiple entries, **When** opened on desktop, **Then** each entry is visually separated and the sender name + headline are scannable without reading the full content
2. **Given** a digest opened on a mobile device (< 600px), **When** the user views it, **Then** text is readable without horizontal scrolling and any images scale to fit the screen
3. **Given** a digest with "Further Reading" links, **When** the user views the section, **Then** links appear as clearly tappable buttons or styled elements — not plain inline text
4. **Given** a digest with a table of contents at the top, **When** the user taps a TOC entry, **Then** the email scrolls to that newsletter's section

---

### Edge Cases

- What happens when an email from a pass-through sender is extremely long? Content is truncated at the nearest sentence boundary within 500 words, with a "read original" link appended. The 500-word cap applies equally to all pass-through entries regardless of original length.
- What happens when a batch of 10 emails includes both pass-through and summarize senders? Both types are included in the same digest email; no restriction on mixing types per batch
- What happens when image classification is uncertain (cannot determine if image is a chart, banner, or something else)? The image is excluded by default (opt-in, not opt-out policy for images)
- What happens if trashing an email fails after a digest is sent? The email is already marked as read (step 1 of FR-013), so it is excluded from future runs by the "unread only" filter. The trash failure is logged as a warning; the email sits in inbox as read and will not be re-digested.
- What happens when the same unread email is fetched twice in two consecutive runs before it can be trashed? The email is processed only once per run; trashing after delivery prevents re-processing in subsequent runs
- What happens when there are more than 10 emails from one sender and the sender is `pass_through`? Each batch of 10 is sent as a separate digest email regardless of sender type

## Requirements *(mandatory)*

### Functional Requirements

**Per-Sender Processing Rules**

- **FR-001**: The newsletter configuration MUST support a per-sender `mode` field with values `pass_through` (no AI summarization, preserve original structure) and `summarize` (AI summarization, existing behavior)
- **FR-002**: Senders not present in the configuration MUST be ignored — the agent only processes explicitly listed senders
- **FR-003**: Superhuman, The Rundown AI, and The Code MUST be pre-configured as `pass_through` senders in the default configuration
- **FR-004**: Pass-through content MUST preserve the original text structure including section headers, bullet points, numbered lists, and paragraph breaks, truncated at the nearest sentence boundary within 500 words; a "read original" link MUST be appended when truncation occurs
- **FR-005**: Per-sender overrides MUST support `summary_word_target`, `include_images`, `max_images` in addition to `mode`

**Image Filtering**

- **FR-006**: The image extraction pipeline MUST exclude all images classified as: banner/header images, logos, brand icons, advertiser/sponsor images, and social media platform icons; classification MUST use HTML context heuristics only (alt text, class/id names, image dimensions, position in email) — no AI vision API calls
- **FR-007**: The image extraction pipeline MUST include images classified as: graphs, charts, data visualizations, and memes (images with overlaid text in meme format); classification MUST use the same HTML context heuristics
- **FR-008**: When image classification is ambiguous or uncertain, the image MUST be excluded (exclude-by-default policy)
- **FR-009**: If no qualifying images (graphs, charts, memes) are found for a newsletter entry, the images section MUST be omitted entirely from that entry's output

**Unread Inbox Fetching**

- **FR-010**: The agent MUST fetch all unread emails from configured senders in the inbox, without any time-based lookback window
- **FR-011**: Fetched emails MUST be filtered to only those that are unread AND in the inbox (not already in trash, spam, or archive)
- **FR-012**: The agent MUST process all fetched emails sorted chronologically (oldest first) across all configured senders, grouped into batches of up to 10 per digest email (final batch may contain fewer than 10)

**Trash After Delivery**

- **FR-013**: After each digest email batch is confirmed as successfully delivered, the agent MUST: (1) mark all source emails in that batch as read in Gmail, then (2) move them to Gmail trash
- **FR-013a**: Marking as read MUST occur before attempting to trash, so that even if trash fails the emails are excluded from future runs by the "unread only" fetch filter
- **FR-014**: If delivery of a digest email fails, the source emails from that batch MUST NOT be marked as read, MUST NOT be moved to trash, and MUST remain unread in the inbox for retry on the next run
- **FR-015**: Trashed emails MUST be accessible in Gmail trash for up to 30 days (standard Gmail trash policy; no additional retention action required)

**Polling & Scheduling**

- **FR-016**: The agent MUST run continuously, polling for unread emails from configured senders every 4 hours
- **FR-017**: The poll interval MUST be configurable (default: 4 hours) in the newsletter configuration
- **FR-018**: At each poll, the agent MUST process all currently unread emails from configured senders, regardless of when they arrived
- **FR-019**: If no unread emails are found at a poll interval, the agent MUST log this and wait until the next poll without sending a digest

**Rate-Limited Batch Processing**

- **FR-020**: The agent MUST pace AI summarization requests to avoid exceeding the configured rate limit (default: no more than 1 summarization request every 2 seconds)
- **FR-021**: The agent MUST handle Gmail API `429 Too Many Requests` responses gracefully via exponential backoff retry (Gmail's per-user quota of 1M calls/day is non-constraining for this workload; no proactive pacing is required, but transient errors must not cause data loss)
- **FR-022**: On a transient rate-limit error or API failure, the agent MUST retry with exponential backoff before failing a batch
- **FR-023**: Each successfully delivered batch MUST be logged with a count of emails processed and remaining
- **FR-024**: Already-delivered batches MUST NOT be re-sent if the agent restarts or retries after a mid-run failure

**Template & Presentation**

- **FR-026**: The digest HTML template MUST be responsive and render correctly on screens narrower than 600px
- **FR-027**: Each digest entry MUST display the newsletter sender's display name (from email "From" header) prominently, falling back to the raw email address
- **FR-028**: The digest MUST include a table of contents at the top linking to each newsletter entry within the email
- **FR-029**: "Further Reading" links MUST be styled as visually distinct, tappable elements
- **FR-030**: Pass-through entries MUST be visually distinguished from summarized entries in the digest (e.g., a label or different styling)

### Key Entities

- **SenderConfig**: Per-sender rule set; attributes: sender address(es), display name, mode (`pass_through` | `summarize`), summary_word_target, include_images, max_images
- **DigestBatch**: A group of up to 10 processed emails assembled into one digest email; attributes: batch_index, email_ids, total_batches
- **DigestEntry** (extended): Existing model extended with is_pass_through (bool), display_name (str), gmail_message_id (str)
- **Email** (extended): Existing model extended with gmail_message_id (str), is_pass_through (bool)

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Pass-through senders (Superhuman, The Rundown AI, The Code) produce digest entries that contain the original newsletter's section structure in 100% of runs
- **SC-002**: Zero branding, banner, logo, sponsor, or social media icon images appear in any digest output
- **SC-003**: All unread emails from configured senders in the inbox are fetched and processed in a single agent run, regardless of age
- **SC-004**: Source emails are moved to trash if and only if their corresponding digest batch was successfully delivered — no emails are trashed due to unrelated failures
- **SC-005**: A backlog of 100 unread emails produces exactly 10 digest emails of 10 entries each during a single poll, with no rate-limit failures during processing
- **SC-008**: The agent runs continuously and automatically polls every 4 hours without requiring manual intervention; new unread emails are processed at the next poll after they arrive
- **SC-006**: The digest renders without layout issues on Gmail web and on a mobile device at 375px width
- **SC-007**: Zero regressions — newsletters configured as `summarize` continue to be summarized correctly with all existing behavior preserved

## Clarifications

### Session 2026-03-19

- Q: How should the agent classify images (heuristics vs AI vision vs hybrid)? → A: HTML context heuristics only — no AI vision API calls. Use alt text, class/id names, image dimensions, position in email, and surrounding HTML structure to classify images.
- Q: How should the agent prevent re-processing emails that were delivered but not trashed? → A: Mark the email as read in Gmail immediately after successful delivery. If trash fails, the email becomes read and is naturally excluded by the "unread only" fetch filter on subsequent runs.
- Q: How should the agent be triggered? → A: Continuous polling every 4 hours. At each poll, the agent processes all unread emails from configured senders. The first poll clears the existing backlog; subsequent polls handle new arrivals.
- Q: How should emails be grouped into digest batches? → A: Mix all senders chronologically — up to 10 emails per digest regardless of sender. Emails from any configured sender are sorted oldest-first and batched together.
- Q: What is the word cap for pass-through content per newsletter entry? → A: 500 words. Pass-through content is truncated at the nearest sentence boundary within 500 words, with a "read original" link appended.

## Assumptions

- "Graphs, charts, and memes" classification uses HTML context heuristics only: alt text content, image class/id names, surrounding caption or heading text, image dimensions (charts tend to be wide/landscape, logos/icons tend to be small and square), and position within the email body (top-of-email images are typically banners; inline images within article sections are more likely to be content). No AI vision API calls are used for image classification.
- Display names for senders will be sourced from the email "From" header and fall back to the raw email address
- The redesigned template will remain inline-CSS-only for maximum email client compatibility; no external stylesheets or JavaScript
- "Confirmed delivery" means the SMTP send call completed without error; no read-receipt or delivery confirmation is required before trashing
- Batch ordering within a poll: all unread emails from all configured senders are sorted chronologically (oldest first) and grouped into batches of 10 regardless of sender — senders are not separated into individual digests
- The configuration will list sender email addresses (not display names) as the matching key for per-sender rules; multiple addresses for the same newsletter brand can be listed as separate entries
- Rate limits referenced: Gmail API write quota (~10,000 units/day; trash = 5 units/message) and AI service rate limits (existing 0.5 req/sec token bucket)
- The agent runs continuously (long-lived process) polling every 4 hours; the poll interval is configurable in `config/newsletters.yaml`
- A poll that processes a 100-email backlog will take approximately 15–20 minutes when paced to respect rate limits; this is acceptable behavior for the initial catch-up poll
