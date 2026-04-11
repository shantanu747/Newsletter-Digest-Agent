# Tasks: Idea-Based Digest Format with No Links

**Input**: Design documents from `/specs/001-idea-digest-format/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths included in all descriptions

---

## Phase 1: Setup

**Purpose**: Add the global format toggle to configuration so all downstream tasks have a concrete value to key off.

- [x] T001 Add `digest_format: "idea_based"` key (with inline comment explaining valid values `"classic"` | `"idea_based"`) to `config/newsletters.yaml`

**Checkpoint**: Config file has the toggle in place. Running `python -c "import yaml; d=yaml.safe_load(open('config/newsletters.yaml')); print(d['digest_format'])"` from repo root should print `idea_based`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Data model and config-loading changes that every user story phase depends on. Must be complete before any story work begins.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T002 Add frozen `Idea` dataclass (`title: str`, `summary_text: str`) to `agent/utils/models.py`, positioned above the `Summary` dataclass
- [x] T003 [P] Add `digest_format: Literal["classic", "idea_based"]` field to `AgentConfiguration` dataclass in `agent/utils/models.py` (default `"classic"`)
- [x] T004 [P] Update `load_config()` in `agent/utils/config.py` to read the optional `digest_format` key from `newsletters.yaml` (validate it is one of the two accepted literals; raise `ConfigurationError` on invalid value; default to `"classic"` when absent)

**Checkpoint**: `python -c "from agent.utils.config import load_config; c = load_config(); print(c.digest_format)"` prints `idea_based` (given T001 config value). `Idea` is importable from `agent.utils.models`.

---

## Phase 3: User Story 1 — Idea-by-Idea Digest Summary (Priority: P1) 🎯 MVP

**Goal**: When `digest_format == "idea_based"`, each newsletter email is decomposed into discrete ideas and rendered as titled idea cards in the digest — replacing the word-count summary blob.

**Independent Test**: Set `digest_format: "idea_based"` in `config/newsletters.yaml`, run the agent in dry-run mode (`python -m agent.runner --dry-run`), and confirm the stdout output lists idea titles with 1–3 sentence summaries and no "X words / Y%" statistics.

- [x] T005 [US1] Add `ideas: tuple[Idea, ...] | None` field (default `None`) to the `Summary` frozen dataclass in `agent/utils/models.py`; update any `Summary(...)` construction sites in the codebase to pass `ideas=None` explicitly so existing call sites remain valid
- [x] T006 [US1] Add module-level `_IDEA_SYSTEM_PROMPT_TEMPLATE` string constant to `agent/summarizer/claude_summarizer.py` containing the idea-decomposition prompt (persona: plugged-in advisor; output format: `IDEA: <title>\n<1–3 sentence summary>`; no URLs; "No High-Signal Content" fallback; include the clause "If the entire email is a single idea, output exactly one IDEA entry" to handle short emails; include "Output only ideas derivable from the text provided — do not infer or fabricate" — see research.md R-002 for base prompt text)
- [x] T007 [US1] Add `_parse_ideas(raw: str) -> tuple[Idea, ...]` private function to `agent/summarizer/claude_summarizer.py` that splits on `\nIDEA:` delimiter and returns a tuple of `Idea` objects (see research.md R-003 for implementation); if the parsed result is an empty tuple (model returned no IDEA blocks), return a single-element tuple `(Idea(title="No High-Signal Content", summary_text="Nothing in this newsletter warrants your attention."),)` to satisfy FR-007 at the code level rather than relying solely on the prompt fallback
- [x] T008 [US1] Add `summarize_as_ideas(self, email: Email, user_profile: UserProfile | None) -> Summary` method to `ClaudeSummarizer` in `agent/summarizer/claude_summarizer.py`; method MUST emit a `structlog` log event at the start of each call with fields `newsletter_id=email.id`, `sender=email.sender`, `digest_format="idea_based"` (Constitution Principle V); then uses `_IDEA_SYSTEM_PROMPT_TEMPLATE`, calls the Anthropic API through the existing rate-limiter and retry path, calls `_parse_ideas()` on the response, and returns a `Summary` with `ideas` populated and `summary_text=""`, `word_count=0`
- [x] T009 [US1] Add the idea-cards rendering block to `templates/digest.html.j2` inside each entry card: `{% if entry.summary.ideas %}` → render each `Idea` as a titled card (`idea-title` + `idea-body` paragraphs styled inline); `{% else %}` → existing `summary_text` block unchanged. Also add minimal inline CSS for `.idea-title` (bold, slightly larger) and `.idea-body` (normal weight) within the `<style>` block already present in the template
- [x] T010 [US1] Update the per-batch summarization loop in `agent/runner.py` to call `summarizer.summarize_as_ideas(email, config.user_profile)` when `config.digest_format == "idea_based"` and the existing `summarizer.summarize(email)` otherwise; no other changes to the loop

**Checkpoint**: Dry-run output shows idea cards with titles and 1–3 sentence summaries. No word-count or percentage-of-original text appears anywhere in the output.

---

## Phase 4: User Story 2 — Remove Links Passthrough (Priority: P2)

**Goal**: When `digest_format == "idea_based"`, the "Further Reading" section is absent from every digest entry — no URLs or hyperlinks appear in the output.

**Independent Test**: Run agent in dry-run mode with `digest_format: "idea_based"` against any newsletter that contains links. Grep the stdout output for `http` — should return no matches.

- [x] T011 [US2] In `agent/runner.py`, update the `DigestEntry(...)` construction inside the per-batch loop to pass `links=()` when `config.digest_format == "idea_based"`; the existing `{% if entry.links %}` guard in the template already handles the empty tuple without rendering the Further Reading section — no template change required

**Checkpoint**: Dry-run output contains no URLs. The "Further Reading" section does not appear in any entry card when `digest_format == "idea_based"`.

---

## Phase 5: User Story 3 — Relevance-Filtered Idea Selection (Priority: P3)

**Goal**: The idea-based prompt is personalized with the reader's portfolio, interests, watchlist, and custom prompts from `config/user_profile.yaml`, so the model filters ideas for relevance to the reader's specific context.

**Independent Test**: With a newsletter covering a mix of topics — one directly tied to a ticker in `user_profile.yaml` (e.g., NVDA earnings) and one clearly unrelated (e.g., a recipe) — confirm the digest includes the NVDA idea and omits the recipe idea.

- [x] T012 [US3] Update `_IDEA_SYSTEM_PROMPT_TEMPLATE` in `agent/summarizer/claude_summarizer.py` to include placeholder slots for `{portfolio_lines}`, `{interests_list}`, and `{custom_prompts}` (see research.md R-006 for injection format)
- [x] T013 [US3] Update `summarize_as_ideas()` in `agent/summarizer/claude_summarizer.py` to format `_IDEA_SYSTEM_PROMPT_TEMPLATE` with the user profile fields when `user_profile` is not `None`; when `user_profile` is `None`, format with empty strings for each placeholder so the prompt degrades gracefully (agent still applies general-informedness filtering)
- [x] T014 [US3] Verify `agent/runner.py` already passes `config.user_profile` to `summarize_as_ideas()` (set in T010); if `config.user_profile` is `None` (file absent), confirm the call still works with the graceful fallback from T013 — no code change needed if T010 was implemented correctly; otherwise adjust the call site

**Checkpoint**: Dry-run against a mixed newsletter shows only relevant ideas. Running with `user_profile.yaml` absent (or renamed temporarily) still produces idea-based output without crashing.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T015 [P] Audit all `structlog` log calls added or touched in T008 and T010 in `agent/summarizer/claude_summarizer.py` and `agent/runner.py` to confirm they include `digest_format=` as a structured field so each run is traceable in logs
- [x] T016 [P] Run `ruff check agent/ templates/` from repo root and resolve any linting errors introduced by the new code

**Checkpoint**: `ruff check` exits clean. Logs include `digest_format` field on every summarization and entry-construction event.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — **blocks all story phases**
- **Phase 3 (US1)**: Depends on Phase 2 — T005 → T006/T007 [P] → T008 → T009/T010 [P]
- **Phase 4 (US2)**: Depends on Phase 2 — T011 is a single-line change; can run alongside Phase 3 if desired since it touches a different section of `runner.py`
- **Phase 5 (US3)**: Depends on Phase 3 (T008 must exist before T012–T013 can modify it)
- **Phase 6 (Polish)**: Depends on all story phases complete

### Within-Story Task Order (Phase 3)

```
T005 (models.py — Summary update)
  ↓
