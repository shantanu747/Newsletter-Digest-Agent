"""Unit tests for agent.knowledge.context (plan 03, step 3)."""

from datetime import datetime, timezone

from agent.knowledge.context import (
    badge_for_idea,
    collect_norm_keys,
    context_window,
    is_recurring,
    recurring_lines,
)
from agent.utils.models import DigestEntry, EntityMention, Idea, Summary
from agent.utils.models import EntityContext


def _ctx(name="Nvidia", mentions=5, senders=3, days=4, sentiment=0.6) -> EntityContext:
    return EntityContext(
        name=name,
        mentions=mentions,
        distinct_senders=senders,
        days_active=days,
        net_sentiment=sentiment,
    )


def _idea(*names: str) -> Idea:
    return Idea(
        title="Idea",
        summary_text="Body.",
        entities=tuple(EntityMention(name=n, entity_type="company", sentiment="neutral") for n in names),
    )


def _entry(email_id: str, *ideas: Idea) -> DigestEntry:
    return DigestEntry(
        summary=Summary(
            email_id=email_id,
            sender="a@example.com",
            subject="Subject",
            summary_text="",
            word_count=0,
            generated_at=datetime(2026, 9, 5, 7, 0, tzinfo=timezone.utc),
            ideas=ideas,
        )
    )


class TestContextWindow:
    def test_window_is_seven_days_ending_at_start_of_run_date(self):
        run_date = datetime(2026, 9, 5, 15, 30, tzinfo=timezone.utc)
        since, until = context_window(run_date)
        assert since == datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
        assert until == datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)

    def test_midnight_run_date_is_excluded(self):
        run_date = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)
        since, until = context_window(run_date)
        assert (until - since).days == 7
        assert until == run_date


class TestCollectNormKeys:
    def test_unique_keys_in_first_seen_order(self):
        entries = [
            _entry("m1", _idea("Nvidia", "Oil"), _idea("NVIDIA Corp.")),
            _entry("m2", _idea("Oil", "Fed")),
        ]
        assert collect_norm_keys(entries) == ["nvidia", "oil", "fed"]

    def test_entries_without_ideas_are_skipped(self):
        entry = DigestEntry(
            summary=Summary(
                email_id="m1",
                sender="a@example.com",
                subject="S",
                summary_text="text",
                word_count=1,
                generated_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            )
        )
        assert collect_norm_keys([entry]) == []


class TestIsRecurring:
    def test_threshold_is_three_mentions_and_two_sources(self):
        assert is_recurring(_ctx(mentions=3, senders=2)) is True
        assert is_recurring(_ctx(mentions=2, senders=3)) is False
        assert is_recurring(_ctx(mentions=5, senders=1)) is False


class TestBadgeForIdea:
    def test_picks_highest_mentions(self):
        idea = _idea("Nvidia", "Oil")
        context = {"nvidia": _ctx("Nvidia", mentions=5, senders=3), "oil": _ctx("Oil", mentions=8, senders=2)}
        assert badge_for_idea(idea, context) == "Recurring · Oil · 8 mentions from 2 newsletters this week"

    def test_ties_break_alphabetically(self):
        idea = _idea("Nvidia", "Oil")
        context = {"nvidia": _ctx("Nvidia", mentions=5, senders=3), "oil": _ctx("Oil", mentions=5, senders=2)}
        assert badge_for_idea(idea, context) == "Recurring · Nvidia · 5 mentions from 3 newsletters this week"

    def test_returns_none_when_no_entity_qualifies(self):
        idea = _idea("Nvidia")
        assert badge_for_idea(idea, {"nvidia": _ctx(mentions=2, senders=1)}) is None
        assert badge_for_idea(idea, {}) is None

    def test_singular_plural_forms(self):
        idea = _idea("Nvidia")
        context = {"nvidia": _ctx(mentions=3, senders=2)}
        badge = badge_for_idea(idea, context)
        assert "3 mentions" in badge
        assert "2 newsletters" in badge


class TestRecurringLines:
    def test_strongest_first_and_limit_respected(self):
        context = {
            "oil": _ctx("Oil", mentions=8, senders=2, days=2, sentiment=-0.2),
            "nvidia": _ctx("Nvidia", mentions=5, senders=3, days=4, sentiment=0.6),
            "fed": _ctx("Fed", mentions=1, senders=1, days=1, sentiment=0.0),
        }
        lines = recurring_lines(context, limit=1)
        assert lines == ["- Oil: 8 mentions, 2 newsletters, 2 days, sentiment -0.2"]

        lines = recurring_lines(context)
        assert lines == [
            "- Oil: 8 mentions, 2 newsletters, 2 days, sentiment -0.2",
            "- Nvidia: 5 mentions, 3 newsletters, 4 days, sentiment +0.6",
        ]

    def test_sentiment_formats_with_sign(self):
        lines = recurring_lines({"n": _ctx("Nvidia", sentiment=0.0)})
        assert lines == ["- Nvidia: 5 mentions, 3 newsletters, 4 days, sentiment +0.0"]
