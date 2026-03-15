# Tasks: Newsletter Digest Agent

**Input**: Design documents from `/specs/001-newsletter-digest-agent/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths are included in every task description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create project skeleton — directories, package init files, config stubs, and dev tooling. No business logic yet.

- [x] T001 Create full directory tree: `agent/`, `agent/fetchers/`, `agent/parsers/`, `agent/summarizer/`, `agent/digest/`, `agent/utils/`, `config/`, `templates/`, `scripts/`, `tests/`
- [x] T002 [P] Add `__init__.py` to every package directory: `agent/__init__.py`, `agent/fetchers/__init__.py`, `agent/parsers/__init__.py`, `agent/summarizer/__init__.py`, `agent/digest/__init__.py`, `agent/utils/__init__.py`
- [x] T003 [P] Create `pyproject.toml` with project name `newsletter-digest-agent`, Python `>=3.11` requirement, and all dependencies from `requirements.txt`
- [x] T004 [P] Populate `.env.example` with all required variables: `ANTHROPIC_API_KEY`, `GMAIL_OAUTH_TOKEN_PATH`, `DELIVERY_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` — each with a descriptive placeholder comment
- [x] T005 [P] Create `config/newsletters.yaml` with fully commented default values for all keys per the config schema in `specs/001-newsletter-digest-agent/contracts/config-schema.md`
- [x] T006 [P] Add `[tool.pytest.ini_options]` section to `pyproject.toml`: set `testpaths = ["tests"]`, define `integration` marker with description

**Checkpoint**: Directory tree exists, all packages importable, config stubs in place.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure every user story depends on — data types, config loading, logging, exceptions, and the abstract fetcher base. No story work can begin until this phase is complete.

**⚠️ CRITICAL**: All Phase 3+ work is blocked until this phase is complete.

- [x] T007 Define `Email`, `Summary`, `DigestEntry` as `@dataclass(frozen=True)` in `agent/utils/models.py` with all fields and types exactly as specified in `specs/001-newsletter-digest-agent/contracts/data-classes.md`
- [x] T008 [P] Define custom exception hierarchy in `agent/utils/exceptions.py`: `NewsletterAgentError` (base), `ConfigurationError`, `FetchError`, `SummarizationError`, `DeliveryError` — each with a docstring
- [x] T009 [P] Configure structlog JSON renderer in `agent/utils/logger.py`: export a `get_logger(name)` factory that returns a bound structlog logger; ensure all log entries include `timestamp` and `level` fields
- [x] T010 Implement `AgentConfiguration` dataclass and `load_config(yaml_path: str) -> AgentConfiguration` in `agent/utils/config.py`: read `newsletters.yaml` via PyYAML, overlay secrets from `python-dotenv` env vars, validate all required ENV fields are non-empty, raise `ConfigurationError` with field name on any missing or invalid value
- [x] T011 [P] Create abstract `BaseFetcher` in `agent/fetchers/base_fetcher.py` with `@abstractmethod fetch_newsletters(self, config: AgentConfiguration) -> list[Email]` signature
- [x] T012 Create `tests/conftest.py` with pytest fixtures: `sample_email()` factory returning a valid `Email` instance, `sample_summary()` returning a valid `Summary`, `mock_config()` returning a valid `AgentConfiguration` with safe test values

**Checkpoint**: Foundation complete. `from agent.utils.models import Email` and `from agent.utils.config import load_config` import cleanly. User story phases can now proceed.

---

## Phase 3: User Story 1 — Connect Gmail and Run First Digest (Priority: P1) 🎯 MVP

**Goal**: Full end-to-end pipeline — fetch newsletters from Gmail, extract clean text, generate summaries, assemble digest, deliver by email.

**Independent Test**: Run `python -m agent.runner` against a Gmail account containing 1+ newsletter emails. Verify a digest email arrives in the inbox containing one 200–250 word summary per newsletter, with sender and subject attribution.

### Unit Tests for User Story 1

- [x] T013 [P] [US1] Write `tests/test_gmail_fetcher.py`: mock `googleapiclient.discovery.build` to return a mock service; assert `GmailFetcher.fetch_newsletters()` returns a `list[Email]` with correct `id`, `sender`, `subject`, `received_at`, `raw_html` from mocked API response
- [x] T014 [P] [US1] Write `tests/test_email_parser.py`: feed raw HTML fixtures (newsletter-like HTML with nav, footer, unsubscribe links, 1×1 tracking pixel); assert `EmailParser.parse()` returns `Email` with `plain_text` stripped of boilerplate, and truncated at 8000 chars when input exceeds limit
- [x] T015 [P] [US1] Write `tests/test_claude_summarizer.py`: mock `anthropic.Anthropic().messages.create` to return a canned response; assert `ClaudeSummarizer.summarize()` returns a `Summary` with non-empty `summary_text` and correct `word_count`
- [x] T016 [P] [US1] Write `tests/test_digest_builder.py`: call `DigestBuilder.build()` with 3 sample `DigestEntry` objects; assert returned HTML contains each sender address, each subject line, and each summary text
- [x] T017 [P] [US1] Write `tests/test_delivery.py`: mock `smtplib.SMTP`; call `EmailDelivery.send()`; assert `starttls()`, `login()`, and `sendmail()` are called with expected arguments; assert `DeliveryError` raised when `sendmail` raises on both attempts

### Implementation for User Story 1

- [x] T018 [US1] Implement `GmailFetcher` in `agent/fetchers/gmail_fetcher.py`: load OAuth credentials from `token.json` path in config, auto-refresh via `google.oauth2.credentials`; call `users.messages.list` with `q="after:{epoch}"` query for the lookback window; call `users.messages.get(format='full')` for each result; decode MIME multipart body (prefer `text/html`, fall back to `text/plain`); return `list[Email]`
- [x] T019 [P] [US1] Implement `scripts/gmail_auth.py`: run Google OAuth 2.0 consent flow using `google_auth_oauthlib.flow.InstalledAppFlow` with `gmail.readonly` scope; write resulting credentials to `token.json` at the path configured by `GMAIL_OAUTH_TOKEN_PATH`
- [x] T020 [US1] Implement `EmailParser` in `agent/parsers/email_parser.py`: use BeautifulSoup4 to remove `<footer>`, `<nav>`, elements with class/id matching `unsubscribe`, `footer`, `header`, `preheader`, and `<img>` tags with width/height of 1; convert remaining HTML to plaintext via `html2text.html2text()`; truncate output to 8000 characters at last sentence boundary; handle plain-text-only emails by returning the body unchanged; return new `Email` instance with `plain_text` populated
- [x] T021 [US1] Implement `ClaudeSummarizer` in `agent/summarizer/claude_summarizer.py`: construct system prompt ("You are a newsletter summarizer. Produce a 200–250 word summary. Preserve tone. Highlight 3–5 key points. Exclude greetings and navigation.") and user prompt with newsletter text; call `anthropic.Anthropic(api_key=...).messages.create(model="claude-sonnet-4-6", ...)`; validate word count (retry once if outside 160–300 range); return `Summary` dataclass
- [x] T022 [US1] Implement `DigestBuilder` in `agent/digest/builder.py`: load `templates/digest.html.j2` via Jinja2 `Environment(loader=FileSystemLoader(...))`; render with `entries: list[DigestEntry]`, `run_date`, `total_summarized`, `failed_subjects`; return rendered HTML string
- [x] T023 [US1] Create `templates/digest.html.j2`: HTML email template with inline CSS; header showing run date and newsletter count; one `<section>` per entry with sender, subject, summary text, `<hr>` separator; footer with failed newsletters note (if any) and agent attribution
- [x] T024 [US1] Implement `EmailDelivery` in `agent/digest/delivery.py`: connect to SMTP via `smtplib.SMTP(host, port)`, call `starttls()`, `login(user, password)`, construct `MIMEMultipart('alternative')` message with `text/html` part, call `sendmail()`; retry once on `smtplib.SMTPException`; raise `DeliveryError` on second failure
- [x] T025 [US1] Implement `NewsletterAgent` class in `agent/runner.py`: orchestrate full pipeline — `load_config()` → `GmailFetcher.fetch_newsletters()` → deduplicate by `Email.id` → cap at `max_newsletters_per_run` → for each: `EmailParser.parse()` → `ClaudeSummarizer.summarize()` (catch `SummarizationError`, log warning, continue) → `DigestBuilder.build()` → `EmailDelivery.send()`; log run start, each newsletter processed, final delivery outcome
- [x] T026 [US1] Add `if __name__ == "__main__"` block and argparse CLI to `agent/runner.py`: no flags yet (just `python -m agent.runner`), call `NewsletterAgent(config).run()`; exit 0 on success, exit 1 on `ConfigurationError` or `FetchError`
- [x] T027 [US1] Create `agent/__main__.py` so `python -m agent.runner` works as a module invocation

**Checkpoint**: `python -m agent.runner` completes without errors against a real Gmail inbox. Digest email delivered. US1 is independently functional.

---

## Phase 4: User Story 2 — Dry Run Without Sending Email (Priority: P2)

**Goal**: `--dry-run` flag skips email delivery; outputs digest summary to log and terminal instead.

**Independent Test**: Run `python -m agent.runner --dry-run`. Confirm no email is sent (no SMTP connection made), digest content is visible in log output, and process exits 0.

**Note**: US2, US4, and US5 can all be worked in parallel after Phase 3 — they touch different files.

### Unit Tests for User Story 2

- [x] T028 [US2] Write `tests/test_runner.py`: mock all pipeline components via `pytest-mock`; invoke runner in dry-run mode; assert `EmailDelivery.send` is **not** called; assert digest content is logged at INFO level

### Implementation for User Story 2

- [x] T029 [US2] Add `--dry-run` flag to argparse in `agent/runner.py`; pass `dry_run: bool` to `NewsletterAgent.run()`
- [x] T030 [US2] Add dry-run branch in `NewsletterAgent.run()` in `agent/runner.py`: when `dry_run=True`, skip `EmailDelivery.send()`; instead log the digest subject line and per-summary word counts at INFO level; print a human-readable summary to stdout

**Checkpoint**: `--dry-run` executes full pipeline through digest assembly, skips SMTP entirely, prints/logs digest. US2 independently verifiable.

---

## Phase 5: User Story 4 — Newsletter Detection via Allowlist and Keywords (Priority: P2)

**Goal**: Emails not on the sender allowlist are still included if their subject matches a configured keyword. Non-matching emails are excluded.

**Independent Test**: Provide mock inbox with 3 emails — one allowlisted sender, one keyword-matching subject from unknown sender, one neither. Confirm only 2 appear in digest.

**Note**: This phase refines `GmailFetcher` from US1. Can run in parallel with US2 and US5.

### Unit Tests for User Story 4

- [x] T031 [US4] Extend `tests/test_gmail_fetcher.py`: add test cases for keyword detection — mock inbox with emails matching sender allowlist, emails matching subject keyword only, and emails matching neither; assert only the first two are returned by `fetch_newsletters()`

### Implementation for User Story 4

- [x] T032 [US4] Add subject-keyword client-side filter to `GmailFetcher.fetch_newsletters()` in `agent/fetchers/gmail_fetcher.py`: after receiving API results, apply two-pass filter: (1) keep emails whose `sender` exactly matches any entry in `config.senders`; (2) keep emails whose `subject` contains any `config.subject_keywords` entry (case-insensitive); return union, deduplicated by message ID
- [x] T033 [US4] Add warning log in `agent/fetchers/gmail_fetcher.py` when both `config.senders` and `config.subject_keywords` are empty — log "No detection rules configured; no newsletters will be fetched" at WARNING level

**Checkpoint**: Mock inbox test passes with correct include/exclude behavior. US4 independently verifiable.

---

## Phase 6: User Story 5 — Rate-Limited and Resilient API Calls (Priority: P2)

**Goal**: Token bucket throttles Anthropic calls; exponential backoff retries transient failures; runs with 20 newsletters complete without quota errors.

**Independent Test**: Mock `ClaudeSummarizer.summarize()` to fail on first 2 calls then succeed; confirm the summary is eventually produced. Mock 20 newsletters; confirm all 20 summaries complete.

**Note**: This phase modifies `ClaudeSummarizer` and adds a new `rate_limiter.py`. Can run in parallel with US2 and US4.

### Unit Tests for User Story 5

- [x] T034 [P] [US5] Write `tests/test_rate_limiter.py`: assert `TokenBucketLimiter.acquire()` returns immediately when tokens are available; assert it blocks (via mock time) when bucket is empty; assert tokens refill at configured rate
- [x] T035 [P] [US5] Extend `tests/test_claude_summarizer.py` with retry tests: mock `anthropic.Anthropic().messages.create` to raise `anthropic.APIError` on calls 1 and 2, succeed on call 3; assert `summarize()` returns a valid `Summary` and the mock was called 3 times; separately assert `SummarizationError` raised when all 3 attempts fail

### Implementation for User Story 5

- [x] T036 [US5] Implement `TokenBucketLimiter` in `agent/utils/rate_limiter.py`: `threading.Lock`-based token bucket; `__init__(rate: float, capacity: int)`; `acquire()` blocks until a token is available; thread-safe
- [x] T037 [US5] Integrate `TokenBucketLimiter` into `ClaudeSummarizer` in `agent/summarizer/claude_summarizer.py`: instantiate limiter with `rate=0.5` (1 request per 2 seconds) at class init; call `self._limiter.acquire()` immediately before each `messages.create` call
- [x] T038 [US5] Add exponential backoff retry loop to `ClaudeSummarizer.summarize()` in `agent/summarizer/claude_summarizer.py`: catch `anthropic.APIError` and `anthropic.RateLimitError`; retry up to 3 times with `wait = 1 * (2 ** attempt) + random.uniform(0, 1)` seconds; log each retry attempt at WARNING level; raise `SummarizationError` after exhaustion

**Checkpoint**: 20-newsletter batch completes without quota errors. Transient failures retry and resolve. US5 independently verifiable.

---

## Phase 7: User Story 3 — Scheduled Daily Digest Delivery (Priority: P3)

**Goal**: `python -m agent.scheduler` runs a daily cron job at the configured time with no manual intervention.

**Independent Test**: Start the scheduler process; confirm it prints/logs its scheduled trigger time; manually trigger the job function and confirm it executes `NewsletterAgent.run()`.

### Unit Tests for User Story 3

- [x] T039 [US3] Write `tests/test_scheduler.py`: mock `APScheduler.schedulers.blocking.BlockingScheduler`; assert `DigestScheduler.start()` adds a job with a `CronTrigger` configured with the correct `hour`, `minute`, and `timezone` from config; assert the job callable is `NewsletterAgent.run`

### Implementation for User Story 3

- [x] T040 [US3] Implement `DigestScheduler` in `agent/scheduler.py`: instantiate `BlockingScheduler(timezone=config.schedule_timezone)`; `add_job(NewsletterAgent(config).run, CronTrigger(hour=..., minute=...), misfire_grace_time=600)`; wrap job in try/except to catch and log all exceptions without crashing the scheduler; implement `start()` method that calls `scheduler.start()`
- [x] T041 [US3] Add `if __name__ == "__main__"` block to `agent/scheduler.py`: call `load_config()` and `DigestScheduler(config).start()`; log the next scheduled run time at startup; handle `KeyboardInterrupt` gracefully with INFO log
- [x] T042 [US3] Create `agent/scheduler.py` module entry point so `python -m agent.scheduler` works

**Checkpoint**: `python -m agent.scheduler` starts without error and logs the next scheduled trigger time. US3 independently verifiable.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final hardening, documentation, and end-to-end validation.

- [x] T043 [P] Update `README.md` setup section to match actual commands (`python -m agent.runner`, `python -m agent.runner --dry-run`, `python -m agent.scheduler`); verify all steps in `specs/001-newsletter-digest-agent/quickstart.md` are reflected accurately
- [x] T044 [P] Add `agent/utils/exceptions.py` import to `agent/utils/__init__.py` and verify all exception types are importable from `agent.utils`
- [x] T045 [P] Run full unit test suite with `pytest -v` and fix any failures; confirm all tests pass with zero warnings
- [x] T046 [P] Verify `.gitignore` correctly excludes `.env`, `token.json`, `credentials.json`, and `__pycache__/` by running `git status` after creating these files and confirming they are untracked
- [x] T047 Perform end-to-end dry-run validation: follow `specs/001-newsletter-digest-agent/quickstart.md` steps 1–5 from scratch in a clean virtual environment; confirm `python -m agent.runner --dry-run` produces digest output within 15 minutes for a 20-newsletter inbox
- [x] T048 [P] Add `CONTRIBUTING.md` note or inline comment in `agent/runner.py` summarizing the pipeline order and extension points (how to add a new fetcher by subclassing `BaseFetcher`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Requires Phase 1 complete — **blocks all user story phases**
- **US1 (Phase 3)**: Requires Phase 2 complete — no other story dependencies
- **US2, US4, US5 (Phases 4–6)**: Each requires Phase 3 complete — can proceed **in parallel with each other**
- **US3 (Phase 7)**: Requires Phase 3 complete — can proceed in parallel with Phases 4–6
- **Polish (Phase 8)**: Requires all user story phases complete

### User Story Dependencies

```
Phase 1 (Setup)
    │
