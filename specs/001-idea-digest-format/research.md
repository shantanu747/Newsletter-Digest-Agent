# Research: Idea-Based Digest Format

**Feature**: 001-idea-digest-format | **Date**: 2026-04-08

## Resolved Questions

All unknowns were resolved through direct codebase exploration. No external research required.

---

### R-001: Existing Summarization Pipeline

**Decision**: Extend `ClaudeSummarizer` with a second method rather than subclassing or replacing.  
**Rationale**: The existing `summarize()` method is called from a single location (`runner.py`) and is well-tested. Adding `summarize_as_ideas()` alongside it is the lowest-risk change. The caller routes based on `digest_format` config.  
**Alternatives considered**: New summarizer subclass — rejected because it duplicates the rate-limiter and retry logic; prompt-only swap on the same method — rejected because it breaks classic mode and the return type would need to change.

---

### R-002: Idea-Based Prompt Structure

**Decision**: Use a structured output format where the model returns each idea as a delimited block.

**Prompt template**:

```
System:
You are a plugged-in, well-informed advisor who cuts through noise.
You do not sugarcoat. You do not pad. You present information in a
grounded, rational, and succinct way.

Your reader holds: {portfolio_lines}
Their interests: {interests_list}
Standing instructions: {custom_prompts}

Given the newsletter text below, identify each discrete idea.
For each idea that is relevant to the reader's holdings, interests,
or that would make a well-informed person meaningfully more aware,
output:

IDEA: <short title (≤8 words)>
<1–3 sentence summary. No filler. No hedging. No transitional phrases.>

If no ideas are relevant, output exactly:
IDEA: No High-Signal Content
Nothing in this newsletter warrants your attention.

Do not include URLs. Do not include links.
```

**Rationale**: Delimiter-based parsing (`IDEA:` prefix) is simple, robust, and doesn't require JSON mode or structured outputs. The model reliably follows this pattern with Claude Sonnet.  
**Alternatives considered**: JSON output (`{"ideas": [...]}`) — rejected because it's more brittle with long content and adds parsing complexity for no gain; free-form prose with post-hoc extraction — rejected because it's unpredictable.

---

### R-003: Response Parsing Strategy

**Decision**: Parse the model response by splitting on `\nIDEA:` and stripping the resulting segments.

```python
def _parse_ideas(raw: str) -> tuple[Idea, ...]:
    segments = re.split(r'\nIDEA:', '\nIDEA:' + raw.strip())
    ideas = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        lines = seg.split('\n', 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if title:
            ideas.append(Idea(title=title, summary_text=body))
    return tuple(ideas)
```

**Rationale**: Regex split on the delimiter is deterministic and handles edge cases (leading/trailing whitespace, empty sections). No third-party parsing libraries needed.  
**Alternatives considered**: Line-by-line state machine — rejected as more code for same result; `json.loads()` — rejected (see R-002).

---

### R-004: Global Toggle Config Key

**Decision**: Add `digest_format: "classic"` to `config/newsletters.yaml` as a top-level key. Accepted values: `"classic"` | `"idea_based"`. Default if absent: `"classic"`.

**Rationale**: Consistent with existing top-level config keys (`summary_length_mode`, `summary_word_target`). A single key is the simplest toggle. Default `"classic"` means the change is non-breaking for any existing config file.  
**Alternatives considered**: Environment variable toggle — rejected because this is a user-facing preference, not an operational secret; per-sender toggle — rejected per the clarification decision (global toggle is sufficient for before/after comparison).

---

### R-005: Link Stripping Location

**Decision**: Strip links in `runner.py` at `DigestEntry` construction time when `digest_format == "idea_based"`. Pass `links=()`.

**Rationale**: The `DigestEntry.links` field already accepts an empty tuple, and the Jinja2 template's `{% if entry.links %}` block already handles it correctly — no template change needed for link removal. This avoids modifying `EmailParser`, which would change behavior for all modes.  
**Alternatives considered**: Strip in template (conditional on format) — rejected because it leaks format-routing logic into the template layer; strip in `EmailParser` — rejected because the parser's job is extraction, not output formatting.

---

### R-006: User Profile Injection into Prompt

**Decision**: Inject user profile directly into the system prompt as plain text. Portfolio formatted as `TICKER (Company Name)` lines. Interests as a comma-separated list. Custom prompts appended verbatim.

**Rationale**: The advisor (`analyzer.py`) already follows this pattern successfully. Consistency is preferable to inventing a new injection strategy.  
**Alternatives considered**: Tool use / structured context passing — rejected (overkill for a list of tickers and interest categories).

---

### R-007: Template Changes for Idea Rendering

**Decision**: Add a new Jinja2 block inside each entry card that renders `entry.summary.ideas` when the list is non-empty. The classic `summary_text` block renders when `entry.summary.ideas` is `None` or empty. No new template file — the existing `digest.html.j2` handles both modes via a single conditional.

```jinja2
{% if entry.summary.ideas %}
  {% for idea in entry.summary.ideas %}
  <div class="idea-card">
    <p class="idea-title">{{ idea.title }}</p>
    <p class="idea-body">{{ idea.summary_text | nl2br }}</p>
  </div>
  {% endfor %}
{% else %}
  <p class="summary-text">{{ entry.summary.summary_text | nl2br }}</p>
{% endif %}
```

**Rationale**: Single template handles both modes, keeping the rendering layer simple. The `digest_format` context variable is not needed in the template — the presence of `ideas` is self-describing.  
**Alternatives considered**: Two separate template files — rejected (doubles maintenance burden for a small structural difference).
