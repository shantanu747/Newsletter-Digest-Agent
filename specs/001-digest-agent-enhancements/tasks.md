# Tasks: Newsletter Digest Agent Enhancements

**Input**: Design documents from `/specs/001-digest-agent-enhancements/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no interdependency)
- **[Story]**: Which user story this task serves (US1–US5)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: One-time migration to new config structure and scope upgrade — must be done before any feature work.

- [x] T001 Migrate `config/newsletters.yaml`: change `senders` from flat list to `SenderConfig` entries; add `poll_interval_hours: 4`, `batch_size: 10`; add Superhuman, The Rundown AI, The Code as `pass_through` senders; remove `lookback_hours`
- [x] T002 Update OAuth scope constant from `gmail.readonly` to `gmail.modify` in `scripts/gmail_auth.py` (line 17) and `agent/fetchers/gmail_fetcher.py` (line 22) — document that `token.json` must be deleted and re-auth run

**Checkpoint**: Config and OAuth scope updated. Run `python scripts/gmail_auth.py` to verify re-auth flow works.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data model and config loader changes that all user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 Add `SenderConfig` dataclass to `agent/utils/models.py` with fields: `address: str`, `display_name: str | None`, `mode: Literal["pass_through", "summarize"]`, `summary_word_target: int | None`, `include_images: bool = True`, `max_images: int | None`
- [x] T004 [P] Add `DigestBatch` dataclass to `agent/utils/models.py` with fields: `batch_index: int`, `entries: list[DigestEntry]`, `gmail_message_ids: list[str]`, `total_batches: int`
- [x] T005 [P] Extend `Email` dataclass in `agent/utils/models.py`: add `gmail_message_id: str = ""` and `is_pass_through: bool = False`
- [x] T006 [P] Extend `DigestEntry` dataclass in `agent/utils/models.py`: add `is_pass_through: bool = False`, `display_name: str = ""`, `gmail_message_id: str = ""`
- [x] T007 Update `AgentConfiguration` dataclass in `agent/utils/config.py`: replace `senders: list[str]` with `senders: list[SenderConfig]`; add `poll_interval_hours: int = 4`, `batch_size: int = 10`; remove `lookback_hours`
- [x] T008 Update config loader in `agent/utils/config.py`: parse per-sender YAML entries into `SenderConfig` objects; validate `mode` is `"pass_through"` or `"summarize"`; warn and ignore unrecognized keys; validate `batch_size ≥ 1`
- [x] T009 Update Gmail query in `agent/fetchers/gmail_fetcher.py`: replace time-based `after:{epoch}` query with `from:(addr1 OR addr2 OR ...) is:unread in:inbox` built from `config.senders`; remove `lookback_hours` usage

**Checkpoint**: Run `python -c "from agent.utils.config import load_config; c = load_config(); print([s.mode for s in c.senders])"` — should print list of modes without errors.

---

## Phase 3: User Story 1 — Per-Sender Pass-Through (Priority: P1) 🎯 MVP

**Goal**: Senders configured as `pass_through` have their content preserved and included in the digest without AI summarization.

**Independent Test**: Set one sender to `mode: pass_through` in config. Run `python -m agent.runner --dry-run --once`. Verify digest output contains the original newsletter's section structure (headings, bullets) — not a flat AI-generated summary.

- [x] T010 [US1] Add `parse_pass_through(raw_html: str) -> str` method to `agent/parsers/email_parser.py`: apply lighter boilerplate removal (keep headings, bullets, numbered lists); convert to plaintext via `html2text` with structure-preserving settings; truncate at nearest sentence boundary within 500 words; append "Read original →" link if truncated
- [x] T011 [US1] Update `EmailParser.parse()` in `agent/parsers/email_parser.py`: propagate `gmail_message_id` from input into returned `Email` object; set `Email.is_pass_through` based on `SenderConfig.mode`
- [x] T012 [US1] Update `ClaudeSummarizer.summarize()` in `agent/summarizer/claude_summarizer.py`: accept `SenderConfig` or `is_pass_through: bool`; if `is_pass_through=True`, skip Claude API call and return a `Summary` wrapping the pre-processed pass-through text with `word_count` calculated from the text
- [x] T013 [US1] Update `NewsletterAgent.run()` in `agent/runner.py`: look up `SenderConfig` for each fetched email by sender address (case-insensitive); pass `SenderConfig` through to parser and summarizer; set `DigestEntry.is_pass_through` and `DigestEntry.display_name` from config
- [x] T014 [US1] Write unit tests in `tests/unit/test_email_parser.py`: test `parse_pass_through()` preserves headings and bullets; test truncation at 500 words; test "Read original" link appended; test that normal `parse()` path is unchanged
- [x] T015 [US1] Write unit tests in `tests/unit/test_summarizer.py`: test that `pass_through=True` returns a `Summary` without calling the Claude API; test that `pass_through=False` calls Claude normally

**Checkpoint**: `cd src && pytest tests/unit/test_email_parser.py tests/unit/test_summarizer.py` passes. Dry run shows pass-through content for configured senders.

---

## Phase 4: User Story 2 — Strict Image Filtering (Priority: P1)

**Goal**: Only graphs, charts, and memes pass through image filtering. All banners, logos, branding, sponsor images, and social icons are excluded.

**Independent Test**: Run `--dry-run --once` against a newsletter with a known banner + chart. Verify digest HTML contains the chart image URL but not the banner URL.

- [x] T016 [US2] Add `_classify_image(img_tag, soup) -> bool` method to `agent/parsers/email_parser.py` implementing the 6-layer heuristic signal stack from `data-model.md`:
  - Layer 1: Known tracking domain → exclude
  - Layer 2: Tracking pixel (width ≤ 1, height ≤ 1) → exclude
  - Layer 3: CSS class/id contains any of `banner`, `header`, `logo`, `icon`, `social`, `ad`, `advertisement`, `promo`, `footer`, `brand`, `sponsor` → exclude
  - Layer 4: Parent element is `<header>`, `<footer>`, `<nav>` → exclude
  - Layer 5: Alt text contains any of `logo`, `icon`, `badge`, `banner`, `social` → exclude; contains any of `chart`, `graph`, `data`, `visualization`, `meme` → include
  - Layer 6: Width < 100px AND aspect ratio 0.8–1.2 AND not on trusted CDN → exclude
  - Default: exclude
- [x] T017 [US2] Replace existing `_extract_images()` logic in `agent/parsers/email_parser.py` with calls to the new `_classify_image()` method; preserve `max_images` cap and per-sender `include_images`/`max_images` overrides
- [x] T018 [US2] Write unit tests in `tests/unit/test_email_parser.py`: test banner image excluded by class name; test logo excluded by parent `<header>`; test social icon excluded by alt text; test chart included by alt text; test small square image excluded by aspect ratio; test trusted CDN image included; test exclude-by-default for ambiguous image

**Checkpoint**: `cd src && pytest tests/unit/test_email_parser.py -k "image"` passes. Dry run shows no banner/logo images in digest.

---

## Phase 5: User Story 3 — Unread Inbox + Trash After Delivery (Priority: P1)

**Goal**: Agent fetches all unread emails from configured senders, sends batched digests, marks source emails as read, and moves them to trash on successful delivery.

**Independent Test**: With 15 unread test emails from one sender in inbox, run `--once`. Verify: 2 digest emails received (10 + 5), all 15 source emails moved to trash (or marked read if trash fails), no emails trashed from a batch whose digest failed to send.

- [x] T019 [US3] Add `mark_as_read(message_id: str) -> None` method to `agent/fetchers/gmail_fetcher.py`: call `messages.modify` with `removeLabelIds: ['UNREAD']`; log at DEBUG; handle `HttpError` with structured log warning (no re-raise)
- [x] T020 [US3] Add `move_to_trash(message_id: str) -> None` method to `agent/fetchers/gmail_fetcher.py`: call `messages.modify` with `addLabelIds: ['TRASH']`; log at DEBUG; handle `HttpError` with structured log warning (no re-raise)
- [x] T021 [US3] Update `NewsletterAgent.run()` in `agent/runner.py`: after fetching all unread emails, sort by `received_at` (oldest first); group into `DigestBatch` objects of size `config.batch_size`; iterate batches
- [x] T022 [US3] Update digest send loop in `agent/runner.py` and `agent/digest/delivery.py`: for each batch — build digest → attempt send → on success: call `mark_as_read()` then `move_to_trash()` for each `gmail_message_id` in batch → on failure: skip mark/trash, log warning with batch index and subject list; continue to next batch. **When `--dry-run` flag is active, skip both `mark_as_read()` and `move_to_trash()` calls entirely** — dry-run must never mutate inbox state.
- [x] T023 [US3] Update `DigestBuilder.build()` in `agent/digest/builder.py` to accept `DigestBatch` and pass `batch_index` / `total_batches` to the template for subject line generation (e.g., "Newsletter Digest — Batch 1 of 3")
- [x] T024 [US3] Write unit tests in `tests/unit/test_delivery.py`: test `mark_as_read` called for each message ID on successful delivery; test `move_to_trash` called after `mark_as_read`; test neither called when delivery fails; test `HttpError` on trash does not halt processing

**Checkpoint**: `cd src && pytest tests/unit/test_delivery.py` passes. Manual test with `--once` confirms source emails are in Gmail trash after digest received.

---

## Phase 6: User Story 4 — Rate-Limited 4-Hour Polling (Priority: P2)

**Goal**: Agent runs continuously, polling for unread emails every 4 hours. First poll runs immediately on startup. Agent handles interruptions gracefully.

**Independent Test**: Start the agent (`python -m agent.runner`). Verify: (1) first poll runs immediately with log output, (2) no second poll fires for 4 hours, (3) `Ctrl+C` produces a clean shutdown log and exits with code 0.

- [x] T025 [US4] Update `agent/scheduler.py`: replace `CronTrigger` with `IntervalTrigger(hours=config.poll_interval_hours)`; call `run_agent()` directly before `scheduler.start()` to execute immediately on startup; wrap `scheduler.start()` in `try/except KeyboardInterrupt` with `scheduler.shutdown()` and log `"scheduler_stopped"`
- [x] T026 [US4] Add `--once` flag to CLI argument parser in `agent/runner.py`: when set, run a single poll and exit without starting the scheduler; log `"single_run_complete"` before exit
- [x] T027 [US4] Add batch progress logging in `agent/runner.py`: log `"poll_started"` with total unread count and total batch count at start of each poll; log `"batch_complete"` with `batch_index`, `total_batches`, `emails_in_batch`, `emails_remaining` after each batch delivery
- [x] T028 [US4] Update `agent/runner.py` to log `"poll_complete_no_emails"` when a poll finds 0 unread emails from configured senders; skip digest send and trash operations

**Checkpoint**: `python -m agent.runner --once` exits cleanly with progress log output. `python -m agent.runner` starts scheduler and logs first poll immediately.

---

## Phase 7: User Story 5 — Redesigned Email Template (Priority: P3)

**Goal**: The digest email looks polished and professional with a table of contents, responsive layout, visual distinction between pass-through and summarized entries, styled links, and an image grid.

**Independent Test**: Run `--dry-run --once` and open the rendered HTML in a browser. Verify: TOC at top with working anchor links, pass-through entries show a "digest" badge, summarized entries show no badge, images render in a 2-column grid when 2+, Further Reading links are styled as buttons, layout is readable at 375px viewport width.

- [x] T029 [US5] Rewrite `templates/digest.html.j2`: add `<head>` with responsive `<meta name="viewport">` and inline base styles (max-width 600px, centered, font stack); add table of contents section at top with anchor links to each entry (`#entry-{{ loop.index }}`)
- [x] T030 [US5] Add per-entry layout in `templates/digest.html.j2`: each entry gets `id="entry-{{ loop.index }}"` anchor; display `entry.display_name` as sender label; add conditional `pass_through` badge for `entry.is_pass_through`; render subject as `<h2>`; render summary/pass-through text preserving line breaks
- [x] T031 [US5] Add image grid layout in `templates/digest.html.j2`: if `entry.images | length >= 2`, render images in a 2-column HTML `<table>` layout; if single image, render full-width; each `<img>` uses inline styles for `max-width: 100%`, `height: auto`, `border-radius: 4px`, `loading="lazy"`; add `alt` text from context
- [x] T032 [US5] Style "Further Reading" links in `templates/digest.html.j2`: render each link as an inline-block `<a>` styled as a pill button (background color, padding, border-radius, no underline); use `safe_url` filter (already in `builder.py`) to prevent XSS
- [x] T033 [US5] Add digest metadata footer in `templates/digest.html.j2`: batch info (e.g., "Batch 1 of 3 · 10 newsletters · Mar 19, 2026"); failed newsletter warning block (existing logic, restyled); plain-text unsubscribe/footer section

