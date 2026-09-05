# Plan 02 — Cross-newsletter theme synthesis (P3, tasks T066–T072)

**Branch:** `feature/theme-synthesis` (cut from `main` after plan 01 merges)
**Depends on:** plan 01 (entities must actually be extracted; `extract_text` helper; `config.model`)
**Unblocks:** plan 03 (shares the "context block above the entries" template pattern)

## Why

When four newsletters cover the same story, today's digest makes the reader read it four times.
The spec for `001-signals-knowledge-graph` already designed the fix as User Story 3 (P3) and
left tasks T066–T072 unchecked in
[specs/001-signals-knowledge-graph/tasks.md](../specs/001-signals-knowledge-graph/tasks.md).
This plan implements exactly those tasks, with the open design points resolved below.

Reader-facing result: a **"Today's Themes"** block near the top of the digest. Each theme has a
title, a merged body that names every contributing newsletter, and — when sources disagree — an
explicit "Where they disagree" line. Ideas absorbed into a theme are not repeated in their
newsletter's section, but **every newsletter still appears** (constitution + recall-integration
principle: profile/context frames and orders, never suppresses a newsletter).

## Design decisions (resolving the "or" / "TBD" points in the tasks)

| Question | Decision | Reason |
|---|---|---|
| Where does the flag live? (T067 says `SignalsConfig` *or* a new section) | `KnowledgeConfig.synthesis_enabled: bool = False` | Synthesis depends on entity extraction (knowledge graph), **not** on the Signals Report. A user can want themes without a weekly report. |
| What counts as "shared entities"? | Two ideas are linked when they share **≥ 2** entities after `normalize_key`. Clusters are connected components (union-find). | One shared entity ("Fed", "Nvidia") links nearly everything on a busy day. Two is the smallest number that means "same story." Constant `_MIN_SHARED_ENTITIES = 2`. |
| Minimum cluster shape | ≥ 2 **distinct senders** (T068, FR-049). Sender = `Summary.sender` compared case-insensitively. | Mandated. |
| How many themes? | At most `_MAX_THEMES = 5` per batch, ranked by distinct-sender count desc, then idea count desc, then first-appearance order. | Keeps the block scannable; the rest render as normal ideas. |
| Which model? | `config.model` (Sonnet 5 after plan 01), `max_tokens=1500`, `output_config={"effort": "medium"}`. | Reconciling sources needs a bit more thought than extraction; still not Opus-grade. |
| Absorbed ideas — what does the newsletter section show? | Ideas in a theme are omitted from their entry's idea list. If **all** of an entry's ideas are absorbed, the entry shows a one-line note: *"Covered in Today's Themes: {theme title}, {theme title}"*. | Never hide a newsletter; the reader can still see it arrived and where it went. |
| Dry-run | Print themes to console before the entries, same style as the advisor block. | Matches existing `--dry-run` UX. |

## Files

| File | Change |
|---|---|
| `agent/utils/models.py` | Add `Theme`; add `themes` to `DigestBatch`. |
| `agent/utils/config.py` | `KnowledgeConfig.synthesis_enabled`; add to `_KNOWN_KNOWLEDGE_KEYS`; parse it. |
| `agent/trends/synthesis.py` | **New.** `cluster_ideas`, `synthesize_themes`, `ThemeSynthesizer`. |
| `agent/runner.py` | Hook after summarization, before `DigestBatch` construction; dry-run printing. |
| `agent/digest/builder.py` | Compute `absorbed` lookup and pass to template. |
| `templates/digest.html.j2` | Theme block; absorbed-idea suppression; "covered in" note. |
| `config/newsletters.yaml` | `synthesis_enabled: false` under `knowledge_graph:` with a comment. |
| `tests/unit/test_synthesis.py` | **New.** |
| `tests/test_digest_builder.py` | Theme rendering + byte-identical tests. |
| `README.md`, `CLAUDE.md`, `specs/001-signals-knowledge-graph/tasks.md` | Docs; tick T066–T072. |

## Steps

### Step 1 — Data model + config

