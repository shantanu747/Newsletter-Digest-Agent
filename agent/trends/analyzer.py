"""TrendAnalyzer — interprets a deterministically computed TrendBrief.

Mirrors agent/advisor/analyzer.py's retry/backoff shape deliberately. The one
structural difference: this analyzer rate-limits its own calls (AdvisorAnalyzer does
not), because a single logical analysis can become several API calls once server-side
tool continuations are in play (Constitution IV).

The model never sees a raw observation and is never asked to produce a count — every
number in the brief was computed by agent.trends.metrics. This module only asks for
interpretation: which movements are real, the causal mechanism, and what opportunity
or risk follows (FR-010).
"""

from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone

import anthropic

from agent.utils.anthropic_text import extract_text
from agent.utils.config import SignalsConfig, UserProfile
from agent.utils.logger import get_logger
from agent.utils.models import CallReview, MacroSnapshot, SignalItem, SignalsReport, TrendBrief
from agent.utils.rate_limiter import TokenBucketLimiter
from collections.abc import Sequence

_SECTION_DELIMITERS = (
    ("risks", "---RISKS---"),
    ("opportunities", "---OPPORTUNITIES---"),
    ("emerging", "---EMERGING---"),
    ("fading", "---FADING---"),
    ("watch", "---WATCH---"),
    ("divergences", "---DIVERGENCE---"),
    ("track_record", "---TRACK RECORD---"),
)

_ITEM_RE = re.compile(
    r"HEADLINE:\s*(?P<headline>.+?)\s*\n"
    r"CONFIDENCE:\s*(?P<confidence>HIGH|MEDIUM|LOW)\s*\n"
    r"ENTITIES:\s*(?P<entities>.*?)\s*\n"
    r"BODY:\s*(?P<body>.+?)(?=\n\s*HEADLINE:|\Z)",
    re.DOTALL,
)

_REVIEW_RE = re.compile(
    r"CALL_ID:\s*(?P<id>\d+)\s*\nBODY:\s*(?P<body>.+?)(?=\nCALL_ID:|\Z)",
    re.DOTALL,
)

_SYSTEM_PROMPT = (
    "You are a markets and current-events analyst. You are handed a pre-computed brief "
    "of entity mention trends — every count, delta, velocity, and z-score in it was "
    "computed deterministically, not by you. Do not recompute or restate those numbers. "
    "Your only job is interpretation: which movements are real signal versus noise, the "
    "likely causal mechanism behind each, and what opportunity or risk follows.\n\n"
    "Every entity name you use MUST be copied verbatim from the ENTITIES list in the "
    "brief below. Do not name any entity, company, or person that does not appear there "
    "— an invented entity is treated as a fabrication and the item will be discarded.\n\n"
    "Produce items across up to six sections, using exactly these delimiters, omitting "
    "a section entirely when it has nothing genuinely warranted:\n\n"
    "---RISKS---\n"
    "---OPPORTUNITIES---\n"
    "---EMERGING---\n"
    "---FADING---\n"
    "---WATCH---\n"
    "---DIVERGENCE---\n\n"
    "Within a section, format each item exactly as:\n"
    "HEADLINE: <short headline, plain language>\n"
    "CONFIDENCE: HIGH|MEDIUM|LOW\n"
    "ENTITIES: <comma-separated entity names, copied from the brief>\n"
    "BODY: <1-3 sentences on mechanism and implication — not a restatement of counts>\n\n"
    "RISKS and OPPORTUNITIES are for entities with a meaningful current-window signal. "
    "EMERGING is for entities flagged NEW below. FADING is for entities flagged FADING "
    "below. WATCH is for anything worth a reader's attention that does not cleanly fit "
    "elsewhere — this is also where you should flag, briefly, any pair in CANDIDATE "
    "ALIASES below that you believe refers to the same real-world entity under two "
    "spellings. DIVERGENCE is for cases where the newsletter narrative and any macro "
    "indicators below appear to contradict each other; leave it empty if no macro data "
    "is provided or nothing diverges.\n\n"
    "{brief_text}"
    "{track_record_block}"
)


def _format_trend(trend) -> str:
    flags = []
    if trend.is_new:
        flags.append("NEW")
    if trend.is_fading:
        flags.append("FADING")
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    z_str = f"{trend.z_score:.2f}" if trend.z_score is not None else "n/a"
    claims = " | ".join(f'"{c}"' for c in trend.sample_claims) or "none"
    return (
        f"- {trend.name} ({trend.entity_type}){flag_str}: current={trend.current_count} "
        f"mentions (prior={trend.prior_count}, delta={trend.delta:+d}, "
        f"velocity={trend.velocity:.2f}/day), {trend.source_breadth} distinct sources, "
        f"net_sentiment={trend.net_sentiment:.2f}, z_score={z_str}. Sample claims: {claims}"
    )


