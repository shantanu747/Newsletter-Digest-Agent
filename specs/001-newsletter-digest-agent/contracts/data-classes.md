# Contract: Data Class Interfaces

**Module**: `agent/utils/models.py`
**Purpose**: Defines all inter-module data types. These are the only types that cross module boundaries. No raw dicts or tuples between pipeline stages.

---

## Email

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Email:
    id: str                      # Gmail message ID — unique per account
    source: str                  # Always "gmail" in current implementation
    sender: str                  # Full sender address, e.g. "hello@stratechery.com"
    subject: str                 # Original subject line
    received_at: datetime        # UTC-aware datetime
    raw_html: str                # Raw HTML body (empty string if plain-text only email)
    plain_text: str | None = None  # Populated by EmailParser; None before parsing
```

**Invariants**:
- `id` is non-empty
- `received_at` is timezone-aware (UTC)
- After `EmailParser.parse()`, `plain_text` is a non-empty string or an empty string (not None) if extraction produced no content
- Instances are frozen (immutable) — pipeline stages return new instances

---

## Summary

```python
@dataclass(frozen=True)
class Summary:
    email_id: str           # References Email.id
    sender: str             # Copied from source Email.sender
    subject: str            # Copied from source Email.subject
    summary_text: str       # Generated summary prose, 200–250 words target
    word_count: int         # len(summary_text.split())
    generated_at: datetime  # UTC-aware datetime
```

**Invariants**:
- `email_id` references a valid `Email.id` from the same run
- `summary_text` is non-empty
- `word_count` is pre-computed and consistent with `summary_text`
- `generated_at` is timezone-aware (UTC)

---

## DigestEntry

```python
@dataclass(frozen=True)
class DigestEntry:
    summary: Summary
    original_email_url: str | None = None  # Optional web-view URL from email headers
```

**Notes**: Thin wrapper adding presentation-layer metadata to a Summary. The `DigestBuilder` accepts `list[DigestEntry]`.

---

## Component Interfaces (not dataclasses — protocol contracts)

### BaseFetcher (abstract)

```python
class BaseFetcher(ABC):
    @abstractmethod
    def fetch_newsletters(
        self,
        config: AgentConfiguration,
    ) -> list[Email]:
        """
        Fetch newsletters matching config filters.
        Returns list of Email objects (plain_text=None).
        Raises FetchError on unrecoverable failure.
        """
```

### EmailParser

```python
class EmailParser:
    def parse(self, email: Email) -> Email:
        """
        Extract plain text from email.raw_html.
        Returns new Email instance with plain_text populated.
        If extraction yields empty string, sets plain_text to "".
        Never raises — logs warnings and returns best-effort result.
        """
```

### ClaudeSummarizer

```python
class ClaudeSummarizer:
    def summarize(self, email: Email) -> Summary:
        """
        Generate a 200–250 word summary of email.plain_text.
        Applies rate limiting before each API call.
        Retries up to 3 times with exponential backoff on transient errors.
        Raises SummarizationError after all retries exhausted.
        """
```

### DigestBuilder

```python
class DigestBuilder:
    def build(self, entries: list[DigestEntry], run_date: datetime) -> str:
        """
        Render Jinja2 HTML template with provided entries.
        Returns complete HTML string ready for email delivery.
        """
```

### EmailDelivery

```python
class EmailDelivery:
    def send(self, html_body: str, subject: str, config: AgentConfiguration) -> None:
        """
        Send HTML email via SMTP.
        Retries once on transient SMTP errors.
        Raises DeliveryError on permanent failure.
        """
```

---

## Exception Types

```python
class NewsletterAgentError(Exception):
    """Base class for all agent errors."""

class ConfigurationError(NewsletterAgentError):
    """Missing or invalid configuration."""

class FetchError(NewsletterAgentError):
    """Unrecoverable error fetching emails from Gmail."""

class SummarizationError(NewsletterAgentError):
    """Summarization failed after all retries."""

class DeliveryError(NewsletterAgentError):
    """Email delivery failed after retry."""
```
