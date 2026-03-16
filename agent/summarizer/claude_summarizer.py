"""ClaudeSummarizer — wraps Anthropic Messages API to summarize newsletter emails.

Implements exponential-backoff retry logic on transient API and rate-limit errors.
"""

import random
import time
from datetime import datetime, timezone

import anthropic

from agent.utils.exceptions import SummarizationError
from agent.utils.logger import get_logger
from agent.utils.models import Email, Summary
from agent.utils.rate_limiter import TokenBucketLimiter

_SYSTEM_PROMPT = (
    "You are a newsletter summarizer. Given a newsletter's text content, produce a "
    "concise summary of 200–250 words. Preserve the author's tone. Highlight the 3–5 "
    "most important points. Do not include greetings, unsubscribe text, or navigation "
    "labels."
)


class ClaudeSummarizer:
    """Summarizes newsletter emails using the Claude claude-sonnet-4-6 model."""

    def __init__(self, api_key: str) -> None:
        """Initialise the summarizer with an Anthropic API key.

        Args:
            api_key: Anthropic API key used to authenticate requests.
        """
        self._client = anthropic.Anthropic(api_key=api_key)
        self._log = get_logger(__name__)
        self._limiter = TokenBucketLimiter(rate=0.5, capacity=1)

    def summarize(self, email: Email) -> Summary:
        """Generate a 200–250 word summary for *email*.

        Retries up to 3 times (with exponential back-off) on ``anthropic.APIError``
        and ``anthropic.RateLimitError``.  Raises ``SummarizationError`` when all
        attempts are exhausted.

        Args:
            email: The newsletter email to summarise.

        Returns:
            A :class:`~agent.utils.models.Summary` dataclass populated with the
            generated text and metadata.

        Raises:
            SummarizationError: If all 3 attempts fail.
        """
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
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_content}],
                )
                text = response.content[0].text.strip()
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