def _format_edges(edges) -> str:
    if not edges:
        return "none"
    return "; ".join(f"{e.entity_a} + {e.entity_b} ({e.count}x, new)" for e in edges)


def _format_macro(macro: MacroSnapshot | None) -> str:
    if macro is None:
        return "No macro data configured.\n"
    lines = ["MACRO INDICATORS:"]
    for ind in macro.indicators:
        alarm = " [ALARM]" if ind.alarm else ""
        lines.append(f"- {ind.label} ({ind.series_id}): {ind.value} as of {ind.as_of}, {ind.direction}{alarm}. {ind.note}")
    return "\n".join(lines) + "\n"


def _format_review(review: CallReview) -> str:
    price = f"{review.price_change_pct:+.1f}%" if review.price_change_pct is not None else "n/a"
    ticker = review.ticker or "no ticker"
    entities = ", ".join(review.entities) or "none"
    return (
        f"CALL_ID {review.call_id} | made {review.made_on.isoformat()} | {review.horizon_days}d | "
        f"{review.section.upper()} | {review.confidence} | \"{review.headline}\" | {entities} | "
        f"price {price} ({ticker}) | {review.mentions_since} mentions from "
        f"{review.sources_since} newsletters since, sentiment {review.sentiment_since:+.1f}"
    )


def _build_track_record_block(track_record: Sequence[CallReview]) -> str:
    if not track_record:
        return ""
    lines = "\n".join(_format_review(r) for r in track_record)
    return (
        "\nTRACK RECORD — your earlier calls, now reviewed (numbers computed deterministically):\n"
        f"{lines}\n\n"
        "---TRACK RECORD---\n"
        "For each CALL_ID in the TRACK RECORD list (and only those ids), write:\n"
        "CALL_ID: <id>\n"
        "BODY: one or two sentences — did the call play out, and what does the price and coverage "
        "evidence say about why. Be direct; \"too early to tell\" is a valid verdict when the "
        "evidence is flat.\n"
    )


def _build_brief_text(brief: TrendBrief, macro: MacroSnapshot | None) -> str:
    trend_lines = "\n".join(_format_trend(t) for t in brief.trends) or "none"
    alias_lines = (
        "; ".join(f"'{a}' / '{b}'" for a, b in brief.alias_candidates) or "none"
    )
    return (
        f"WINDOW: {brief.window_days} days ending {brief.window_end.date().isoformat()}\n\n"
        f"ENTITIES:\n{trend_lines}\n\n"
        f"NEW COOCCURRENCES: {_format_edges(brief.new_edges)}\n\n"
        f"CANDIDATE ALIASES: {alias_lines}\n\n"
        f"{_format_macro(macro)}"
    )


def _parse_section(text: str) -> tuple[SignalItem, ...]:
    items = []
    for match in _ITEM_RE.finditer(text):
        entities = tuple(e.strip() for e in match.group("entities").split(",") if e.strip())
        items.append(
            SignalItem(
                headline=match.group("headline").strip(),
                body=match.group("body").strip(),
                confidence=match.group("confidence").strip().upper(),
                entities=entities,
            )
        )
    return tuple(items)


def _split_sections(raw_text: str) -> dict[str, str]:
    positions = []
    for key, delimiter in _SECTION_DELIMITERS:
        idx = raw_text.find(delimiter)
        if idx != -1:
            positions.append((idx, key, delimiter))
    positions.sort()

    sections: dict[str, str] = {key: "" for key, _ in _SECTION_DELIMITERS}
    for i, (idx, key, delimiter) in enumerate(positions):
        start = idx + len(delimiter)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(raw_text)
        sections[key] = raw_text[start:end]
    return sections


def _parse_track_record_commentary(
    raw_text: str, track_record: Sequence[CallReview], log=None
) -> dict[int, str]:
    """Map known call ids to their model-written commentary.

    Ids not present in the supplied *track_record* are dropped and logged
    (FR-019 pattern). Reviews with no commentary keep ``commentary=""``.
    """
    known = {r.call_id for r in track_record}
    sections = _split_sections(raw_text)
    commentary: dict[int, str] = {}
    for match in _REVIEW_RE.finditer(sections.get("track_record", "")):
        call_id = int(match.group("id"))
        if call_id not in known:
            if log is not None:
                log.warning("track_record_unknown_call_id", call_id=call_id)
            continue
        commentary[call_id] = match.group("body").strip()
    return commentary


