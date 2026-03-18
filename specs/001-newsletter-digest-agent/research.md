# Research: Newsletter Digest Agent

**Branch**: `001-newsletter-digest-agent` | **Date**: 2026-03-09
**Status**: Complete — all decisions resolved, no NEEDS CLARIFICATION items remain

---

## Decision 1: Gmail API Access Pattern

**Decision**: Use the Gmail REST API via `google-api-python-client` with OAuth 2.0 offline access (refresh tokens). Fetch emails using `users.messages.list` with a `q` query string combining sender and date filters, then `users.messages.get` with `format=full` for MIME content.

**Rationale**: Google deprecated IMAP/password-based access for Gmail in 2022. OAuth 2.0 with offline access is the only supported long-running approach. The official `google-api-python-client` handles token refresh automatically via `google-auth` when an expired access token is detected.

**Alternatives considered**:
- `imaplib` (stdlib) — blocked by Google's mandatory OAuth enforcement; not viable
- Gmail API with `format=raw` — returns base64-encoded RFC 2822 message, requires more parsing work than `format=full` with no benefit for this use case
- Service account — requires Google Workspace; not suitable for personal Gmail

**Key implementation detail**: Store `token.json` (contains both access + refresh tokens) outside the repo. The `gmail_auth.py` script handles the one-time consent flow and writes `token.json`. Subsequent runs call `Credentials.refresh(Request())` automatically via the `google.oauth2.credentials` module.

---

## Decision 2: Newsletter Detection Strategy

**Decision**: Two-pass filter: (1) exact sender address match against `config.senders` allowlist; (2) case-insensitive subject keyword scan against `config.subject_keywords`. Either match includes the email. Apply after fetching all emails within the lookback window.

**Rationale**: Allowlist is the most reliable signal — newsletter senders are stable and known. Keyword fallback catches newsletters from new senders before the user adds them to the allowlist. Neither regex nor ML classification is needed at this scale.

**Alternatives considered**:
- Header-based detection (List-Unsubscribe header) — many transactional emails also include this header; produces false positives
- ML classifier — overkill for a single-user agent with an explicit allowlist
- Gmail label-based detection — requires user to pre-label newsletters; adds manual setup friction

**Key implementation detail**: The lookback window query is built as `after:{epoch_timestamp}` in the Gmail API `q` parameter. The date filter is applied server-side by Gmail, reducing bytes transferred.

---

## Decision 3: HTML Content Extraction Pipeline

**Decision**: Two-stage pipeline: (1) `BeautifulSoup4` removes known boilerplate tags (`<footer>`, `<nav>`, elements with class/id patterns matching `unsubscribe`, `footer`, `header`, `preheader`, tracking pixel `<img>` with 1×1 dimensions); (2) `html2text` converts remaining HTML to clean Markdown-ish plaintext, preserving paragraph structure and link text.

**Rationale**: BS4 gives fine-grained control over what to strip before conversion. `html2text` produces better plaintext than BS4's `.get_text()` because it preserves heading hierarchy and link text, which helps Claude understand document structure.

**Alternatives considered**:
- `lxml` — faster but less forgiving of malformed HTML common in newsletters; BS4 handles broken HTML more gracefully
- `trafilatura` — designed for article extraction from web pages, not email HTML; tends to over-strip newsletter content
- Passing raw HTML directly to Claude — increases token usage significantly (~3–5×) and exceeds context limits for long newsletters

**Key implementation detail**: Add a character limit (default: 8,000 chars) after extraction. If the newsletter exceeds the limit, truncate to the last complete sentence before the limit. This protects against context window overflows while keeping the most important content (newsletters are typically front-loaded with key information).

---

## Decision 4: Claude Summarization Prompt Design

**Decision**: Use a single system + user prompt pattern. System prompt sets the persona and output format constraints (200–250 words, preserve tone, extract 3–5 key insights). User prompt passes the cleaned newsletter text. Use `claude-sonnet-4-6` (or the latest Sonnet model available) for the cost/quality balance.

**Rationale**: A single API call per newsletter is the simplest approach and sufficient for newsletters up to 8,000 characters of cleaned text. The word count constraint (200–250) is enforced via the prompt; post-generation validation checks the count and retries once if it falls outside ±20% of target.

**Prompt template**:
```
System: You are a newsletter summarizer. Given a newsletter's text content, produce a concise
summary of 200–250 words. Preserve the author's tone. Highlight the 3–5 most important points.
Do not include greetings, unsubscribe text, or navigation labels.

User: Summarize the following newsletter:
---
{newsletter_text}
---
```

**Alternatives considered**:
- Streaming responses — adds complexity; not needed since we're not displaying output in real-time
- Structured output (JSON) — unnecessary; plain prose summaries are easier to embed in HTML digest
- Chunking + map-reduce summarization — reserved for newsletters that exceed 8,000 chars; first implementation handles truncation, chunking added only if needed

---

## Decision 5: Rate Limiting Implementation

**Decision**: Implement a token bucket rate limiter in `utils/rate_limiter.py` using `threading.Lock`. Default configuration: 1 request per 2 seconds for Anthropic API calls (conservative; actual limits are higher but vary by tier). Gmail API calls are not rate-limited by the agent (Google handles quota internally via the `googleapiclient.http` retry mechanism).

