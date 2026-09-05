# Plan 01 — Model upgrade to `claude-sonnet-5` + knowledge-extraction wiring fix

**Branch:** `improvements/model-upgrade-sonnet-5` (cut from `main`)
**Depends on:** nothing
**Unblocks:** plans 02, 03, 04 (all three rely on entities actually being recorded in the store)

## Why

1. **The per-newsletter model is a generation behind.** `ClaudeSummarizer`, `AdvisorAnalyzer`, and
   `scripts/grade_extraction.py` hard-code `claude-sonnet-4-6`. `claude-sonnet-5` is stronger and
   cheaper ($2 / $10 per MTok vs $3 / $15). The Signals Report already runs `claude-opus-5` via
   `signals.model` and is **not** changed by this plan.
2. **Entity extraction never runs in production.** `NewsletterAgent.__init__`
   ([agent/runner.py:47-54](../agent/runner.py#L47-L54)) constructs `ClaudeSummarizer` without
   `knowledge_config=config.knowledge`. `_build_entity_section` therefore returns `""`, the prompt
   never asks for `ENTITIES:` lines, `_parse_ideas` yields `Idea.entities == ()`, and
   `ObservationStore.record_summary` records nothing. `data/signals.db` does not exist on the
   user's machine today, which is consistent with this. Everything downstream (trends, synthesis,
   badges, track record) needs this fixed first.
3. **The hard-coded model string is repeated in three places.** Introduce one config key so the next
   upgrade is a YAML edit.

## What changes, at a glance

| Area | Change |
|---|---|
| Config | New optional top-level YAML key `model` → `AgentConfiguration.model` (default `"claude-sonnet-5"`). |
| Summarizer | `ClaudeSummarizer(..., model=)`; both call sites use it; `max_tokens` raised; text extracted via shared helper. |
| Advisor | `AdvisorAnalyzer(..., model=)`; `max_tokens` raised; text via shared helper; **rate limiter added** (constitution gap). |
| Runner | Pass `model=config.model` **and** `knowledge_config=config.knowledge` to the summarizer; pass `model=` to the advisor. |
| Shared helper | `agent/utils/anthropic_text.py::extract_text(response)` — moved from `agent/trends/analyzer.py::_extract_text`. |
| Script | `scripts/grade_extraction.py` → `claude-sonnet-5` + helper. |
| Tests | Mock content blocks gain `type="text"`; new tests for config key, model pass-through, knowledge wiring, helper. |
| Docs | README line 73, `config/newsletters.yaml` comment, `requirements.txt`/`pyproject.toml` pin alignment. |

## Claude Sonnet 5 facts that drive the details (verified against `anthropic==0.84.0`)

- **Adaptive thinking is on by default** when `thinking` is omitted. Thinking tokens count against
  `max_tokens`. Our current budgets (1024 / 2048 / 1200) can be consumed by thinking before the
  answer finishes, producing truncated `ENTITIES:` lines or a missing `SIGNALS` section. Hence the
  `max_tokens` increases below.
- Because thinking blocks can be returned **before** the text block, `response.content[0].text` is
  unsafe. `agent/trends/analyzer.py::_extract_text` already iterates `type == "text"` blocks; make
  that the single shared implementation.
- Effort is controlled with `output_config={"effort": "low" | "medium" | "high" | "max"}`. The
  summarization and advisor tasks are extraction/formatting work, not deep reasoning, so use
  `effort: "low"` there — it keeps latency and cost near today's while staying on the adaptive path
  (preferred over `thinking={"type": "disabled"}`). Do **not** send `temperature`, `top_p`,
  `budget_tokens`, or assistant prefill — Sonnet 5 rejects them with HTTP 400.
- Sonnet 5's tokenizer produces ~30% more tokens for the same text. No code change; noted for
  cost expectations.
- Sonnet 5 follows instructions more literally. The existing prompts are explicit enough; do not
  rewrite them in this plan. (If real-run output regresses, that is a follow-up, not this branch.)

## Steps

Each step: implement → run `.venv/bin/python -m pytest -q -m "not integration"` → `ruff check <touched files>` → commit.

### Step 1 — Shared response-text helper

Create `agent/utils/anthropic_text.py`:

```python
"""Helpers for reading Anthropic Messages responses.

Sonnet 5 / Opus 5 may return thinking blocks before the text block, and server-side tool
blocks can also precede it, so callers must never index ``response.content[0]``.
"""

from __future__ import annotations


def extract_text(response) -> str:
    """Concatenate every ``type == "text"`` content block, stripped of surrounding whitespace.

    Returns "" when the response has no text blocks (e.g. ``stop_reason == "refusal"``).
    """
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()
```

- In `agent/trends/analyzer.py`, delete `_extract_text` (lines 126–133) and
  `from agent.utils.anthropic_text import extract_text`; replace the one call site at line 228.
- Tests: `tests/unit/test_anthropic_text.py`
  - `test_single_text_block_returned_stripped`
  - `test_thinking_block_before_text_is_skipped` (blocks: `MagicMock(type="thinking", thinking="...")`, then text)
  - `test_multiple_text_blocks_concatenated_in_order`
  - `test_no_text_blocks_returns_empty_string`
  - `test_block_without_type_attribute_is_ignored` (a bare `MagicMock()` where `type` is a MagicMock, not `"text"`)
- `tests/unit/test_trend_analyzer.py` must still pass unchanged.

### Step 2 — Config key

`agent/utils/config.py`:
- Add to `AgentConfiguration` after the `digest_format` field:
  ```python
  # Model used for per-newsletter summarization and the daily advisor section.
  # The Signals Report has its own `signals.model` (defaults to claude-opus-5).
  model: str = "claude-sonnet-5"
  ```
- In `load_config`, alongside the other scalar reads: `model=str(raw.get("model", "claude-sonnet-5"))`.
  Empty string → treat as default: `str(raw.get("model") or "claude-sonnet-5")`.
- `load_config` does not validate unknown *top-level* keys, so nothing else is needed for parsing.

`config/newsletters.yaml`: add, directly under the `digest_format` block:
```yaml
# Claude model for per-newsletter summaries and the daily advisor section.
# The periodic Signals Report uses `signals.model` instead.
model: "claude-sonnet-5"
```

`tests/unit/test_config.py` (or the existing config test module — find it with `grep -rl "load_config" tests`):
- `test_model_defaults_to_sonnet_5_when_key_absent`
- `test_model_key_is_read_from_yaml`
- `test_empty_model_string_falls_back_to_default`

### Step 3 — Summarizer

`agent/summarizer/claude_summarizer.py`:
- Add module constants near the top:
  ```python
  _DEFAULT_MODEL = "claude-sonnet-5"
  _SUMMARY_MAX_TOKENS = 2048       # was 1024; adaptive thinking shares this budget
  _IDEAS_MAX_TOKENS = 4096         # was 2048
  _OUTPUT_CONFIG = {"effort": "low"}  # extraction work — keep thinking short
  ```
- `__init__` gains keyword-only `model: str = _DEFAULT_MODEL`, stored as `self._model`.
- Both `messages.create(...)` calls (lines 239 and 318) become
  `model=self._model, max_tokens=<constant>, output_config=_OUTPUT_CONFIG, system=..., messages=...`.
- Replace `response.content[0].text.strip()` at lines 244 and 323 with `extract_text(response)`
  (keep the `.replace("**", "")` on the classic path).
- After extracting, log `stop_reason=getattr(response, "stop_reason", None)` in the existing
  `newsletter_summarized` / `newsletter_ideas_extracted` info logs. If `stop_reason == "max_tokens"`,
  also emit `self._log.warning("summary_truncated", message_id=email.id)` — do not retry, the
  partial output is still used (matches current behavior).
- Fix the class docstring at line 159 (`"...using the Claude claude-sonnet-4-6 model"`) to
  `"Summarizes newsletter emails with the configured Claude model (default claude-sonnet-5)."`

Tests:
- Update `_make_api_response` helpers in `tests/test_claude_summarizer.py:36`,
  `tests/unit/test_idea_format.py:34`, `tests/unit/test_summarizer.py:36` to
  `content_block = MagicMock(type="text", text=text)`.
- `tests/test_claude_summarizer.py:99-113` currently asserts `claude-sonnet-4-6`; change it to assert
  the default `claude-sonnet-5`, and add `test_model_kwarg_overrides_default` constructing
  `ClaudeSummarizer(api_key="k", model="claude-test-x", ...)` and asserting `call_kwargs.kwargs["model"] == "claude-test-x"`.
- Add `test_summarize_uses_raised_max_tokens_and_low_effort` asserting `max_tokens == 2048` and
  `output_config == {"effort": "low"}`; same for `summarize_as_ideas` with `4096`.
- Add `test_thinking_block_before_text_still_parses_ideas` — response content
  `[MagicMock(type="thinking", thinking="…"), MagicMock(type="text", text="IDEA: …")]` yields ideas.
- Add `test_max_tokens_stop_reason_logs_truncation_warning` (patch the logger or use `structlog` capture — follow whatever pattern the existing tests use; if none, assert via `mocker.patch.object(summarizer._log, "warning")`).
- The byte-identical-prompt test in `test_idea_format.py` must still pass.

### Step 4 — Advisor

`agent/advisor/analyzer.py`:
- Constants: `_DEFAULT_MODEL = "claude-sonnet-5"`, `_MAX_TOKENS = 2400` (was 1200),
  `_OUTPUT_CONFIG = {"effort": "low"}`.
- `__init__(self, api_key, user_profile, *, model: str = _DEFAULT_MODEL)`; store `self._model`.
- **Add the rate limiter the constitution requires and the summarizer already has:**
  `from agent.utils.rate_limiter import TokenBucketLimiter` (confirm the import path by reading
  `agent/summarizer/claude_summarizer.py`), `self._limiter = TokenBucketLimiter(rate=0.5, capacity=1)`,
  and call `self._limiter.acquire()` inside the retry loop before `messages.create`.
- `messages.create(model=self._model, max_tokens=_MAX_TOKENS, output_config=_OUTPUT_CONFIG, ...)`.
- Line 145 → `raw_text = extract_text(response).replace("**", "")`.
- Log `stop_reason` in `advisor_analysis_complete`.

Tests (`tests/test_advisor_analyzer.py`):
- `_mock_response` → `MagicMock(type="text", text=text)`.
- Patch the limiter in tests that exercise `analyze` (mirror `tests/unit/test_trend_analyzer.py:90`:
  `mocker.patch("agent.advisor.analyzer.TokenBucketLimiter.acquire")`).
- Add `test_default_model_is_sonnet_5`, `test_model_kwarg_overrides_default`,
  `test_rate_limiter_acquired_before_every_attempt` (3 API errors → `acquire.call_count == 3`),
  `test_thinking_block_before_text_still_parses`.

### Step 5 — Runner wiring (two commits)

Commit A — `fix(runner): pass knowledge_config to the summarizer so entity extraction runs`
- `agent/runner.py:47-54`: add `knowledge_config=config.knowledge,`.
- Test in `tests/unit/test_runner_wiring.py` (new; runner tests may not exist — check
  `grep -rl "NewsletterAgent" tests` first and extend an existing module if one does):
  `test_summarizer_receives_knowledge_config` — patch `agent.runner.ClaudeSummarizer`,
  `agent.runner.GmailFetcher`, `agent.runner.EmailDelivery`, construct `NewsletterAgent(config)`
  with a config whose `knowledge=KnowledgeConfig(enabled=True, ...)`, assert the patched
  class was called with `knowledge_config=config.knowledge`.

Commit B — `feat(runner): route configured model to summarizer and advisor`
- Add `model=config.model` to the `ClaudeSummarizer(...)` call and to the `AdvisorAnalyzer(...)`
  call at `agent/runner.py:171-174`.
- Tests: `test_summarizer_receives_configured_model`; for the advisor, the construction happens
  inside `_run_digest`, so test it the same way `tests/unit/test_signals_cadence.py` drives the
  runner — if that proves awkward, a focused test that patches `agent.advisor.analyzer.AdvisorAnalyzer`
  and calls `_run_digest` with one fake email is acceptable. Do not skip this test.

### Step 6 — Script, pins, docs

- `scripts/grade_extraction.py:121-125`: `model="claude-sonnet-5"`, `max_tokens=2048`,
  `output_config={"effort": "low"}`, `grade_text = extract_text(response)`. This file is in the
  pre-existing ruff-error set; fix **only** lint on lines you touch.
- `pyproject.toml:7` and `requirements.txt:2`: pin both to `anthropic>=0.84.0` — the installed
  version, verified to accept `output_config={"effort": ...}` and `thinking={"type": "adaptive"}`.
  (Today the two files disagree: `>=0.40.0` vs `>=0.60.0`.) No other dependency changes.
- `README.md:73`: `Claude Sonnet 5 (configurable via \`model\`) — best cost/quality tradeoff for summarization`.
  Add one sentence to the configuration section documenting the `model` key and that
  `signals.model` is separate.
- `CLAUDE.md` "Recent Changes": add a line for `001-model-upgrade-sonnet-5`.

## Out of scope (do not do in this branch)

- Rewriting prompts for Sonnet 5's more literal instruction-following.
- Changing `signals.model` or anything in `agent/trends/`, beyond removing `_extract_text`.
- Streaming. Responses are ≤4096 tokens; not needed.
- Handling `stop_reason == "refusal"` specially — `extract_text` returning `""` already degrades
  to an empty summary/ideas list on the existing code paths.
- Any store, template, or synthesis work (plans 02–04).

## Acceptance checklist

- [ ] `grep -rn "sonnet-4-6" agent scripts tests README.md config` returns nothing.
- [ ] `grep -rn "content\[0\]" agent scripts` returns nothing.
- [ ] `ClaudeSummarizer` and `AdvisorAnalyzer` accept `model=`; runner passes `config.model` to both.
- [ ] Runner passes `knowledge_config=config.knowledge` to `ClaudeSummarizer` (test proves it).
- [ ] `AdvisorAnalyzer` acquires the rate limiter before every attempt (test proves it).
- [ ] All four response-mock helpers use `type="text"`; a thinking-block-first response parses correctly in summarizer, ideas, and advisor tests.
- [ ] `pytest -q -m "not integration"` green (≥ 274 + new tests); `ruff check agent/` clean; `ruff check` on every touched file clean.
- [ ] Manual smoke (user runs it, not CI): `python -m agent --dry-run --once` with `digest_format: idea_based` and `knowledge_graph.enabled: true` shows `ENTITIES:`-derived entities on ideas (dry-run prints the digest; entities are visible in the log line `newsletter_ideas_extracted` — add `entity_count=sum(len(i.entities) for i in ideas)` to that log line so the smoke check is one grep).