**Checkpoint**: Open dry-run HTML output in browser and mobile-width devtools. All entries display correctly; TOC links scroll to correct sections; no layout breakage at 375px.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Config validation, integration test, cleanup.

- [X] T034 [P] Add config validation tests in `tests/unit/test_config.py`: test `SenderConfig` parsed correctly from YAML; test unknown key produces log warning but no error; test invalid `mode` value raises `ValueError`; test `batch_size` defaults to 10; test empty `senders` list raises `ValueError`
- [X] T035 [P] Add integration smoke test in `tests/integration/test_pipeline.py`: mock Gmail API to return 3 unread emails from one `pass_through` sender and 2 from one `summarize` sender; mock Claude API; mock SMTP; run full pipeline via `runner.py --once --dry-run`; assert: pass-through entries not sent to Claude; summarize entries sent to Claude; no mark-as-read/trash called in dry-run mode
- [X] T036 Update `README.md` (or `quickstart.md`) with migration instructions: delete `token.json`, re-run `gmail_auth.py`, update `newsletters.yaml` to new sender format; note breaking change on `senders` field
- [X] T037 Run full test suite `cd src && pytest` — fix any regressions in existing tests caused by `senders: list[str]` → `list[SenderConfig]` type change; update any test fixtures using the old config format

**Checkpoint**: `cd src && pytest` — all tests pass with no failures.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — **BLOCKS all user story phases**
- **Phase 3 (US1 Pass-Through)**: Depends on Phase 2
- **Phase 4 (US2 Image Filtering)**: Depends on Phase 2; can run in parallel with Phase 3
- **Phase 5 (US3 Trash/Batch)**: Depends on Phase 2; can run in parallel with Phase 3 and 4
- **Phase 6 (US4 Polling)**: Depends on Phase 5 (needs batch loop in place)
- **Phase 7 (US5 Template)**: Depends on Phase 2; can run in parallel with Phases 3–5
- **Phase 8 (Polish)**: Depends on all feature phases complete

