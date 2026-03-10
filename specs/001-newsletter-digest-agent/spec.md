# Feature Specification: Newsletter Digest Agent

**Feature Branch**: `001-newsletter-digest-agent`
**Created**: 2026-03-09
**Status**: Draft
**Input**: User description: "Newsletter Digest Agent — an AI-powered Python agent that automatically fetches newsletters from Gmail via OAuth 2.0, extracts and cleans HTML content, summarizes each newsletter using the Claude API (~200-250 words each), assembles a consolidated HTML digest email, and delivers it to the user's inbox on a daily schedule."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect Gmail and Run First Digest (Priority: P1)

A user configures the agent with their Gmail account credentials and a list of newsletter senders. They run the agent manually and receive a single consolidated digest email containing summaries of all newsletters received in the past 24 hours.

**Why this priority**: This is the core value proposition — without the ability to fetch, summarize, and deliver a digest, nothing else matters. All other features depend on this working end-to-end.

**Independent Test**: Can be fully tested by running the agent with a pre-configured Gmail account containing newsletter emails and verifying that a digest email lands in the inbox with one summary per newsletter.

**Acceptance Scenarios**:

1. **Given** a configured Gmail account with 5 newsletter emails in the past 24 hours, **When** the agent runs, **Then** the user receives one digest email containing 5 summaries, each 200–250 words, grouped by sender.
2. **Given** the Gmail account has no newsletters matching the sender allowlist, **When** the agent runs, **Then** no digest email is sent and the agent logs that no newsletters were found.
3. **Given** a newsletter email contains only images with no extractable text, **When** the agent processes it, **Then** the digest includes a placeholder entry noting the newsletter could not be summarized, and processing continues for the remaining newsletters.

---

### User Story 2 - Dry Run Without Sending Email (Priority: P2)

A user wants to preview what the digest would look like without actually sending an email, to verify configuration and content quality before enabling the scheduled run.

**Why this priority**: Essential for initial setup confidence and ongoing debugging. Users must be able to validate behavior safely before committing to live email delivery.

**Independent Test**: Can be fully tested by running the agent with the dry-run flag and confirming that summaries are printed or logged, no email is sent, and the exit code indicates success.

**Acceptance Scenarios**:

1. **Given** the agent is invoked with the `--dry-run` flag, **When** the agent completes, **Then** digest content is output to the terminal or log, and no email is dispatched.
2. **Given** dry-run mode is active and an API error occurs during summarization, **When** that error is encountered, **Then** the error is reported clearly and processing continues for remaining newsletters.

---

### User Story 3 - Scheduled Daily Digest Delivery (Priority: P3)

A user configures the agent to run automatically every morning without any manual intervention, receiving their digest email before they start their day.

**Why this priority**: Automation is the long-term value of the agent. Manual invocation is fine for setup, but the scheduled mode is what makes it a persistent daily utility.

**Independent Test**: Can be tested by starting the scheduler process, waiting for the configured trigger time, and confirming a digest email is received without any manual action.

**Acceptance Scenarios**:

1. **Given** the scheduler is running and configured to trigger at 6:30 AM, **When** 6:30 AM arrives, **Then** the agent executes a full run and the digest email is delivered within 10 minutes of the trigger time.
2. **Given** the scheduler is running and a run completes with errors, **When** the next trigger fires at the scheduled time, **Then** a new run begins normally regardless of the previous run's outcome.

---

### User Story 4 - Newsletter Detection via Allowlist and Keywords (Priority: P2)

A user maintains a YAML configuration file listing trusted newsletter senders and subject keywords. The agent uses this to automatically filter which emails qualify as newsletters, ignoring all other inbox messages.

**Why this priority**: Without accurate filtering, the agent may summarize non-newsletter emails or miss newsletters entirely. Correct detection is foundational to digest quality.

**Independent Test**: Can be tested by providing a mock inbox with a mix of newsletter and non-newsletter emails, running the agent, and confirming only allowlisted senders or keyword-matched subjects appear in the digest.

**Acceptance Scenarios**:

1. **Given** an email from a sender on the allowlist, **When** the agent scans the inbox, **Then** that email is included in the digest regardless of subject line content.
2. **Given** an email not on the allowlist but whose subject contains a configured keyword, **When** the agent scans the inbox, **Then** that email is included in the digest.
3. **Given** an email neither from an allowlisted sender nor containing a keyword match, **When** the agent scans the inbox, **Then** that email is excluded from the digest entirely.

---

### User Story 5 - Rate-Limited and Resilient API Calls (Priority: P2)

When the agent processes a large batch of newsletters, it automatically throttles its calls to external services to stay within quota limits, and retries gracefully on transient failures without crashing.

**Why this priority**: Without rate limiting, a run with many newsletters will fail partway through with quota errors. Resilience is required for the agent to be trusted for unattended daily operation.

**Independent Test**: Can be tested by processing a batch of 20 newsletters in rapid succession and confirming all summaries complete successfully with no quota-exceeded errors and appropriate delays between calls.

**Acceptance Scenarios**:

1. **Given** 20 newsletters are queued for summarization, **When** the agent processes them, **Then** all 20 summaries complete successfully without any quota or rate-limit errors.
2. **Given** a transient API error occurs during summarization, **When** the error is encountered, **Then** the agent retries up to 3 times with exponential backoff before marking that newsletter as failed and continuing with the rest.
3. **Given** a newsletter fails after all retries, **When** the agent finishes, **Then** the digest is delivered with all available summaries and includes a note listing newsletters that could not be summarized.

