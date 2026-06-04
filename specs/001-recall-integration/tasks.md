# Tasks: Filtering Rollback — Always-On Newsletter Digest

**Input**: Design documents from `/specs/001-recall-integration/`  
**Branch**: `001-recall-integration`  
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to

## Path Conventions

All paths are relative to repository root. Source: `agent/`, tests: `tests/`.

---

## Phase 1: Setup

No new project structure or infrastructure required. All changes are confined to existing files. Phase skipped.

---

## Phase 2: Foundational

No shared prerequisites block US1. Phase skipped — proceed directly to implementation.

---

## Phase 3: User Story 1 — Every Newsletter Gets a Digest Entry (Priority: P1) 🎯 MVP

**Goal**: Remove the interest-based suppression gate so every newsletter produces real digest ideas regardless of portfolio/interest alignment.

**Independent Test**: Run `pytest tests/unit/test_idea_format.py` (green) and manually trigger the agent against a newsletter unrelated to the user profile — confirm the output contains real ideas, not "No High-Signal Content."

### Tests for User Story 1

- [x] T001 [US1] Create `tests/unit/test_idea_format.py` with six test cases: (1) assert `"No High-Signal Content"` is not in `_IDEA_SYSTEM_PROMPT_TEMPLATE`, (2) assert `"warrants your attention"` is not in `_IDEA_SYSTEM_PROMPT_TEMPLATE`, (3) assert `_parse_ideas("")` returns an `Idea` with `title="Content Unavailable"`, (4) assert `_parse_ideas("IDEA: Test\nBody text.")` returns a tuple containing `Idea(title="Test", summary_text="Body text.")` — regression guard for valid IDEA block parsing, (5) assert `summarize_as_ideas()` with a mocked off-topic Claude response returns a `Summary` whose `ideas` tuple contains at least one real idea, (6) assert `summarize_as_ideas()` with `user_profile=None` and a mocked Claude response returns a non-empty `Summary` with real ideas — validates the no-profile code path

### Implementation for User Story 1

- [x] T002 [US1] Update `_IDEA_SYSTEM_PROMPT_TEMPLATE` in `agent/summarizer/claude_summarizer.py`: remove the relevance-gate phrase ("for each idea that is relevant to the reader's holdings, interests, or that would make a well-informed person meaningfully more aware"), remove the entire "If no ideas are relevant, output exactly: IDEA: No High-Signal Content / Nothing in this newsletter warrants your attention." block, and add an instruction that where an idea directly relates to the reader's holdings or interests the connection should be noted briefly within the idea's summary text

- [x] T003 [US1] Update `_parse_ideas()` fallback in `agent/summarizer/claude_summarizer.py` (lines 86–90): replace `Idea(title="No High-Signal Content", summary_text="Nothing in this newsletter warrants your attention.")` with `Idea(title="Content Unavailable", summary_text="Unable to extract ideas from this newsletter.")`

- [x] T004 [US1] Update `summarize_as_ideas()` docstring in `agent/summarizer/claude_summarizer.py` (lines 210–228): remove the sentence "Filters ideas for relevance using the reader's profile" and the clause "When *user_profile* is None, the model applies general-informedness filtering only." Replace with accurate description: profile is injected for framing only; all significant ideas are always surfaced

**Checkpoint**: Run `pytest tests/unit/test_idea_format.py` — all six tests green. US1 is fully functional and independently testable.

---

## Phase 4: Polish & Cross-Cutting Concerns

- [x] T005 [P] Run `pytest` from repo root and confirm no regressions in existing test suite
- [x] T006 [P] Run `ruff check .` from repo root and resolve any lint issues introduced

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 3 (US1)**: No dependencies — start immediately
- **Phase 4 (Polish)**: Depends on T001–T004 complete

### Within User Story 1

- T001 first (tests define the contract, must be written before implementation)
- T002 → T003 → T004 sequentially (all in the same file; avoids merge conflicts within a single edit session)
- Run `pytest tests/unit/test_idea_format.py` after T004 to confirm all six tests pass

### Parallel Opportunities

- T005 and T006 (polish phase) can run in parallel — different tools, no shared output

---

## Parallel Example: User Story 1

```bash
# No parallelism within US1 (all changes in the same file)
# Sequential order: T001 → T002 → T003 → T004

# Polish phase (run in parallel after T004):
Task T005: pytest (test suite)
Task T006: ruff check . (lint)
```

---

## Implementation Strategy

### MVP (User Story 1 only — the only story in scope)

1. Write T001 tests first — confirm they fail before implementation
2. Implement T002 (prompt change) — re-run T001 prompt guard tests, expect pass for guards 1 & 2
3. Implement T003 (parser fallback) — re-run T001 parser test, expect pass for guard 3
4. Implement T004 (docstring) — cosmetic only, no test impact
5. Run `pytest tests/unit/test_idea_format.py` after T004 — all six tests green
6. Run full test suite (T005) — confirm zero regressions
6. Run ruff (T006) — confirm clean lint

### Total Tasks: 6

| Phase | Tasks | Count |
|-------|-------|-------|
| US1 Tests | T001 | 1 |
| US1 Implementation | T002, T003, T004 | 3 |
| Polish | T005, T006 | 2 |
| **Total** | | **6** |

---

## Notes

- All 6 tasks touch only 2 files: `agent/summarizer/claude_summarizer.py` and `tests/unit/test_idea_format.py`
- No data model changes, no new dependencies, no config changes
- T001 test file is new — it does not replace or conflict with `tests/unit/test_summarizer.py`
- Commit after T004 (implementation complete), then again after T005+T006 (polish clean)