T006, T007 [parallel] (new prompt constant + parse function)
  ↓
T008 (summarize_as_ideas method — depends on T006, T007)
  ↓
T009, T010 [parallel] (template block + runner routing — both depend on T008)
```

### Parallel Opportunities

```bash
# Phase 2 — run together (different files):
T003: AgentConfiguration field in models.py
T004: config.py load_config() update

# Phase 3 — run together after T005:
T006: _IDEA_SYSTEM_PROMPT_TEMPLATE constant
T007: _parse_ideas() function

# Phase 3 — run together after T008:
T009: template idea-cards block
T010: runner routing logic

# Phase 6 — run together:
T015: structlog audit
T016: ruff lint check
```

---

## Implementation Strategy

### MVP (User Story 1 Only — Phases 1–3)

1. Complete Phase 1: add config key
2. Complete Phase 2: `Idea` dataclass + `AgentConfiguration.digest_format` + config parsing
3. Complete Phase 3: new summarizer method + template block + runner routing
4. **STOP and VALIDATE**: dry-run shows idea cards, no word-count stats

### Incremental Delivery

1. Phases 1–3 → idea decomposition working → validate MVP
2. Phase 4 → links stripped → validate no URLs in output
3. Phase 5 → user profile injected → validate relevance filtering
4. Phase 6 → polish → validate logs + linting

---

## Notes

- No test tasks generated (not requested in spec)
- `is_pass_through` emails skip `ClaudeSummarizer` entirely (existing behavior) — `summarize_as_ideas()` is never called for them; no changes needed
- The "View Original Email" structural link in the template is NOT stripped — spec targets "Further Reading" content links only (see spec FR-005 interpretation in plan.md)
- T014 is a verification task — it may require zero code changes if T010 was implemented correctly
