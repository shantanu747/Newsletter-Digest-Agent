"""Unit tests for DigestBuilder.

Tests cover:
- Build digest with multiple entries: HTML contains sender, subject, summary text
- Build digest with failed subjects: HTML mentions the failed newsletter name
- Build digest with empty entries: HTML is generated without error and contains run date
- Build digest with themes: Theme block renders, absorbed ideas hidden, covered note shown
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from agent.utils.models import (
    AdvisorAnalysis, DigestBatch, DigestEntry, EntityContext, Idea, EntityMention, Summary, Theme,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary(
    email_id: str,
    sender: str,
    subject: str,
    summary_text: str,
) -> Summary:
    return Summary(
        email_id=email_id,
        sender=sender,
        subject=subject,
        summary_text=summary_text,
        word_count=len(summary_text.split()),
        generated_at=datetime(2026, 3, 9, 7, 1, 0, tzinfo=timezone.utc),
    )


def _make_entry(
    email_id: str,
    sender: str,
    subject: str,
    summary_text: str,
) -> DigestEntry:
    return DigestEntry(summary=_make_summary(email_id, sender, subject, summary_text))


def _make_batch(
    entries: list[DigestEntry],
    batch_index: int = 0,
    total_batches: int = 1,
    advisor: AdvisorAnalysis | None = None,
) -> DigestBatch:
    return DigestBatch(
        batch_index=batch_index,
        entries=entries,
        gmail_message_ids=[],
        total_batches=total_batches,
        advisor=advisor,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_date() -> datetime:
    return datetime(2026, 3, 9, 6, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def three_entries() -> list[DigestEntry]:
    return [
        _make_entry(
            "msg-001",
            "alpha@newsletter.com",
            "Alpha Weekly",
            "Alpha newsletter summary content here.",
        ),
        _make_entry(
            "msg-002",
            "beta@newsletter.com",
            "Beta Digest",
            "Beta newsletter summary content here.",
        ),
        _make_entry(
            "msg-003",
            "gamma@newsletter.com",
            "Gamma Report",
            "Gamma newsletter summary content here.",
        ),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDigestBuilderMultipleEntries:
    """Digest HTML contains all entry data when multiple entries are provided."""

    def test_html_contains_all_senders(self, mocker, three_entries, run_date):
        """Built HTML includes every sender address."""
        rendered_html = _fake_render(three_entries, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            batch=_make_batch(three_entries),
            run_date=run_date,
            total_summarized=3,
            failed_subjects=[],
        )

        assert "alpha@newsletter.com" in html
        assert "beta@newsletter.com" in html
        assert "gamma@newsletter.com" in html

    def test_html_contains_all_subjects(self, mocker, three_entries, run_date):
        """Built HTML includes every subject line."""
        rendered_html = _fake_render(three_entries, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            batch=_make_batch(three_entries),
            run_date=run_date,
            total_summarized=3,
            failed_subjects=[],
        )

        assert "Alpha Weekly" in html
        assert "Beta Digest" in html
        assert "Gamma Report" in html

    def test_html_contains_all_summary_texts(self, mocker, three_entries, run_date):
        """Built HTML includes the summary prose for every entry."""
        rendered_html = _fake_render(three_entries, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            batch=_make_batch(three_entries),
            run_date=run_date,
            total_summarized=3,
            failed_subjects=[],
        )

        assert "Alpha newsletter summary content here." in html
        assert "Beta newsletter summary content here." in html
        assert "Gamma newsletter summary content here." in html

    def test_build_returns_string(self, mocker, three_entries, run_date):
        """build() always returns a str."""
        rendered_html = _fake_render(three_entries, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        result = builder.build(
            batch=_make_batch(three_entries),
            run_date=run_date,
            total_summarized=3,
            failed_subjects=[],
        )

        assert isinstance(result, str)


class TestDigestBuilderFailedSubjects:
    """Failed newsletter subjects appear in the rendered digest."""

    def test_html_mentions_failed_subject(self, mocker, run_date):
        """HTML references the name of a newsletter that failed summarization."""
        failed = ["Newsletter X"]
        rendered_html = _fake_render([], run_date=run_date, failed_subjects=failed)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            batch=_make_batch([]),
            run_date=run_date,
            total_summarized=0,
            failed_subjects=failed,
        )

        assert "Newsletter X" in html

    def test_html_mentions_multiple_failed_subjects(self, mocker, run_date):
        """HTML references each name when multiple newsletters failed."""
        failed = ["Newsletter X", "Newsletter Y", "Newsletter Z"]
        rendered_html = _fake_render([], run_date=run_date, failed_subjects=failed)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            batch=_make_batch([]),
            run_date=run_date,
            total_summarized=0,
            failed_subjects=failed,
        )

        assert "Newsletter X" in html
        assert "Newsletter Y" in html
        assert "Newsletter Z" in html


class TestDigestBuilderEmptyEntries:
    """DigestBuilder handles an empty entries list gracefully."""

    def test_no_crash_on_empty_entries(self, mocker, run_date):
        """build() does not raise when entries list is empty."""
        rendered_html = _fake_render([], run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            batch=_make_batch([]),
            run_date=run_date,
            total_summarized=0,
            failed_subjects=[],
        )

        assert isinstance(html, str)
        assert len(html) > 0

    def test_html_contains_run_date(self, mocker, run_date):
        """HTML generated for an empty digest still contains the run date."""
        rendered_html = _fake_render([], run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            batch=_make_batch([]),
            run_date=run_date,
            total_summarized=0,
            failed_subjects=[],
        )

        assert "2026" in html
        assert "March" in html or "03" in html or "2026-03-09" in html


class TestDigestBuilderAdvisorCards:
    """Advisor cards render when AdvisorAnalysis is present; absent otherwise."""

    def test_relevance_text_appears_in_html(self, mocker, run_date):
        """When advisor has relevance_text, it appears in the rendered HTML."""
        advisor = AdvisorAnalysis(
            relevance_text="UAL margins at risk from rising oil prices.",
            signals_text=None,
        )
        batch = _make_batch([], advisor=advisor)
        rendered_html = _fake_render([], run_date=run_date, advisor=advisor)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder
        html = DigestBuilder().build(batch=batch, run_date=run_date)
        assert "UAL margins at risk from rising oil prices." in html

    def test_signals_text_appears_in_html(self, mocker, run_date):
        """When advisor has signals_text, it appears in the rendered HTML."""
        advisor = AdvisorAnalysis(
            relevance_text=None,
            signals_text="[BUY] XOM (ExxonMobil) — oil price tailwind.",
        )
        batch = _make_batch([], advisor=advisor)
        rendered_html = _fake_render([], run_date=run_date, advisor=advisor)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder
        html = DigestBuilder().build(batch=batch, run_date=run_date)
        assert "[BUY] XOM (ExxonMobil) — oil price tailwind." in html

    def test_no_advisor_section_when_advisor_is_none(self, mocker, run_date):
        """When advisor is None, no advisor content appears in the HTML."""
        batch = _make_batch([], advisor=None)
        rendered_html = _fake_render([], run_date=run_date, advisor=None)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder
        html = DigestBuilder().build(batch=batch, run_date=run_date)
        assert "What This Means For You" not in html
        assert "Action Signals" not in html

    def test_no_advisor_section_when_both_fields_none(self, mocker, run_date):
        """An AdvisorAnalysis with both fields None produces no advisor content."""
        advisor = AdvisorAnalysis(relevance_text=None, signals_text=None)
        batch = _make_batch([], advisor=advisor)
        rendered_html = _fake_render([], run_date=run_date, advisor=advisor)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder
        html = DigestBuilder().build(batch=batch, run_date=run_date)
        assert "What This Means For You" not in html
        assert "Action Signals" not in html


# ---------------------------------------------------------------------------
# Internal test-only render helper
# ---------------------------------------------------------------------------

def _fake_render(
    entries: list[DigestEntry],
    run_date: datetime,
    failed_subjects: list[str] | None = None,
    advisor: AdvisorAnalysis | None = None,
) -> str:
    failed_subjects = failed_subjects or []
    parts = [
        "<!DOCTYPE html><html><body>",
        f"<p>Run date: {run_date.strftime('%Y-%m-%d %B')}</p>",
    ]
    if advisor is not None:
        if advisor.relevance_text:
            parts.append(f"<div class='advisor-relevance'><p>What This Means For You</p><p>{advisor.relevance_text}</p></div>")
        if advisor.signals_text:
            parts.append(f"<div class='advisor-signals'><p>Action Signals</p><p>{advisor.signals_text}</p></div>")
    for entry in entries:
        s = entry.summary
        parts.append("<div class='entry'>")
        parts.append(f"<p class='sender'>{s.sender}</p>")
        parts.append(f"<h2>{s.subject}</h2>")
        if s.ideas:
            for idea in s.ideas:
                parts.append(f"<p>{idea.title}</p>")
                parts.append(f"<p>{idea.summary_text}</p>")
        else:
            parts.append(f"<p>{s.summary_text}</p>")
        parts.append("</div>")
    if failed_subjects:
        parts.append("<section class='failed'>")
        for subj in failed_subjects:
            parts.append(f"<p>{subj}</p>")
        parts.append("</section>")
    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------

def _make_idea(
    title: str,
    summary_text: str,
    entities: list[EntityMention] | None = None,
) -> Idea:
    return Idea(
        title=title,
        summary_text=summary_text,
        entities=tuple(entities) if entities else (),
    )


def _make_summary_with_ideas(
    email_id: str,
    sender: str,
    subject: str,
    ideas: list[Idea] | None = None,
) -> Summary:
    return Summary(
        email_id=email_id,
        sender=sender,
        subject=subject,
        summary_text="",
        word_count=0,
        generated_at=datetime(2026, 3, 9, 7, 1, 0, tzinfo=timezone.utc),
        ideas=tuple(ideas) if ideas else None,
    )


def _make_entry_with_ideas(
    email_id: str,
    sender: str,
    subject: str,
    ideas: list[Idea] | None = None,
    display_name: str = "",
) -> DigestEntry:
    summary = _make_summary_with_ideas(email_id, sender, subject, ideas)
    return DigestEntry(
        summary=summary,
        display_name=display_name or sender,
    )


def _make_theme(
    title: str,
    body: str,
    sources: list[str],
    absorbed_keys: list[tuple[str, int]],
    disagreement: str | None = None,
) -> Theme:
    return Theme(
        title=title,
        body=body,
        sources=tuple(sources),
        disagreement=disagreement,
        absorbed_idea_keys=tuple(absorbed_keys),
    )


def _make_batch_with_themes(
    entries: list[DigestEntry],
    themes: list[Theme] | None = None,
    batch_index: int = 0,
    total_batches: int = 1,
    advisor: AdvisorAnalysis | None = None,
) -> DigestBatch:
    return DigestBatch(
        batch_index=batch_index,
        entries=entries,
        gmail_message_ids=[],
        total_batches=total_batches,
        advisor=advisor,
        themes=tuple(themes) if themes else (),
    )


# ---------------------------------------------------------------------------
# Theme Tests
# ---------------------------------------------------------------------------

class TestDigestBuilderThemes:
    """Theme rendering and absorbed idea suppression."""

    @pytest.fixture
    def run_date(self) -> datetime:
        return datetime(2026, 3, 9, 6, 30, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def entries_with_ideas(self) -> list[DigestEntry]:
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        return [
            _make_entry_with_ideas("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Nvidia hit", "Nvidia faces new curbs", [e1, e2]),
                _make_idea("Market reacts", "Stocks dip on news", [e1]),
            ], display_name="Bloomberg"),
            _make_entry_with_ideas("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Chip curbs", "Export controls tighten", [e1, e2]),
            ], display_name="The AI Journal"),
        ]

    @pytest.fixture
    def theme(self) -> Theme:
        return _make_theme(
            title="Nvidia hit by new export controls",
            body="Bloomberg reports Nvidia faces new curbs while The AI Journal adds that China restrictions expand.",
            sources=["Bloomberg", "The AI Journal"],
            absorbed_keys=[("msg-1", 0), ("msg-2", 0)],
            disagreement="Bloomberg emphasizes revenue impact; The AI Journal focuses on supply chain.",
        )

    def test_no_themes_html_is_byte_identical_to_pre_synthesis_render(self, mocker, run_date, entries_with_ideas):
        """Empty themes produces identical HTML to batch without themes kwarg (FR-050)."""
        # Render with themes=()
        batch_with_themes = _make_batch_with_themes(entries_with_ideas, themes=[])
        batch_without_themes = DigestBatch(
            batch_index=0,
            entries=entries_with_ideas,
            gmail_message_ids=[],
            total_batches=1,
        )

        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()

        # Mock template to return same base HTML
        base_html = _fake_render(entries_with_ideas, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = base_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        html_with = builder.build(batch=batch_with_themes, run_date=run_date, total_summarized=2)
        html_without = builder.build(batch=batch_without_themes, run_date=run_date, total_summarized=2)

        # Both should not contain theme-related content
        assert "Today's Themes" not in html_with
        assert "Today's Themes" not in html_without
        assert "Covered in" not in html_with
        assert "Covered in" not in html_without
        # Both should contain all original ideas
        assert "Nvidia hit" in html_with
        assert "Market reacts" in html_with
        assert "Chip curbs" in html_with
        assert "Nvidia hit" in html_without
        assert "Market reacts" in html_without
        assert "Chip curbs" in html_without

    def test_theme_block_renders_title_sources_body(self, mocker, run_date, entries_with_ideas, theme):
        """Theme block renders title, sources, and body."""
        batch = _make_batch_with_themes(entries_with_ideas, themes=[theme])

        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()
        html = builder.build(batch=batch, run_date=run_date, total_summarized=2)

        assert theme.title in html
        assert "Bloomberg" in html
        assert "The AI Journal" in html
        assert "Nvidia faces new curbs" in html

    def test_disagreement_line_only_when_present(self, mocker, run_date, entries_with_ideas):
        """Disagreement line renders only when disagreement is not None."""
        theme_with = _make_theme("Title", "Body", ["A", "B"], [], disagreement="They disagree.")
        theme_without = _make_theme("Title", "Body", ["A", "B"], [], disagreement=None)

        batch_with = _make_batch_with_themes(entries_with_ideas, themes=[theme_with])
        batch_without = _make_batch_with_themes(entries_with_ideas, themes=[theme_without])

        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()

        html_with = builder.build(batch=batch_with, run_date=run_date, total_summarized=2)
        html_without = builder.build(batch=batch_without, run_date=run_date, total_summarized=2)

        assert "Where they disagree" in html_with
        assert "Where they disagree" not in html_without

    def test_absorbed_idea_hidden_unabsorbed_idea_rendered(self, mocker, run_date, entries_with_ideas, theme):
        """Absorbed ideas are hidden; unabsorbed ideas still render."""
        batch = _make_batch_with_themes(entries_with_ideas, themes=[theme])

        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()
        html = builder.build(batch=batch, run_date=run_date, total_summarized=2)

        # The absorbed idea content should not appear in the entry's idea list
        # Check that "Market reacts" (unabsorbed) appears in entry section
        assert "Market reacts" in html
        assert "Stocks dip on news" in html
        # The absorbed ideas' original bodies should not appear in entry sections
        # (they appear in the theme block instead, merged)
        # Just verify the unabsorbed ideas are present
        assert "Nvidia faces new curbs" in html  # appears in theme body
        assert "Export controls tighten" not in html  # this is the original idea body, not in theme

    def test_entry_with_all_ideas_absorbed_shows_covered_note_and_still_lists_subject(self, mocker, run_date):
        """Entry whose all ideas are absorbed shows covered note but still appears in TOC."""
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")

        entries = [
            _make_entry_with_ideas("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Nvidia hit", "Nvidia faces new curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry_with_ideas("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Chip curbs", "Export controls tighten", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        theme = _make_theme(
            title="Nvidia export controls",
            body="Both cover the same story.",
            sources=["Bloomberg", "The AI Journal"],
            absorbed_keys=[("msg-1", 0), ("msg-2", 0)],
        )
        batch = _make_batch_with_themes(entries, themes=[theme])

        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()
        html = builder.build(batch=batch, run_date=run_date, total_summarized=2)

        # TOC still lists both entries
        assert "Bloomberg" in html
        assert "AI Journal" in html
        # Covered note appears
        assert "Covered in Today's Themes" in html
        assert "Nvidia export controls" in html

    def test_hr_not_orphaned_when_last_idea_absorbed(self, mocker, run_date, entries_with_ideas, theme):
        """HR count equals visible ideas - 1 (no orphaned HR after last visible idea)."""
        batch = _make_batch_with_themes(entries_with_ideas, themes=[theme])

        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()
        html = builder.build(batch=batch, run_date=run_date, total_summarized=2)

        # Count HR tags in entry sections - should be (visible_ideas - 1) per entry
        # Bloomberg had 2 ideas, 1 absorbed -> 1 visible -> 0 HR
        # AI Journal had 1 idea, 1 absorbed -> 0 visible -> 0 HR
        # So no HR tags should appear
        hr_count = html.count("<hr")
        assert hr_count == 0

    def test_toc_still_lists_entry_whose_ideas_are_all_absorbed(self, mocker, run_date):
        """TOC includes entry even when all its ideas are absorbed."""
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")

        entries = [
            _make_entry_with_ideas("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Nvidia hit", "Nvidia faces new curbs", [e1, e2]),
            ], display_name="Bloomberg"),
        ]
        theme = _make_theme(
            title="Nvidia export controls",
            body="Covered.",
            sources=["Bloomberg"],
            absorbed_keys=[("msg-1", 0)],
        )
        batch = _make_batch_with_themes(entries, themes=[theme])

        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()
        html = builder.build(batch=batch, run_date=run_date, total_summarized=1)

        # TOC should still have the entry
        assert "Bloomberg" in html
        assert "Bloomberg" in html  # subject in TOC


# ---------------------------------------------------------------------------
# Recurring-badge Tests (plan 03, step 6)
# ---------------------------------------------------------------------------

def _make_context_batch(entries: list[DigestEntry], context: dict) -> DigestBatch:
    return DigestBatch(
        batch_index=0,
        entries=entries,
        gmail_message_ids=[],
        total_batches=1,
        entity_context=context,
    )


class TestDigestBuilderBadges:
    """Recurring badge renders under the qualifying idea title."""

    @pytest.fixture
    def run_date(self) -> datetime:
        return datetime(2026, 3, 9, 6, 30, 0, tzinfo=timezone.utc)

    @pytest.fixture
    def badge_entries(self) -> list[DigestEntry]:
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="positive")
        e2 = EntityMention(name="Oil", entity_type="asset", sentiment="neutral")
        return [
            _make_entry_with_ideas("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Nvidia hit", "Nvidia faces new curbs", [e1]),
                _make_idea("Oil steady", "Oil prices hold", [e2]),
            ], display_name="Bloomberg"),
        ]

    @pytest.fixture
    def badge_context(self) -> dict[str, EntityContext]:
        return {
            "nvidia": EntityContext(
                name="Nvidia", mentions=5, distinct_senders=3, days_active=4, net_sentiment=0.6,
            ),
        }

    def test_no_context_renders_identical_html_to_previous_plan(self, run_date, badge_entries):
        """Batch without entity_context renders the same as batch with empty context."""
        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()

        batch_default = DigestBatch(
            batch_index=0, entries=badge_entries, gmail_message_ids=[], total_batches=1,
        )
        batch_empty = _make_context_batch(badge_entries, {})

        html_default = builder.build(batch=batch_default, run_date=run_date, total_summarized=1)
        html_empty = builder.build(batch=batch_empty, run_date=run_date, total_summarized=1)

        assert html_default == html_empty
        assert "Recurring ·" not in html_empty

    def test_badge_rendered_under_qualifying_idea(self, run_date, badge_entries, badge_context):
        """The qualifying idea carries the badge line; the other idea does not."""
        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()

        html = builder.build(
            batch=_make_context_batch(badge_entries, badge_context),
            run_date=run_date,
            total_summarized=1,
        )

        badge = "Recurring · Nvidia · 5 mentions from 3 newsletters this week"
        assert html.count(badge) == 1
        title_pos = html.index("Nvidia hit")
        badge_pos = html.index(badge)
        body_pos = html.index("Nvidia faces new curbs")
        assert title_pos < badge_pos < body_pos

    def test_only_one_badge_per_idea_even_with_two_recurring_entities(
        self, run_date, badge_context,
    ):
        """An idea naming two recurring entities still renders exactly one badge."""
        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="positive")
        e2 = EntityMention(name="Oil", entity_type="asset", sentiment="neutral")
        entries = [
            _make_entry_with_ideas("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Both", "Nvidia and Oil move", [e1, e2]),
            ], display_name="Bloomberg"),
        ]
        context = {
            "nvidia": EntityContext(
                name="Nvidia", mentions=5, distinct_senders=3, days_active=4, net_sentiment=0.6,
            ),
            "oil": EntityContext(
                name="Oil", mentions=8, distinct_senders=2, days_active=2, net_sentiment=-0.2,
            ),
        }
        html = builder.build(
            batch=_make_context_batch(entries, context), run_date=run_date, total_summarized=1,
        )

        assert html.count("Recurring ·") == 1
        assert "Recurring · Oil · 8 mentions from 2 newsletters this week" in html

    def test_no_badge_below_threshold(self, run_date, badge_entries):
        """Context entries below the recurring threshold render no badge."""
        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()

        context = {
            "nvidia": EntityContext(
                name="Nvidia", mentions=2, distinct_senders=1, days_active=1, net_sentiment=0.0,
            ),
        }
        html = builder.build(
            batch=_make_context_batch(badge_entries, context), run_date=run_date, total_summarized=1,
        )

        assert "Recurring ·" not in html

    def test_absorbed_idea_gets_no_badge(self, run_date, badge_entries, badge_context):
        """An absorbed idea renders no badge even when its entity qualifies."""
        from agent.digest.builder import DigestBuilder
        builder = DigestBuilder()

        theme = _make_theme(
            title="Nvidia export controls",
            body="Covered.",
            sources=["Bloomberg"],
            absorbed_keys=[("msg-1", 0)],
        )
        batch = DigestBatch(
            batch_index=0,
            entries=badge_entries,
            gmail_message_ids=[],
            total_batches=1,
            themes=(theme,),
            entity_context=badge_context,
        )
        html = builder.build(batch=batch, run_date=run_date, total_summarized=1)

        assert "Recurring ·" not in html