Phase 2 (Foundational)
    │
Phase 3 (US1 — P1) ←── Must complete before any P2/P3 work
    ├──── Phase 4 (US2 — dry-run)      ─┐
    ├──── Phase 5 (US4 — detection)     ├── All can run in parallel
    ├──── Phase 6 (US5 — rate limiting) ┘
    └──── Phase 7 (US3 — scheduler)    ── Can also run in parallel with Phases 4-6
              │
         Phase 8 (Polish)
```

### Within Each User Story

1. Unit tests written first (marked [P] — they can all be written in parallel)
2. Tests must fail before implementation begins
3. Implementation in dependency order: models → services → integration
4. Verify tests pass before marking story complete

### Parallel Opportunities

| When | What can run in parallel |
|------|--------------------------|
| Phase 1 | T002–T006 (all marked [P]) |
| Phase 2 | T008, T009, T011 alongside T007; T012 after T007 |
| Phase 3 | T013–T017 (all unit tests); T019 alongside T018 |
| After Phase 3 | Phases 4, 5, 6, and 7 (different files, no conflicts) |
| Phase 8 | T043, T044, T045, T046, T048 (all marked [P]) |

---

## Parallel Execution Examples

### US1 Tests (write all together before implementing)

```
Agent A: T013 — tests/test_gmail_fetcher.py
Agent B: T014 — tests/test_email_parser.py
Agent C: T015 — tests/test_claude_summarizer.py
Agent D: T016 — tests/test_digest_builder.py
Agent E: T017 — tests/test_delivery.py
```

### After US1: P2 stories in parallel

```
Agent A: Phase 4 (US2) — agent/runner.py --dry-run additions
Agent B: Phase 5 (US4) — agent/fetchers/gmail_fetcher.py keyword detection
Agent C: Phase 6 (US5) — agent/utils/rate_limiter.py + claude_summarizer.py backoff
Agent D: Phase 7 (US3) — agent/scheduler.py
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational — **do not skip**
3. Complete Phase 3: User Story 1 (end-to-end pipeline)
4. **STOP and VALIDATE**: `python -m agent.runner --dry-run` works; digest email delivered
5. Declare MVP ✅