**Rationale**: A token bucket allows bursts up to the bucket capacity while enforcing a long-term average rate. Thread-safe with `threading.Lock`. No external dependency required.

**Alternatives considered**:
- `ratelimit` library — adds a dependency for something easily implemented in ~30 lines; constitution prefers minimal dependencies
- `tenacity` for retry logic — viable, but writing explicit exponential backoff is straightforward and keeps the retry logic transparent and testable
- `asyncio` semaphore — the agent is synchronous; introducing async purely for rate limiting would complicate the entire pipeline without benefit

**Key implementation detail**: Exponential backoff for retries: `wait = base * (2 ** attempt) + jitter` where `base=1s`, max 3 attempts, jitter is `random.uniform(0, 1)`. Applied separately from the rate limiter — rate limiter controls steady-state throughput, backoff handles error recovery.

---

## Decision 6: Digest Email Template

**Decision**: Jinja2 HTML template (`templates/digest.html.j2`) with inline CSS for maximum email client compatibility. Structure: header with run date and newsletter count; one section per summary with sender name, original subject (linked if URL available), horizontal rule separator; footer with agent attribution.

**Rationale**: Jinja2 is already in the constitution's tech stack. Inline CSS avoids email client CSS stripping issues (Gmail strips `<style>` blocks). The template keeps presentation logic entirely separate from business logic.

**Alternatives considered**:
- Plain-text digest — simpler but harder to scan visually when there are 10+ summaries
- Markdown digest — not natively renderable in most email clients without conversion
- MJML — powerful but adds a build step and Node.js dependency; overkill for this single-template use case

---

## Decision 7: Email Delivery Method

**Decision**: Use `smtplib` (stdlib) with `SMTP_SSL` or `STARTTLS` depending on port. Default: port 587 + STARTTLS. Authenticate with a Gmail App Password (not the account password). This avoids needing another OAuth flow for outbound sending.

**Rationale**: `smtplib` is stdlib — zero additional dependencies. Gmail App Passwords work with any SMTP client and are scoped specifically to the application. The Gmail SMTP server (`smtp.gmail.com`) provides excellent deliverability for self-delivery to the same account.

**Alternatives considered**:
- SendGrid / Mailgun API — adds dependency and cost; unnecessary for personal self-delivery
- OAuth 2.0 for SMTP — Gmail supports XOAUTH2 for SMTP but the setup complexity is high; App Passwords are the pragmatic choice for a personal agent
- Gmail API `users.messages.send` — would unify on one auth mechanism but adds complexity vs. simple SMTP; not worth it

---

## Decision 8: Scheduler Implementation

**Decision**: Use `APScheduler`'s `BlockingScheduler` with a `CronTrigger`. Default: `hour=6, minute=30` (6:30 AM local time). The scheduler runs in a single foreground process; the user keeps it alive via a terminal multiplexer or process manager.

**Rationale**: `APScheduler` is already in the constitution's tech stack. `BlockingScheduler` is the simplest option for a single-job scheduler. No distributed coordination needed.

**Key implementation detail**: The scheduler catches and logs all exceptions from the job function to prevent the scheduler from crashing on a single failed run. The next trigger fires normally regardless of the previous run's outcome.

**Alternatives considered**:
- System cron — requires no Python process to stay alive, but harder to configure cross-platform and loses structured logging
- Celery — distributed task queue; massive overkill for one recurring job
- `schedule` library — simpler API than APScheduler but less control over timezone-aware cron expressions

---

## Decision 9: Configuration Schema

**Decision**: Single YAML file at `config/newsletters.yaml` with explicit keys for all tunable parameters. Loaded once at agent startup. Schema validated at load time with clear error messages for missing required fields.

**Key configuration keys**:
```yaml
senders:           # list[str] — exact sender email addresses
subject_keywords:  # list[str] — case-insensitive subject match strings
lookback_hours: 24 # int — how far back to search
max_newsletters_per_run: 20  # int — cap on newsletters processed per run
summary_word_target: 225     # int — target word count for each summary
schedule:
  hour: 6
  minute: 30
  timezone: "America/New_York"
delivery:
  recipient: ""  # str — destination email address (loaded from env if empty)
```

**Rationale**: Separating non-secret config (allowlists, limits) from secret config (API keys, SMTP credentials) follows the constitution's secrets management principle. YAML is human-editable without code changes.

---

## Decision 10: Testing Strategy

**Decision**: Unit tests for each module in isolation using `pytest-mock`. Key mocks:
- `GmailFetcher`: mock `googleapiclient.discovery.build` return value; return pre-built `Email` dataclass instances
- `ClaudeSummarizer`: mock `anthropic.Anthropic().messages.create`; return a canned `Summary`
- `EmailDelivery`: mock `smtplib.SMTP_SSL`; assert `sendmail` was called with expected args
- `EmailParser`: feed raw HTML fixtures; assert plaintext output matches expected

Integration tests (optional, marked `@pytest.mark.integration`): require real credentials; skipped in CI by default.

**Rationale**: Mocking at the class boundary (not the HTTP layer) makes tests fast, offline, and independent of quota limits. `pytest-mock`'s `mocker.patch` fixture is the idiomatic approach.