---

### Edge Cases

- What happens when a newsletter is extremely long? The agent truncates the content to a safe length before summarization and notes this in the log.
- What happens when the Gmail authorization token has expired? The agent attempts automatic token refresh; if that fails, it exits with a clear error message prompting the user to re-authenticate.
- What happens when the inbox contains duplicate newsletters (same sender, same subject, same day)? The agent deduplicates by unique message ID and processes each email at most once per run.
- What happens when outbound email delivery fails? The agent retries delivery once; if the second attempt fails, it logs a critical error and exits with a non-zero status code.
- What happens when no newsletters are found on a given day? No digest email is sent; this is logged as an informational event, not an error.
- What happens when a newsletter contains no HTML and is plain text only? The agent passes the plain text directly to summarization without any HTML stripping step.
- What happens when the configuration file is missing or malformed? The agent exits immediately with a descriptive error message identifying the problem.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The agent MUST connect to Gmail using secure delegated authorization, fetching only emails that match the configured sender allowlist or subject keywords within a configurable lookback window (default: 24 hours).
- **FR-002**: The agent MUST extract readable text content from newsletter emails, removing navigation elements, footers, unsubscribe links, and other boilerplate before summarization.
- **FR-003**: The agent MUST produce a 200–250 word plain-language summary for each newsletter that preserves the key insights and important facts from the original content.
- **FR-004**: The agent MUST assemble all summaries into a single formatted digest email with clear separation between newsletters, sender attribution, and original subject lines.
- **FR-005**: The agent MUST deliver the digest email to the configured recipient address via authenticated outbound email.
- **FR-006**: The agent MUST support a `--dry-run` flag that executes all steps except email delivery, outputting the digest content to the terminal or log instead.
- **FR-007**: The agent MUST enforce rate limits on all external service calls, automatically throttling request frequency to avoid quota exhaustion.
- **FR-008**: The agent MUST retry failed external service calls with exponential backoff (up to 3 attempts) before marking a newsletter as failed and continuing.
- **FR-009**: The agent MUST load all detection rules and operational settings (sender allowlist, subject keywords, lookback window, per-run maximum, summary word target) from a YAML configuration file without requiring code changes.
- **FR-010**: The agent MUST log each run's start time, number of newsletters found, number successfully summarized, and final delivery outcome.
- **FR-011**: The agent MUST support scheduled daily execution via a configurable in-process scheduler without requiring an external system scheduler.
- **FR-012**: The agent MUST be fully testable with all external dependencies replaced by mocked equivalents, without modifying production code.
- **FR-013**: The agent MUST cap the number of newsletters processed per run at a configurable maximum (default: 20) to prevent runaway usage.
- **FR-014**: The agent MUST deduplicate newsletters within a single run by unique message identifier, processing each email at most once.

### Key Entities

- **Newsletter Email**: A raw email message from Gmail matching the sender allowlist or keyword filter. Key attributes: unique message ID, sender address, subject line, received timestamp, raw body content (HTML or plain text).
- **Summary**: An AI-generated condensed representation of a single newsletter. Key attributes: source message ID, sender, subject, summary text (200–250 words), word count, generation timestamp.
- **Digest**: The assembled output of a single agent run. Key attributes: ordered collection of summaries, run date, count of successfully summarized newsletters, count of failed newsletters.
- **Agent Configuration**: The user-defined rules governing agent behavior. Key attributes: sender allowlist, subject keyword list, lookback window in hours, maximum newsletters per run, target summary word count, delivery recipient address, scheduler trigger time.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Daily newsletter reading time is reduced from 45–90 minutes to a 15–20 minute digest review.
- **SC-002**: The agent successfully summarizes at least 95% of newsletters in a typical daily inbox batch (up to 20 newsletters) without manual intervention.
- **SC-003**: Each digest is delivered within 10 minutes of its scheduled trigger time on 99% of scheduled runs.
- **SC-004**: The agent processes a batch of 20 newsletters end-to-end (fetch, extract, summarize, deliver) in under 15 minutes.
- **SC-005**: Zero non-newsletter emails are incorrectly included in the digest when the sender allowlist is properly configured.
- **SC-006**: The agent recovers automatically from transient external service failures in at least 90% of cases (retry logic resolves the issue without the run failing entirely).
- **SC-007**: A new user can configure, authenticate, and successfully receive their first digest within 30 minutes of cloning the repository.

---

## Assumptions

- The user has a Gmail account with API access enabled. OAuth credential setup is a one-time manual step outside the agent's core execution loop.
- The digest recipient address is the user's own Gmail address by default. Delivery to other addresses is supported but not the primary use case.
- The agent does not maintain a persistent database of previously processed emails across runs. Deduplication is per-run only; re-running the agent on the same day may re-deliver the same digest.
- Summaries are generated in the same language as the newsletter content.
- The user configures at least one sender address or one subject keyword; an empty configuration produces no results, which is treated as an informational outcome rather than an error.
- Outbound email delivery uses the user's own authenticated email account; no third-party delivery service is required for the initial version.
- The scheduler runs as a long-lived foreground process; the user is responsible for keeping it alive (e.g., via a terminal multiplexer or process manager).
