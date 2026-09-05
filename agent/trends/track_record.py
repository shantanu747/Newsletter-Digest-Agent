"""Track-record computation — score past Signals Report calls at fixed horizons.

For every (call, horizon) pair due per ``ObservationStore.calls_due_for_review``,
computes the price move of the related profile ticker (when there is one) and
how newsletter coverage of the call's entities evolved since the call was made.

All numbers are computed in code; the model only writes commentary later
(agent.trends.analyzer). Never raises — a failing ticker just yields
``price_change_pct=None``; mention stats always compute. Does not write reviews
to the store; the runner records them after a successful send.

Deliberately does not: fetch prices itself on a schedule (the runner drives one
pass per signals run), score divergences (not calls), or show old reviews
(only reviews produced in the current run render).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone

from agent.knowledge.canonicalize import normalize_key
from agent.utils.config import UserProfile
from agent.utils.logger import get_logger
from agent.utils.models import CallReview

log = get_logger(__name__)

_REVIEW_HORIZONS_DAYS = (7, 30)
_MAX_CALL_AGE_DAYS = 90
_PRICE_SLACK_DAYS = 5


def resolve_ticker(entity_names: Sequence[str], profile: UserProfile | None) -> str | None:
    """Resolve a call's entities to a profile ticker.

    First profile holding (portfolio then watchlist) whose name or ticker
    normalizes equal to any entity name wins. None when the profile is None
    or nothing matches.
    """
    if profile is None:
        return None
    normalized = {normalize_key(name) for name in entity_names if normalize_key(name)}
    if not normalized:
        return None
    for holding in list(profile.portfolio) + list(profile.watchlist):
        ticker = holding.get("ticker")
        name = holding.get("name")
        candidates = set()
        if ticker:
            candidates.add(normalize_key(str(ticker)))
        if name:
            candidates.add(normalize_key(str(name)))
        if candidates & normalized:
            return str(ticker) if ticker else (str(name) if name else None)
    return None


def price_change(
    closes: Sequence[tuple[str, float]], made_on: date, horizon_days: int
) -> float | None:
    """Percent change between boundary closes, rounded to 1 dp.

    Base is the last close on/before made_on; target is the first close
    on/after made_on + horizon_days. Either side may fall back within
    _PRICE_SLACK_DAYS (trading-day tolerance around weekends/holidays).
    None when either side is missing within slack.
    """
    if not closes:
        return None
    target_day = made_on + timedelta(days=horizon_days)
    base = None
    for day_s, close in closes:
        day = date.fromisoformat(day_s)
        if day <= made_on and (made_on - day).days <= _PRICE_SLACK_DAYS:
            base = close
    target = None
    for day_s, close in closes:
        day = date.fromisoformat(day_s)
        if day >= target_day and (day - target_day).days <= _PRICE_SLACK_DAYS:
            target = close
            break
    if base is None or target is None or base == 0:
        return None
    return round(target / base * 100 - 100, 1)


def build_track_record(store, profile: UserProfile | None, fetcher, now: datetime) -> tuple[CallReview, ...]:
    """Compute every due review as of *now*. Never raises.

    Fetches each distinct ticker once, upserts into price_daily, reads the
    window back via closes_between. Mention stats come from
    ``store.recent_context(keys, since=made_on 00:00, until=now date 00:00)``
    summed across the call's entities (sentiment is mention-weighted).
    """
    try:
        due = store.calls_due_for_review(now, _REVIEW_HORIZONS_DAYS, _MAX_CALL_AGE_DAYS)
    except Exception:
        log.error("track_record_due_query_failed", exc_info=True)
        return ()
    tickers = sorted({call.ticker for call, _ in due if call.ticker})
    for ticker in tickers:
        try:
            start = min(date.fromisoformat(call.report_date) for call, _ in due if call.ticker == ticker)
            rows = fetcher.daily_closes(ticker, start, now.date())
            if rows:
                store.upsert_prices(ticker, rows)
        except Exception:
            log.warning("track_record_price_fetch_failed", ticker=ticker, exc_info=True)
    reviews: list[CallReview] = []
    until = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for call, horizon in due:
        made_on = date.fromisoformat(call.report_date)
        since = datetime(made_on.year, made_on.month, made_on.day, tzinfo=timezone.utc)
        change = None
        if call.ticker:
            try:
                closes = store.closes_between(
                    call.ticker, made_on - timedelta(days=_PRICE_SLACK_DAYS),
                    made_on + timedelta(days=horizon + _PRICE_SLACK_DAYS),
                )
                change = price_change(closes, made_on, horizon)
            except Exception:
                log.warning("track_record_price_lookup_failed", ticker=call.ticker, exc_info=True)
                change = None
        mentions = 0
        sources = 0
        sentiment_num = 0.0
        try:
            keys = [normalize_key(n) for n in call.entity_names if normalize_key(n)]
            contexts = store.recent_context(keys, since, until) if keys else {}
            for key in keys:
                ctx = contexts.get(key)
                if ctx is None:
                    continue
                mentions += ctx.mentions
                sources += ctx.distinct_senders
                sentiment_num += ctx.net_sentiment * ctx.mentions
        except Exception:
            log.warning("track_record_mentions_failed", call_id=call.id, exc_info=True)
            mentions, sources, sentiment_num = 0, 0, 0.0
        reviews.append(
            CallReview(
                call_id=call.id,
                made_on=made_on,
                horizon_days=horizon,
                section=call.section,
                headline=call.headline,
                confidence=call.confidence,
                entities=call.entity_names,
                ticker=call.ticker,
                price_change_pct=change,
                mentions_since=mentions,
                sources_since=sources,
                sentiment_since=(sentiment_num / mentions) if mentions else 0.0,
            )
        )
    return tuple(reviews)
