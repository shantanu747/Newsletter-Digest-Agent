"""ClaudeSummarizer — wraps Anthropic Messages API to summarize newsletter emails.

Implements exponential-backoff retry logic on transient API and rate-limit errors.
For pass_through emails, bypasses Claude entirely and wraps the pre-processed text.
"""

import random
import re
import time
from datetime import datetime, timezone

import anthropic

from agent.utils.exceptions import SummarizationError
from agent.utils.logger import get_logger
from agent.utils.models import Email, Idea, Summary
from agent.utils.rate_limiter import TokenBucketLimiter

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a newsletter summarizer. Given a newsletter's text content, produce a "
    "concise summary of approximately {target} words. Preserve the author's tone. "
    "Highlight the 3–5 most important points. Do not include greetings, unsubscribe "
    "text, or navigation labels."
)

_IDEA_SYSTEM_PROMPT_TEMPLATE = """\
You are a plugged-in, well-informed advisor who cuts through noise. \
You do not sugarcoat. You do not pad. \
You present information in a grounded, rational, and succinct way.

{profile_section}\
Given the newsletter text below, identify every discrete, significant idea. \
For each idea, output:

IDEA: <short title (8 words or fewer)>
<1–3 sentence summary. No filler. No hedging. No transitional phrases. \
Where the idea directly relates to the reader's holdings or interests, \
note that connection briefly within the summary.>

If the entire email is a single idea, output exactly one IDEA entry.
Output only ideas derivable from the text provided — do not infer or fabricate.
Do not include URLs. Do not include links.\
"""


