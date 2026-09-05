"""Recurring-entity helpers — one store query's worth of memory for the daily digest.

Thresholds are module-level constants, promoted to config only if tuning proves
necessary. Nothing here touches the network or writes to the store: it shapes the
``recent_context`` result into an advisor prompt block and per-idea badge lines.
Badges prioritize; they never hide anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

from agent.knowledge.canonicalize import normalize_key
from agent.utils.models import DigestEntry, EntityContext, Idea

_WINDOW_DAYS = 7
_MIN_MENTIONS = 3
_MIN_SOURCES = 2


def context_window(run_date: datetime) -> tuple[datetime, datetime]:
    """[start of (run_date - 7 days), start of run_date) in UTC — today's batch is excluded."""
    until = run_date.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    since = until - timedelta(days=_WINDOW_DAYS)
    return since, until


def collect_norm_keys(entries: Sequence[DigestEntry]) -> list[str]:
    """Unique normalize_key() of every entity on every idea, in first-seen order."""
    keys: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not entry.summary.ideas:
            continue
        for idea in entry.summary.ideas:
            for mention in idea.entities:
                key = normalize_key(mention.name)
                if key and key not in seen:
                    seen.add(key)
                    keys.append(key)
    return keys


def is_recurring(ctx: EntityContext) -> bool:
    """True when an entity clears the mentions AND distinct-senders thresholds."""
    return ctx.mentions >= _MIN_MENTIONS and ctx.distinct_senders >= _MIN_SOURCES


def badge_for_idea(idea: Idea, context: Mapping[str, EntityContext]) -> str | None:
    """'Recurring · {name} · {n} mentions from {k} newsletters this week' for the strongest
    recurring entity on the idea, else None. Highest mentions wins; ties break alphabetically
    by canonical name.
    """
    best: EntityContext | None = None
    for mention in idea.entities:
        ctx = context.get(normalize_key(mention.name))
        if ctx is None or not is_recurring(ctx):
            continue
        # Higher mentions wins; equal mentions → alphabetically smaller name wins.
        if best is None or (ctx.mentions, best.name) > (best.mentions, ctx.name):
            best = ctx
    if best is None:
        return None
    mention_word = "mention" if best.mentions == 1 else "mentions"
    newsletter_word = "newsletter" if best.distinct_senders == 1 else "newsletters"
    return (
        f"Recurring · {best.name} · {best.mentions} {mention_word} "
        f"from {best.distinct_senders} {newsletter_word} this week"
    )


def recurring_lines(context: Mapping[str, EntityContext], limit: int = 10) -> list[str]:
    """Prompt lines for the advisor, strongest first:
    '- Nvidia: 5 mentions, 3 newsletters, 4 days, sentiment +0.6'."""
    qualifying = [ctx for ctx in context.values() if is_recurring(ctx)]
    qualifying.sort(key=lambda c: (-c.mentions, c.name))
    lines = []
    for ctx in qualifying[:limit]:
        mention_word = "mention" if ctx.mentions == 1 else "mentions"
        newsletter_word = "newsletter" if ctx.distinct_senders == 1 else "newsletters"
        day_word = "day" if ctx.days_active == 1 else "days"
        lines.append(
            f"- {ctx.name}: {ctx.mentions} {mention_word}, "
            f"{ctx.distinct_senders} {newsletter_word}, "
            f"{ctx.days_active} {day_word}, "
            f"sentiment {ctx.net_sentiment:+.1f}"
        )
    return lines