`agent/utils/models.py` (after `Idea`, before `Summary`):
```python
@dataclass(frozen=True)
class Theme:
    """A story told by several newsletters, merged into one reading (P3 synthesis)."""

    title: str
    body: str
    sources: tuple[str, ...]
    """Display names of every contributing newsletter, in cluster order."""
    disagreement: str | None
    """Where the sources conflict, stated plainly. None when they agree."""
    absorbed_idea_keys: tuple[tuple[str, int], ...]
    """(email_id, idea_index) pairs the renderer hides from per-newsletter sections."""
```
`DigestBatch`: add `themes: tuple[Theme, ...] = field(default_factory=tuple)` as the **last** field
(after `advisor`). Import `field` if not already imported.

`agent/utils/config.py`:
- `KnowledgeConfig.synthesis_enabled: bool = False` with docstring
  `"""Merge ideas that several newsletters share into a Today's Themes block."""`.
- `_KNOWN_KNOWLEDGE_KEYS` add `"synthesis_enabled"`.
- `_parse_knowledge_config`: `synthesis_enabled=bool(raw.get("synthesis_enabled", False))`.

`config/newsletters.yaml` under `knowledge_graph:`:
```yaml
  # Merge stories covered by 2+ newsletters into a "Today's Themes" block (needs enabled: true)
  synthesis_enabled: false
```

Tests (existing config test module): `test_synthesis_enabled_defaults_false`,
`test_synthesis_enabled_parsed_from_yaml`, and confirm the existing unknown-key test still rejects
a misspelling like `synthesis_enable`.

### Step 2 — Clustering (pure, deterministic, no I/O)

`agent/trends/synthesis.py` module docstring: what it does; that it never raises; that clustering
is deterministic and testable without a network.

