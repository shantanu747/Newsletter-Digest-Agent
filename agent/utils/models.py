"""Shared dataclasses for inter-module data transfer.

All pipeline stages communicate exclusively through these types.
No raw dicts or untyped tuples cross module boundaries.
"""

from dataclasses import dataclass, field
from datetime import datetime


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
    """Generated summary prose."""

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