### User Story Dependencies

- **US1 (P1)**: Foundational → T010–T015
- **US2 (P1)**: Foundational → T016–T018 (parallel with US1)
- **US3 (P1)**: Foundational → T019–T024 (parallel with US1/US2)
- **US4 (P2)**: US3 must be complete (batch loop required) → T025–T028
- **US5 (P3)**: Foundational → T029–T033 (parallel with US1/US2/US3)

### Parallel Opportunities Within Each Story

**US1**: T014 and T015 (unit tests) can run in parallel after T012/T013
**US2**: T016 and T017 depend on each other in sequence; T018 after both
**US3**: T019 and T020 (mark_as_read, move_to_trash) run in parallel; T021/T022 after
**US5**: T029, T031, T032 can run in parallel (different sections of the template)

---

## Parallel Execution Examples

### Phase 3 (US1) Sequential Dependency Note
```
# T010 → T012 must be sequential (data contract dependency):
# T010 defines the parse_pass_through() interface and output format
# T012 wraps that output in a Summary object — depends on T010's contract
# T014 and T015 (unit tests) can run in parallel after T012 is complete
```

### Phase 4 (US2) Parallel with Phase 3
```
# US2 can start as soon as Phase 2 is complete, without waiting for US1:
T016: _classify_image() method in email_parser.py
```

