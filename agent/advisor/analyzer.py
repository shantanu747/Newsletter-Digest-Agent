"""AdvisorAnalyzer — synthesizes personalized insights across all newsletter summaries.

Runs a single Claude call after the full summarization pass, producing two optional
advisory sections:
  - RELEVANCE: how today's collective news affects the reader's holdings/interests
  - SIGNALS:   actionable buy/sell/watch recommendations synthesized across all newsletters
"""

from __future__ import annotations

import random
import time

import anthropic

from agent.utils.config import UserProfile
from agent.utils.exceptions import SummarizationError
from agent.utils.logger import get_logger
from agent.utils.models import AdvisorAnalysis, Summary

_RELEVANCE_DELIMITER = "---RELEVANCE---"
_SIGNALS_DELIMITER = "---SIGNALS---"

_SYSTEM_PROMPT = (
    "You are a personal financial advisor reading a digest of newsletter summaries "
    "on behalf of the reader. Your job is to analyze the collective content and "
    "produce actionable insights tailored to the reader's interests and portfolio.\n\n"
    "Produce up to two advisory sections after reviewing all newsletters — only when "
    "genuinely warranted:\n\n"
    "SECTION 1 — RELEVANCE: How does today's collective news affect the reader's "
    "existing interests or holdings? Include second-order effects (e.g., rising oil → "
    "airlines face margin pressure; chip export controls → AI infrastructure stocks at "
    "risk). Synthesize across all newsletters — do not repeat the same point per source. "
    "Omit entirely if no meaningful connection exists.\n\n"
    "SECTION 2 — SIGNALS: Based on today's collective news, are there actionable "
    "considerations? For buys: identify stocks or ETFs the reader does NOT currently "
    "hold that stand to benefit — including thematic plays (e.g., oil price rise → "
    "consider XOM, CVX; EV adoption → consider charging infrastructure ETFs). For "
    "sells: flag current holdings showing exit signals. Format each signal as:\n"
    "  [BUY/SELL/WATCH] TICKER (Name) — one sentence rationale\n"
    "Omit entirely if there are no clear signals.\n\n"
    "READER PROFILE:\n"
    "INTERESTS: {interests}\n\n"
    "PORTFOLIO (holdings): {portfolio}\n\n"
    "WATCHLIST (watching, not held): {watchlist}\n\n"
    "{custom_block}"
    "Format your full response as:\n"
    "<any brief framing sentence if needed, or skip entirely>\n"
    "---RELEVANCE---\n"
    "<portfolio/interest implications — omit this delimiter and block if none>\n"
    "---SIGNALS---\n"
    "<buy/sell/watch signals — omit this delimiter and block if none>"
)


def _fmt_holdings(items: list[dict]) -> str:
    if not items:
        return "none"
    parts = []
    for item in items:
        entry = f"{item['ticker']} ({item['name']})"
        if item.get("notes"):
            entry += f": {item['notes']}"
        parts.append(entry)
    return "; ".join(parts)


class AdvisorAnalyzer:
    """Produces a single personalized advisor analysis across all digest summaries."""

    def __init__(self, api_key: str, user_profile: UserProfile) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._profile = user_profile
        self._log = get_logger(__name__)

    def _build_system_prompt(self) -> str:
        interests_str = ", ".join(self._profile.interests) or "none"
        portfolio_str = _fmt_holdings(self._profile.portfolio)
        watchlist_str = _fmt_holdings(self._profile.watchlist)

        if self._profile.custom_prompts:
            lines = "\n".join(f"  - {p}" for p in self._profile.custom_prompts)
            custom_block = f"ADDITIONAL INSTRUCTIONS FROM THE READER:\n{lines}\n\n"
        else:
            custom_block = ""

        return _SYSTEM_PROMPT.format(
            interests=interests_str,
            portfolio=portfolio_str,
            watchlist=watchlist_str,
            custom_block=custom_block,
        )

    def _build_user_message(self, summaries: list[Summary]) -> str:
        parts = ["Here are today's newsletter summaries:\n"]
        for s in summaries:
            label = s.subject or s.sender
            parts.append(f"--- {label} ---\n{s.summary_text}\n")
        return "\n".join(parts)

    def _parse_response(self, text: str) -> AdvisorAnalysis:
        """Split Claude's response into relevance and signals sections."""
        relevance_text: str | None = None
        signals_text: str | None = None

        if _RELEVANCE_DELIMITER in text:
            after_relevance = text.split(_RELEVANCE_DELIMITER, 1)[1]
            if _SIGNALS_DELIMITER in after_relevance:
                relevance_raw, signals_raw = after_relevance.split(_SIGNALS_DELIMITER, 1)
                relevance_text = relevance_raw.strip() or None
                signals_text = signals_raw.strip() or None
            else:
                relevance_text = after_relevance.strip() or None
        elif _SIGNALS_DELIMITER in text:
            signals_text = text.split(_SIGNALS_DELIMITER, 1)[1].strip() or None

        return AdvisorAnalysis(relevance_text=relevance_text, signals_text=signals_text)

    def analyze(self, summaries: list[Summary]) -> AdvisorAnalysis:
        """Run one Claude call across all summaries and return an AdvisorAnalysis.

        Retries up to 3 times on transient API/rate-limit errors. Returns an
        AdvisorAnalysis with both fields None if the call exhausts all retries.

        Args:
            summaries: All Summary objects from the current digest batch.

        Returns:
            AdvisorAnalysis with optional relevance_text and signals_text.
        """
        if not summaries:
            return AdvisorAnalysis(relevance_text=None, signals_text=None)

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(summaries)

        last_exc = None
        for attempt in range(3):
            try:
                response = self._client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1200,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                raw_text = response.content[0].text.strip().replace("**", "")
                analysis = self._parse_response(raw_text)
                self._log.info(
                    "advisor_analysis_complete",
                    newsletter_count=len(summaries),
                    has_relevance=analysis.relevance_text is not None,
                    has_signals=analysis.signals_text is not None,
                    attempt=attempt + 1,
                )
                return analysis
            except (anthropic.APIError, anthropic.RateLimitError) as exc:
                last_exc = exc
                wait = 1 * (2 ** attempt) + random.uniform(0, 1)
                self._log.warning(
                    "advisor_retry",
                    attempt=attempt + 1,
                    wait=round(wait, 2),
                    error=str(exc),
                )
                time.sleep(wait)

        self._log.error(
            "advisor_analysis_failed",
            error=str(last_exc),
            message="Advisor analysis failed after 3 attempts — digest will have no advisor section.",
        )
        return AdvisorAnalysis(relevance_text=None, signals_text=None)
