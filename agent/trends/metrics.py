"""Deterministic trend metrics — pure Python, no API calls, no I/O beyond the store handle.

Every number here — delta, velocity, z_score, source_breadth, is_new/is_fading — is
computed in this module, never by a model. agent.trends.analyzer only interprets what
compute_brief() already decided (FR-010). Truncation happens here too, which is what
keeps prompt size O(config) rather than O(history) (FR-053, SC-005).
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from agent.knowledge.canonicalize import find_alias_candidates
from agent.utils.models import EntityTrend, TrendBrief

_MIN_DAILY_BUCKETS_FOR_ZSCORE = 8
_NEW_FADING_SALIENCE_BOOST = 5
_HISTORY_LOOKBACK_DAYS = 365


def _gate_passes(count: int, breadth: int, config) -> bool:
    """FR-014: an entity is eligible only with enough mentions AND enough distinct sources."""
    return count >= config.min_mentions and breadth >= config.min_sources


def _compute_z_score(daily_counts: list[int], current_avg: float) -> float | None:
    """None below 8 daily buckets (FR-016) — a z-score over 3 points is theatre."""
    if len(daily_counts) < _MIN_DAILY_BUCKETS_FOR_ZSCORE:
        return None
    mean = statistics.fmean(daily_counts)
    stdev = statistics.pstdev(daily_counts)
    if stdev == 0:
        return None
    return (current_avg - mean) / stdev


def _salience(delta: int, source_breadth: int, is_new: bool, is_fading: bool) -> float:
    boost = _NEW_FADING_SALIENCE_BOOST if (is_new or is_fading) else 0
    return abs(delta) + source_breadth + boost


def compute_brief(store, config, now: datetime) -> TrendBrief:
    """Build the TrendBrief the analysis model receives — the only thing it receives.

    *store* is an agent.knowledge.store.ObservationStore, *config* a SignalsConfig.
    """
    window_end = now
    window_start = now - timedelta(days=config.window_days)
    prior_start = window_start - timedelta(days=config.window_days)
    history_since = window_end - timedelta(days=_HISTORY_LOOKBACK_DAYS)

    current = {t.entity_id: t for t in store.compute_window(window_start, window_end)}
    prior = {t.entity_id: t for t in store.compute_window(prior_start, window_start)}
    all_ids = set(current) | set(prior)

    trends: list[EntityTrend] = []
    for entity_id in all_ids:
        cur = current.get(entity_id)
        pri = prior.get(entity_id)
        cur_count = cur.current_count if cur else 0
        cur_breadth = cur.source_breadth if cur else 0
        pri_count = pri.current_count if pri else 0
        pri_breadth = pri.source_breadth if pri else 0

        if cur is not None and _gate_passes(cur_count, cur_breadth, config):
            base = cur
        elif cur is None and pri is not None and _gate_passes(pri_count, pri_breadth, config):
            base = pri
        else:
            continue

        is_new = cur_count > 0 and pri_count == 0
        is_fading = cur_count == 0 and pri_count > 0
        delta = cur_count - pri_count
        velocity = delta / config.window_days if config.window_days else 0.0

        daily_counts = store.entity_daily_counts(entity_id, history_since)
        current_avg = cur_count / config.window_days if config.window_days else 0.0
        z_score = _compute_z_score(daily_counts, current_avg)

        trends.append(
            EntityTrend(
                entity_id=entity_id,
                name=base.name,
                entity_type=base.entity_type,
                current_count=cur_count,
                prior_count=pri_count,
                delta=delta,
                velocity=velocity,
                source_breadth=cur_breadth if cur else pri_breadth,
                z_score=z_score,
                net_sentiment=base.net_sentiment,
                is_new=is_new,
                is_fading=is_fading,
                sample_claims=base.sample_claims,
            )
        )

    trends.sort(
        key=lambda t: _salience(t.delta, t.source_breadth, t.is_new, t.is_fading),
        reverse=True,
    )
    truncated = tuple(trends[: config.max_entities_in_prompt])

    new_edges = tuple(store.new_edges(window_start, window_end))
    alias_candidates = tuple(find_alias_candidates([t.name for t in trends]))

    total_observations, distinct_senders, earliest_date = store.history_summary()
    if earliest_date is None:
        is_cold_start = True
    else:
        span_days = (window_end.date() - datetime.fromisoformat(earliest_date).date()).days
        is_cold_start = span_days < 2 * config.window_days

    return TrendBrief(
        window_days=config.window_days,
        window_start=window_start,
        window_end=window_end,
        trends=truncated,
        new_edges=new_edges,
        total_observations=total_observations,
        distinct_senders=distinct_senders,
        is_cold_start=is_cold_start,
        alias_candidates=alias_candidates,
    )