def _parse_response(raw_text: str, brief: TrendBrief) -> dict[str, tuple[SignalItem, ...]]:
    """Deterministic validator run before a SignalsReport is constructed.

    Drops any SignalItem naming an entity absent from the brief (FR-019, SC-003).
    Downgrades HIGH confidence to MEDIUM when the item carries no entity evidence (FR-020).
    """
    known_names = {t.name.casefold() for t in brief.trends}
    sections = _split_sections(raw_text)

    result: dict[str, tuple[SignalItem, ...]] = {}
    for key, _ in _SECTION_DELIMITERS:
        parsed_items = _parse_section(sections[key])
        kept = []
        for item in parsed_items:
            if any(e.casefold() not in known_names for e in item.entities):
                continue
            if item.confidence == "HIGH" and not item.entities:
                item = SignalItem(
                    headline=item.headline,
                    body=item.body,
                    confidence="MEDIUM",
                    entities=item.entities,
                    citations=item.citations,
                )
            kept.append(item)
        result[key] = tuple(kept)
    return result


class TrendAnalyzer:
    """Interprets a TrendBrief into a SignalsReport. Never raises (FR-029, FR-038)."""

    def __init__(self, api_key: str, config: SignalsConfig, user_profile: UserProfile | None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._config = config
        self._profile = user_profile
        self._log = get_logger(__name__)
        self._limiter = TokenBucketLimiter(rate=0.5, capacity=1)

    def _build_system_prompt(
        self,
        brief: TrendBrief,
        macro: MacroSnapshot | None,
        track_record: Sequence[CallReview] = (),
    ) -> str:
        return _SYSTEM_PROMPT.format(
            brief_text=_build_brief_text(brief, macro),
            track_record_block=_build_track_record_block(track_record),
        )

    def analyze(
        self,
        brief: TrendBrief,
        macro: MacroSnapshot | None,
        track_record: Sequence[CallReview] = (),
    ) -> SignalsReport:
        """Run the trend interpretation call. Never raises.

        On retry exhaustion, returns a SignalsReport with empty signal tuples but
        *macro* passed through unchanged — a populated macro dashboard is a valid,
        deliverable artifact even when the model call fails entirely (FR-038, SC-009).
        """
        system_prompt = self._build_system_prompt(brief, macro, track_record)
        track_record = tuple(track_record)

        last_exc = None
        for attempt in range(3):
            try:
                self._limiter.acquire()
                response = self._client.messages.create(
                    model=self._config.model,
                    max_tokens=3000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": "Interpret the brief above."}],
                )
                raw_text = extract_text(response)
                sections = _parse_response(raw_text, brief)
                commentary = _parse_track_record_commentary(raw_text, track_record, self._log)
                reviewed = tuple(
                    CallReview(
                        call_id=r.call_id,
                        made_on=r.made_on,
                        horizon_days=r.horizon_days,
                        section=r.section,
                        headline=r.headline,
                        confidence=r.confidence,
                        entities=r.entities,
                        ticker=r.ticker,
                        price_change_pct=r.price_change_pct,
                        mentions_since=r.mentions_since,
                        sources_since=r.sources_since,
                        sentiment_since=r.sentiment_since,
                        commentary=commentary.get(r.call_id, ""),
                    )
                    for r in track_record
                )
                self._log.info(
                    "trend_analysis_complete",
                    risk_count=len(sections["risks"]),
                    opportunity_count=len(sections["opportunities"]),
                    emerging_count=len(sections["emerging"]),
                    fading_count=len(sections["fading"]),
                    watch_count=len(sections["watch"]),
                    divergence_count=len(sections["divergences"]),
                    track_record_count=len(reviewed),
                    attempt=attempt + 1,
                )
                return SignalsReport(
                    generated_at=datetime.now(timezone.utc),
                    window_days=brief.window_days,
                    macro=macro,
                    risks=sections["risks"],
                    opportunities=sections["opportunities"],
                    emerging=sections["emerging"],
                    fading=sections["fading"],
                    watch=sections["watch"],
                    divergences=sections["divergences"],
                    is_cold_start=brief.is_cold_start,
                    observation_count=brief.total_observations,
                    track_record=reviewed,
                )
            except (anthropic.APIError, anthropic.RateLimitError) as exc:
                last_exc = exc
                wait = 1 * (2 ** attempt) + random.uniform(0, 1)
                self._log.warning(
                    "trend_analysis_retry",
                    attempt=attempt + 1,
                    wait=round(wait, 2),
                    error=str(exc),
                )
                time.sleep(wait)

        self._log.error(
            "trend_analysis_failed",
            error=str(last_exc),
            message="Trend analysis failed after 3 attempts — report will carry no signals.",
        )
        return SignalsReport(
            generated_at=datetime.now(timezone.utc),
            window_days=brief.window_days,
            macro=macro,
            is_cold_start=brief.is_cold_start,
            observation_count=brief.total_observations,
            track_record=tuple(track_record),
        )