### Incremental Delivery

1. Setup + Foundational → agent importable, models defined
2. US1 → full pipeline works, digest delivered manually
3. US2 → safe dry-run preview available
4. US4 → keyword detection complete; detection is accurate
5. US5 → rate limiting + resilience; agent is production-ready for unattended runs
6. US3 → daily schedule running; agent requires no daily manual invocation
7. Polish → test suite clean, docs accurate

### Parallel Agent Strategy

With multiple agents (after Phase 2 complete):

- **Agent 1**: Phase 3 (US1) — core pipeline end-to-end
- *(Phase 3 must complete first as it unblocks the rest)*
- **Agent 1**: Phase 4 (US2) | **Agent 2**: Phase 5 (US4) | **Agent 3**: Phase 6 (US5) | **Agent 4**: Phase 7 (US3)
- All agents → Phase 8 (Polish)

---

## Task Summary

| Phase | Stories | Tasks | Parallelizable |
|-------|---------|-------|----------------|
| Phase 1: Setup | — | T001–T006 (6) | 5 of 6 |
| Phase 2: Foundational | — | T007–T012 (6) | 4 of 6 |
| Phase 3: US1 (P1) | US1 | T013–T027 (15) | 7 of 15 |
| Phase 4: US2 (P2) | US2 | T028–T030 (3) | 0 of 3 |
| Phase 5: US4 (P2) | US4 | T031–T033 (3) | 0 of 3 |
| Phase 6: US5 (P2) | US5 | T034–T038 (5) | 2 of 5 |
| Phase 7: US3 (P3) | US3 | T039–T042 (4) | 0 of 4 |
| Phase 8: Polish | — | T043–T048 (6) | 5 of 6 |
| **Total** | **5 stories** | **48 tasks** | **23 parallelizable** |

---

## Notes

- `[P]` tasks touch different files with no dependency on incomplete tasks — safe to assign to separate agents
- `[US#]` labels map each task to its user story for traceability back to `spec.md`
- Each user story phase is a complete, independently testable increment — stop at any checkpoint to validate
- Unit tests use `pytest-mock` exclusively; no real credentials needed in any test
- Integration tests (real Gmail + Anthropic) should be marked `@pytest.mark.integration` and skipped in CI
- Commit after completing each phase checkpoint
