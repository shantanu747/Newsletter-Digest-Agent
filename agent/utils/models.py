"""Shared dataclasses for inter-module data transfer.

All pipeline stages communicate exclusively through these types.
No raw dicts or untyped tuples cross module boundaries.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class EmailLink:
    """A content link extracted from a newsletter email."""

    url: str
    """Destination URL (https only)."""

    title: str
    """Anchor text of the link, truncated to 60 chars."""

    context: str
    """Surrounding sentence snippet providing context, up to 120 chars."""


@dataclass(frozen=True)
class SenderConfig:
    """Per-sender processing rules from config/newsletters.yaml."""

    address: str
    """Sender email address (matching key, case-insensitive)."""

    mode: Literal["pass_through", "summarize"] = "summarize"
    """Processing mode — pass_through preserves content; summarize calls Claude."""

    display_name: str | None = None
    """Human-readable name shown in digest (falls back to From header)."""

    summary_word_target: int | None = None
    """Custom word target for summarize mode (overrides global default)."""

    include_images: bool = True
    """Whether to include qualifying images from this sender."""

    max_images: int | None = None
    """Max images to include from this sender (overrides global _MAX_IMAGES)."""


@dataclass(frozen=True)
class Email:
    """A single newsletter email fetched from Gmail or loaded from an .eml file."""

    id: str
    """Unique message ID — used for deduplication."""

    source: str
    """'gmail' for live fetches, 'eml_file' for local test fixtures."""

    sender: str
    """Full sender address, e.g. 'hello@stratechery.com'."""

    subject: str
    """Original email subject line."""

    received_at: datetime
    """UTC-aware datetime when the email was received."""

    raw_html: str
    """Raw HTML body. Empty string for plain-text-only emails."""

    plain_text: str | None = None
    """Extracted plain text. None until EmailParser runs; '' if extraction yields nothing."""

    links: tuple[EmailLink, ...] = field(default_factory=tuple)
    """Article links extracted by EmailParser. Empty tuple until parsing runs."""

    images: tuple[str, ...] = field(default_factory=tuple)
    """Content image URLs extracted by EmailParser. Empty tuple until parsing runs."""

    gmail_message_id: str = ""
    """Raw Gmail message ID — used for mark-as-read and trash API calls."""

    is_pass_through: bool = False
    """Whether this email was processed in pass-through mode (no AI summarization)."""


@dataclass(frozen=True)
class Summary:
    """An AI-generated summary of a single newsletter email."""

    email_id: str
    """References Email.id — links this summary to its source email."""

    sender: str
    """Copied from source Email.sender."""

    subject: str
    """Copied from source Email.subject."""

    summary_text: str
    """Generated summary prose (or pass-through text for pass_through senders)."""

    word_count: int
    """Actual word count of summary_text."""

    generated_at: datetime
    """UTC-aware datetime when the summary was generated."""


@dataclass(frozen=True)
class DigestEntry:
    """A single entry in the assembled digest."""

    summary: Summary
    """The underlying summary."""

    original_email_url: str | None = None
    """Optional web-view URL for the original newsletter (from email headers)."""

    links: tuple[EmailLink, ...] = field(default_factory=tuple)
    """Article links to render in the 'Further Reading' section."""

    images: tuple[str, ...] = field(default_factory=tuple)
    """Content image URLs to render inline in the digest."""

    is_pass_through: bool = False
    """Whether content was passed through (not AI-summarized)."""

    display_name: str = ""
    """Human-readable sender name for template rendering."""

    gmail_message_id: str = ""
    """Propagated from Email — used for post-delivery mark-as-read and trash."""


@dataclass(frozen=True)
class AdvisorAnalysis:
    """Personalized advisor output synthesized across all newsletters in a digest."""

    relevance_text: str | None
    """How today's collective news affects the reader's existing holdings/interests."""

    signals_text: str | None
    """Actionable buy/sell/watch signals synthesized across all newsletters."""


@dataclass(frozen=True)
class DigestBatch:
    """A group of up to batch_size emails assembled into one digest email."""

    batch_index: int
    """0-based index of this batch in the current poll run."""

    entries: list[DigestEntry]
    """Processed entries in this batch (max batch_size)."""

    gmail_message_ids: list[str]
    """Source email IDs for post-delivery label operations."""

    total_batches: int
    """Total number of batches in this poll run (for subject line and logging)."""

    advisor: AdvisorAnalysis | None = None
    """Personalized advisor analysis. None when no user profile is configured."""
