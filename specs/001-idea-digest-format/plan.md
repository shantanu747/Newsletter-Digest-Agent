# Implementation Plan: Idea-Based Digest Format with No Links

**Branch**: `001-idea-digest-format` | **Date**: 2026-04-08 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/001-idea-digest-format/spec.md`

## Summary

Replace the word-count summarization pipeline with an idea-decomposition pipeline. Each newsletter email is broken into discrete ideas (title + 1–3 sentence summary), filtered for relevance against `config/user_profile.yaml`, and rendered in the digest without any "Further Reading" links. A global `digest_format` toggle in `config/newsletters.yaml` allows switching between the new `idea_based` format and the existing `classic` format for before/after comparison.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: `anthropic` SDK, `Jinja2`, `PyYAML`, `structlog`, `pytest` + `pytest-mock`  
**Storage**: Files only — `config/newsletters.yaml` (format toggle), `config/user_profile.yaml` (relevance signals). No schema migrations.  
**Testing**: `pytest` + `pytest-mock`  
**Target Platform**: Linux/macOS server process  
**Project Type**: CLI agent / scheduled pipeline  
**Performance Goals**: No new latency targets; idea-based prompt will produce more tokens per email than classic — acceptable given existing rate-limiter  
**Constraints**: Must not break classic mode; no new secrets or environment variables required  
**Scale/Scope**: One Claude call per email (same as classic mode); prompt changes only

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I. Separation of Concerns | PASS | New `Idea` dataclass and idea-prompt logic stay inside `ClaudeSummarizer`; no inline API calls elsewhere |
| II. Secrets Management | PASS | No new secrets; `digest_format` toggle is non-secret config in `newsletters.yaml` |
| III. Typed Data Transfer | PASS | New `Idea` dataclass added; all inter-module transfers remain typed dataclasses |
| IV. Reliability & Rate Limiting | PASS | Existing rate limiter and retry logic unchanged; new prompt uses same call path |
| V. Observability | PASS | All log calls remain `structlog`; no `print()` introduced |

No gate violations. No Complexity Tracking required.

## Project Structure

### Documentation (this feature)

```text
specs/001-idea-digest-format/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
└── tasks.md             ← Phase 2 output (/speckit.tasks)
```

### Source Code Changes

```text
agent/utils/models.py                      ← add Idea dataclass; update Summary; update AgentConfiguration
agent/utils/config.py                      ← parse digest_format from newsletters.yaml
agent/summarizer/claude_summarizer.py      ← add idea-based prompt + summarize_as_ideas() method
agent/runner.py                            ← route to classic vs idea-based; strip links in idea mode
templates/digest.html.j2                   ← add idea-list rendering block
config/newsletters.yaml                    ← add digest_format field (default: "classic")

tests/unit/test_summarizer.py              ← (deferred — tests not in scope for this feature)
tests/unit/test_models.py                  ← (deferred — tests not in scope for this feature)
tests/unit/test_config.py                  ← (deferred — tests not in scope for this feature)
tests/integration/test_runner.py           ← (deferred — tests not in scope for this feature)
```

## Phase 0: Research

See [research.md](research.md).

## Phase 1: Design

See [data-model.md](data-model.md).

### Design Decisions

**1. Global Toggle Placement**  
`digest_format: "classic" | "idea_based"` added to `config/newsletters.yaml` at the top level. Parsed into `AgentConfiguration.digest_format`. Default `"classic"` ensures backwards compatibility.

**2. New `Idea` Dataclass**  
A frozen dataclass `Idea(title: str, summary_text: str)` is added to `models.py`. It holds one decomposed idea from an email. `Summary` gains an optional `ideas: tuple[Idea, ...] | None` field — `None` in classic mode, populated in idea-based mode. `word_count` is kept for classic mode compatibility but not rendered.

**3. Summarizer Extension (no new class)**  
`ClaudeSummarizer` gets a second method: `summarize_as_ideas(email, user_profile) -> Summary`. It uses a new system prompt (see research.md) and parses the structured response into `Idea` tuples. The existing `summarize()` method is unchanged.

**4. Link Stripping**  
In `runner.py`, when `digest_format == "idea_based"`, `DigestEntry` is constructed with `links=()`. No change to `EmailParser` (links are still extracted but discarded at the runner level). The "Further Reading" block in the template already guards on `{% if entry.links %}` — passing an empty tuple means it simply doesn't render. The "View Original Email" structural link is preserved (it's navigation, not content passthrough).

**5. Template Rendering**  
The Jinja2 template receives `digest_format` as a new context variable. In each entry card, a new block renders `entry.summary.ideas` as a list of titled cards when `digest_format == "idea_based"`. In classic mode the existing `summary_text` block renders unchanged.

**6. Relevance Filtering in Prompt**  
The idea-based prompt injects the user's `interests`, `portfolio` tickers/names, and `custom_prompts` directly into the system prompt. The model is instructed to omit ideas with no relevance to those signals or to general informedness. If all ideas are filtered, it returns a single `Idea` with title `"No High-Signal Content"` and a brief explanation — satisfying FR-007 without adding special-case logic in the runner.