### Phase 5 (US3) Parallel Tasks
```
# mark_as_read and move_to_trash are independent:
T019: mark_as_read() in gmail_fetcher.py
T020: move_to_trash() in gmail_fetcher.py
```

### Phase 7 (US5) Parallel Tasks
```
# Different template sections:
T029: TOC and base layout
T031: Image grid
T032: Further Reading link styling
```

---

## Implementation Strategy

### MVP First (P1 Stories Only)

1. Complete Phase 1: Setup (config migration + OAuth scope)
2. Complete Phase 2: Foundational (data model + config loader + Gmail query)
3. Complete Phase 3: US1 (pass-through processing) — **highest priority pain point**
4. Complete Phase 4: US2 (image filtering) — parallel with or after US1
5. Complete Phase 5: US3 (unread + trash) — completes the core pipeline
6. **STOP and VALIDATE**: Run `--once`, verify pass-through content, no banners, emails trashed
7. Deploy and use — template redesign and polling scheduler are quality-of-life improvements

### Incremental Delivery

1. Phase 1 + 2 → Foundation ready, existing behavior unchanged
2. Phase 3 (US1) → Pass-through works for Superhuman/Rundown/The Code
3. Phase 4 (US2) → Image filtering cleaned up
4. Phase 5 (US3) → Inbox management automated (read + trash on delivery)
5. Phase 6 (US4) → Continuous 4-hour polling starts
6. Phase 7 (US5) → Better-looking digest emails
7. Phase 8 → Tests and docs complete

---

## Task Summary

| Phase | User Story | Tasks | Parallelizable |
|-------|-----------|-------|---------------|
| 1 Setup | — | T001–T002 | — |
| 2 Foundational | — | T003–T009 | T004, T005, T006 |
| 3 US1 Pass-Through (P1) | US1 | T010–T015 | T014, T015 |
| 4 US2 Image Filtering (P1) | US2 | T016–T018 | T018 |
| 5 US3 Unread + Trash (P1) | US3 | T019–T024 | T019, T020 |
| 6 US4 Polling Scheduler (P2) | US4 | T025–T028 | T027, T028 |
| 7 US5 Template Redesign (P3) | US5 | T029–T033 | T029, T031, T032 |
| 8 Polish | — | T034–T037 | T034, T035 |

**Total tasks**: 37
**MVP scope**: Phases 1–5 (T001–T024), 24 tasks