```python
_MIN_SHARED_ENTITIES = 2
_MAX_THEMES = 5

IdeaKey = tuple[str, int]  # (email_id, idea_index)


def cluster_ideas(entries: Sequence[DigestEntry]) -> list[list[IdeaKey]]:
    """Group ideas that tell the same story across different newsletters.

    Two ideas are linked when they share at least ``_MIN_SHARED_ENTITIES`` entities after
    ``normalize_key``. Clusters are connected components of that link graph. Only clusters
    spanning ≥2 distinct senders are returned, ranked by sender count, then size, then the
    position of their earliest idea, and capped at ``_MAX_THEMES``.
    Pass-through entries and entries without ideas are ignored.
    """
```
Implementation notes:
- Build `keyed: list[tuple[IdeaKey, str /*sender lower*/, frozenset[str] /*norm entities*/]]`
  skipping `entry.is_pass_through`, `summary.ideas is None`, and ideas with `< _MIN_SHARED_ENTITIES` entities (they can't link).
- O(n²) pairwise comparison is fine (n ≤ ~100 ideas/batch). Union-find with a dict.
- Sender for an idea: `entry.summary.sender.lower()`.
- Return keys within a cluster in original order.

Tests (`tests/unit/test_synthesis.py`, class `TestClusterIdeas`), build entries with the
`_make_summary/_make_entry` helper style from `tests/test_digest_builder.py`:
- `test_four_senders_sharing_two_entities_form_one_cluster`
- `test_three_ideas_from_one_sender_do_not_cluster` (FR-049)
- `test_single_shared_entity_does_not_link`
- `test_entity_matching_is_case_and_punctuation_insensitive` (`"NVIDIA Corp."` vs `"nvidia corp"` via `normalize_key`)
- `test_transitive_links_merge_into_one_cluster` (A–B share 2, B–C share 2, A–C share 0 → one cluster of 3)
- `test_pass_through_entries_are_ignored`
- `test_entries_without_ideas_are_ignored`
- `test_clusters_ranked_by_sender_count_then_size_and_capped` (build 6 qualifying clusters; assert 5 returned in the right order)
- `test_empty_entries_return_empty_list`

### Step 3 — Synthesis call

Same module. Class mirrors `TrendAnalyzer`:

```python
class ThemeSynthesizer:
    def __init__(self, api_key: str, *, model: str) -> None: ...
        # anthropic.Anthropic(api_key=api_key), TokenBucketLimiter(rate=0.5, capacity=1), logger

    def synthesize(self, clusters, entries) -> tuple[Theme, ...]:
        """One Claude call per cluster. A cluster whose call fails or parses badly yields no
        theme (its ideas then render normally). Never raises."""
```
Keep the T069 name as a thin module-level convenience:
`def synthesize_themes(clusters, entries, api_key, *, model) -> tuple[Theme, ...]` that builds the
class and calls it — the runner uses the class directly.

Prompt (module constant `_SYSTEM_PROMPT`):
```
You are merging coverage of one story from several financial/tech newsletters into a single
reading for a busy investor. You will receive the story as a list of ideas, each labelled with
its source newsletter.

Write:
TITLE: one line, 10 words or fewer, the story itself (not "Several newsletters discuss...")
BODY: 2–4 sentences. Merge the facts. Name each source newsletter where its contribution is
used, e.g. "Bloomberg reports X while The AI Journal adds Y." Every source must be named at least
once. No bullet points, no markdown.
DISAGREEMENT: one or two sentences stating where the sources conflict or emphasize different
things, naming which source holds which view. If they genuinely agree, write exactly NONE.

Output those three labelled lines and nothing else.
```
User message: `Sources: {n}\n\n--- {display_name} ---\nTitle: {idea.title}\n{idea.summary_text}\n\n...`
where display name is `entry.display_name or entry.summary.sender`.

Call: `model=self._model, max_tokens=1500, output_config={"effort": "medium"}`; `extract_text(response)`.

Parsing (`_parse_theme(raw, sources, keys) -> Theme | None`): regex the three labels
(`re.S`, labels at line start); `TITLE` and `BODY` required and non-empty, else `None`;
`DISAGREEMENT` → `None` if missing or equals `NONE` (case-insensitive, stripped). Strip `**`.
`sources` = ordered unique display names of the cluster's entries.

Retry: 3 attempts, backoff `1 * 2**attempt + random.uniform(0, 1)`, rate limiter acquired each
attempt, catch `(anthropic.APIError, anthropic.RateLimitError)`; log `theme_synthesis_failed`
with the cluster's entity/source info and continue to the next cluster.

Tests (`TestThemeSynthesizer`; mock `anthropic.Anthropic`, patch
`agent.trends.synthesis.TokenBucketLimiter.acquire` and `time.sleep`):
- `test_well_formed_response_becomes_theme_with_all_sources`
- `test_disagreement_none_maps_to_python_none`
- `test_disagreement_text_is_kept`
- `test_missing_body_yields_no_theme`
- `test_api_error_on_one_cluster_does_not_block_others` (side_effect: `[APIError, APIError, APIError, good_response]` across two clusters → 1 theme, 4 create calls)
- `test_rate_limiter_acquired_before_every_attempt`
- `test_user_message_labels_each_idea_with_its_source`
- `test_thinking_block_before_text_is_handled`
- `test_uses_configured_model`

### Step 4 — Runner hook

`agent/runner.py::_run_digest`, after the advisor call and observation recording, before the
`DigestBatch(...)` construction:

```python
themes: tuple[Theme, ...] = ()
if (
    self.config.knowledge is not None
    and self.config.knowledge.enabled
    and self.config.knowledge.synthesis_enabled
    and entries
):
    clusters = cluster_ideas(entries)
    if clusters:
        themes = ThemeSynthesizer(
            api_key=self.config.anthropic_api_key, model=self.config.model
        ).synthesize(clusters, entries)
```
Pass `themes=themes` into `DigestBatch`. Synthesis runs in `--dry-run` too (it is read-only and the
user needs to preview it); it does not touch the store.

Dry-run print, inserted after the advisor block and before the entries loop:
```
--- Today's Themes ---
• {title}  [{', '.join(sources)}]
  {body[:300]}
  Disagreement: {disagreement}   (only if not None)
```

Test: in the runner test module created in plan 01, `test_synthesis_skipped_when_flag_off`
(patch `agent.runner.ThemeSynthesizer` → not called) and `test_synthesis_runs_when_flag_on`.

### Step 5 — Builder + template

`agent/digest/builder.py::build`: compute
```python
absorbed: dict[tuple[str, int], str] = {}   # idea key -> theme title
for theme in batch.themes:
    for key in theme.absorbed_idea_keys:
        absorbed.setdefault(key, theme.title)
```
and pass `absorbed=absorbed` to `template.render(...)`. (A dict is Jinja-friendly; tuple keys work
with `(entry.summary.email_id, loop.index0) in absorbed`.)

`templates/digest.html.j2`:
1. Insert a **Today's Themes** block immediately after the advisor cards `{% endif %}` (before the
   TOC comment at ~line 143), guarded by `{% if batch is defined and batch.themes %}`. Use the
   same card styling as the advisor cards. Per theme: title (16px/600), sources line
   (12px, `#a1a1a6`, `sources | join(' · ')`), body (`nl2br`), and if `theme.disagreement` a
   sub-line prefixed **Where they disagree:** in the amber used by the Medium badge in
   `signals.html.j2` (`#b8863a` on `#fdf5e8`).