def _build_profile_section(user_profile) -> str:
    """Build a reader-context block to inject into the idea-based system prompt."""
    if user_profile is None:
        return ""
    lines = []
    if user_profile.portfolio:
        holdings = ", ".join(f"{h['ticker']} ({h['name']})" for h in user_profile.portfolio)
        lines.append(f"Reader holds: {holdings}")
    if user_profile.watchlist:
        watching = ", ".join(f"{h['ticker']} ({h['name']})" for h in user_profile.watchlist)
        lines.append(f"Reader is watching: {watching}")
    if user_profile.interests:
        lines.append(f"Reader's interests: {', '.join(user_profile.interests)}")
    if user_profile.custom_prompts:
        lines.append("Standing instructions: " + " ".join(user_profile.custom_prompts))
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def _parse_ideas(raw: str) -> tuple[Idea, ...]:
    """Parse a Claude response containing IDEA: blocks into a tuple of Idea objects.

    If the response contains no parseable IDEA blocks, returns a single
    'Content Unavailable' fallback idea.
    """
    segments = re.split(r"(?:^|\n)IDEA:\s*", raw.strip())
    ideas: list[Idea] = []
    for seg in segments[1:]:
        seg = seg.strip()
        if not seg:
            continue
        lines = seg.split("\n", 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if title:
            ideas.append(Idea(title=title, summary_text=body))
    if not ideas:
        return (Idea(
            title="Content Unavailable",
            summary_text="Unable to extract ideas from this newsletter.",
        ),)
    return tuple(ideas)


class ClaudeSummarizer:
    """Summarizes newsletter emails using the Claude claude-sonnet-4-6 model."""

    def __init__(
        self,
        api_key: str,
        *,
        summary_length_mode: str = "fixed",
        summary_word_target: int = 225,
        summary_percentage: int = 18,
        summary_min_words: int = 100,
        summary_max_words: int = 500,
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._log = get_logger(__name__)
        self._limiter = TokenBucketLimiter(rate=0.5, capacity=1)
        self._mode = summary_length_mode
        self._word_target = summary_word_target
        self._percentage = summary_percentage
        self._min_words = summary_min_words
        self._max_words = summary_max_words

    def _compute_target(self, email: Email) -> int:
        if self._mode == "percentage":
            wc = len((email.plain_text or "").split())
            return max(self._min_words, min(self._max_words, int(wc * self._percentage / 100)))
        return self._word_target

    def summarize(self, email: Email) -> Summary:
        """Generate a summary for *email*.

        For pass_through emails (email.is_pass_through=True), skips the Claude API
        and returns a Summary wrapping the pre-processed plain_text directly.

        For normal emails, retries up to 3 times (with exponential back-off) on
        ``anthropic.APIError`` and ``anthropic.RateLimitError``. Raises
        ``SummarizationError`` when all attempts are exhausted.

        Args:
            email: The newsletter email to summarise.

        Returns:
            A :class:`~agent.utils.models.Summary` dataclass populated with the
            generated text and metadata.

        Raises:
            SummarizationError: If all 3 attempts fail (summarize mode only).
        """
        # Pass-through bypass: skip Claude API entirely
        if email.is_pass_through:
            text = (email.plain_text or "").strip()
            word_count = len(text.split())
            self._log.info(
                "newsletter_pass_through",
                message_id=email.id,
                word_count=word_count,
            )
            return Summary(
                email_id=email.id,
                sender=email.sender,
                subject=email.subject,
                summary_text=text,
                word_count=word_count,
                generated_at=datetime.now(timezone.utc),
            )

        # Standard summarization path
        target = self._compute_target(email)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(target=target)
        user_content = (
            f"Summarize the following newsletter:\n---\n"
            f"{email.plain_text or email.raw_html[:8000]}\n---"
        )

        last_exc = None
        for attempt in range(3):
            try:
                self._limiter.acquire()
                response = self._client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_content}],
                )
                text = response.content[0].text.strip().replace("**", "")
                word_count = len(text.split())
                self._log.info(
                    "newsletter_summarized",
                    message_id=email.id,
                    word_count=word_count,
                    attempt=attempt + 1,
                )
                return Summary(
                    email_id=email.id,
                    sender=email.sender,
                    subject=email.subject,
                    summary_text=text,
                    word_count=word_count,
                    generated_at=datetime.now(timezone.utc),
                )
            except (anthropic.APIError, anthropic.RateLimitError) as exc:
                last_exc = exc
                wait = 1 * (2 ** attempt) + random.uniform(0, 1)
                self._log.warning(
                    "summarization_retry",
                    message_id=email.id,
                    attempt=attempt + 1,
                    wait=round(wait, 2),
                    error=str(exc),
                )
                time.sleep(wait)

        raise SummarizationError(
            f"Summarization failed after 3 attempts for message {email.id}: {last_exc}"
        ) from last_exc

    def summarize_as_ideas(self, email: Email, user_profile) -> Summary:
        """Decompose *email* into discrete ideas using the idea-based digest format.

        *user_profile* supplies reader context for inline connection notes only;
        it does not filter ideas. When *user_profile* is None, no profile context
        is injected.

        Retries up to 3 times with exponential back-off on transient API errors.
        Raises SummarizationError when all attempts are exhausted.

        Args:
            email: The newsletter email to decompose.
            user_profile: Reader profile for framing context, or None.

        Returns:
            A Summary with ideas populated and summary_text="" / word_count=0.

        Raises:
            SummarizationError: If all 3 attempts fail.
        """
        self._log.info(
            "newsletter_idea_decomposition_started",
            newsletter_id=email.id,
            sender=email.sender,
            digest_format="idea_based",
        )

        profile_section = _build_profile_section(user_profile)
        system_prompt = _IDEA_SYSTEM_PROMPT_TEMPLATE.format(profile_section=profile_section)
        user_content = (
            f"Decompose the following newsletter into ideas:\n---\n"
            f"{email.plain_text or email.raw_html[:8000]}\n---"
        )

        last_exc = None
        for attempt in range(3):
            try:
                self._limiter.acquire()
                response = self._client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2048,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_content}],
                )
                raw = response.content[0].text.strip()
                ideas = _parse_ideas(raw)
                self._log.info(
                    "newsletter_ideas_extracted",
                    newsletter_id=email.id,
                    sender=email.sender,
                    digest_format="idea_based",
                    idea_count=len(ideas),
                    attempt=attempt + 1,
                )
                return Summary(
                    email_id=email.id,
                    sender=email.sender,
                    subject=email.subject,
                    summary_text="",
                    word_count=0,
                    generated_at=datetime.now(timezone.utc),
                    ideas=ideas,
                )
            except (anthropic.APIError, anthropic.RateLimitError) as exc:
                last_exc = exc
                wait = 1 * (2 ** attempt) + random.uniform(0, 1)
                self._log.warning(
                    "idea_decomposition_retry",
                    newsletter_id=email.id,
                    attempt=attempt + 1,
                    wait=round(wait, 2),
                    error=str(exc),
                )
                time.sleep(wait)

        raise SummarizationError(
            f"Idea decomposition failed after 3 attempts for message {email.id}: {last_exc}"
        ) from last_exc
