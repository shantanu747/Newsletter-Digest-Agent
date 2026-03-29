"""ClaudeSummarizer — wraps Anthropic Messages API to summarize newsletter emails.

Implements exponential-backoff retry logic on transient API and rate-limit errors.
For pass_through emails, bypasses Claude entirely and wraps the pre-processed text.
"""

import random
import time
from datetime import datetime, timezone

import anthropic

from agent.utils.exceptions import SummarizationError
from agent.utils.logger import get_logger
from agent.utils.models import Email, Summary
from agent.utils.rate_limiter import TokenBucketLimiter

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a newsletter summarizer. Given a newsletter's text content, produce a "
    "concise summary of approximately {target} words. Preserve the author's tone. "
    "Highlight the 3–5 most important points. Do not include greetings, unsubscribe "
    "text, or navigation labels."
)


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