2. Keep the template dumb: the **builder** computes
   `visible_ideas: dict[str, list[tuple[int, Idea]]]` (email_id → `(original_index, idea)` pairs
   not in `absorbed`, original order) and passes it to `render`. In the ideas loop (~line 217)
   iterate `{% for idx, idea in visible_ideas.get(entry.summary.email_id, []) %}` instead of
   `entry.summary.ideas`, so `loop.last` and the `<hr>` logic stay exactly as they are. Plan 03
   relies on `idx` being the original index.
3. When `entry.summary.ideas` is non-empty but its `visible_ideas` list is empty, render:
   `<p style="font-size:13px;color:#86868b;margin:0;">Covered in Today's Themes: {{ titles | join(', ') }}</p>`
   where titles are the distinct theme titles for that entry's absorbed keys (compute in the
   builder as `absorbed_titles_by_email: dict[str, list[str]]` to keep the template simple).
4. `visible_ideas` and `absorbed_titles_by_email` must default to empty dicts at the top of the
   template (`{% set visible_ideas = visible_ideas | default({}) %}`), and when `visible_ideas`
   has no entry for an email (direct `render` callers that skip the builder) fall back to
   `entry.summary.ideas` enumerated from 0 — write a tiny Jinja macro or handle it in the builder;
   the point is that a caller who passes nothing sees today's output.

Tests (`tests/test_digest_builder.py`, new class `TestDigestBuilderThemes`):
- `test_no_themes_html_is_byte_identical_to_pre_synthesis_render` — render a batch with
  `themes=()`; assert the HTML contains no `Today's Themes`, no `Covered in`, every idea title,
  and equals the HTML rendered from an otherwise identical `DigestBatch` constructed **without**
  the `themes` kwarg (proves the default path is untouched, FR-050).
- `test_theme_block_renders_title_sources_body`
- `test_disagreement_line_only_when_present`
- `test_absorbed_idea_hidden_unabsorbed_idea_rendered`
- `test_entry_with_all_ideas_absorbed_shows_covered_note_and_still_lists_subject`
- `test_hr_not_orphaned_when_last_idea_absorbed` (assert count of `<hr` equals visible-1)
- `test_toc_still_lists_entry_whose_ideas_are_all_absorbed`

### Step 6 — Docs

- README: short "Today's Themes" paragraph under the knowledge-graph/signals section; document
  `synthesis_enabled`.
- `specs/001-signals-knowledge-graph/tasks.md`: tick T066–T072.
- `CLAUDE.md` Recent Changes line.

## Out of scope

- Recording themes in the store (themes are derived; ideas are already recorded).
- Cross-batch clustering (batches are independent; `batch_size` is 10).
- Configurable thresholds — `_MIN_SHARED_ENTITIES`/`_MAX_THEMES` stay constants until real use
  shows they need tuning.
- Phase 6 tasks (T073–T080).

## Acceptance checklist

- [ ] `synthesis_enabled: false` (default) → digest HTML identical to before this branch (test proves it).
- [ ] Single-sender clusters never become themes (test proves it).
- [ ] A theme names every contributing source; disagreement rendered only when present.
- [ ] Absorbed ideas hidden; entries never hidden; TOC unchanged.
- [ ] A failing synthesis call degrades to "no theme, ideas render normally"; `synthesize` never raises.
- [ ] `pytest -q -m "not integration"` green; `ruff check agent/` clean; touched files clean.
- [ ] T066–T072 ticked in tasks.md.
- [ ] Manual smoke: `python -m agent --dry-run --once` with the flag on prints a `--- Today's Themes ---` block on a day with overlapping coverage (or nothing when there is no overlap — both are correct).
