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
class EntityMention:
    """An entity named within a single idea, extracted alongside it. Not yet canonicalized."""

    name: str
    """Entity name as written by the model (e.g. 'Nvidia', 'export controls')."""

    entity_type: str
    """One of: company, person, country, policy, sector, technology, asset, institution, event, concept."""

    sentiment: str
    """How this idea frames the entity — 'positive' | 'negative' | 'neutral'."""


@dataclass(frozen=True)
class Idea:
    """A discrete concept extracted from a newsletter email in idea-based digest mode."""

    title: str
    """Short label for the idea (8 words or fewer)."""

    summary_text: str
    """1–3 sentence summary of the idea. No filler, no hedging."""

    entities: tuple[EntityMention, ...] = field(default_factory=tuple)
    """Entities named within this idea, for the persistent knowledge layer. Empty when disabled."""


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
    """Generated summary prose (or pass-through text for pass_through senders).
    Empty string in idea_based mode — use ideas instead."""

    word_count: int
    """Actual word count of summary_text. Zero in idea_based mode."""

    generated_at: datetime
    """UTC-aware datetime when the summary was generated."""

    ideas: tuple[Idea, ...] | None = None
    """Decomposed ideas in idea_based digest mode. None in classic mode."""


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
class Theme:
    """A story told by several newsletters, merged into one reading (P3 synthesis)."""

    title: str
    body: str
    sources: tuple[str, ...]
    """Display names of every contributing newsletter, in cluster order."""
    disagreement: str | None
    """Where the sources conflict, stated plainly. None when they agree."""
    absorbed_idea_keys: tuple[tuple[str, int], ...]
    """(email_id, idea_index) pairs the renderer hides from per-newsletter sections."""


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

    themes: tuple[Theme, ...] = field(default_factory=tuple)
    """Cross-newsletter synthesized themes (P3). Empty when synthesis disabled."""


@dataclass(frozen=True)
class EntityTrend:
    """One entity's deterministically computed movement. Nothing here is produced by a model."""

    entity_id: int
    """Primary key of this entity in the `entity` table."""

    name: str
    """Canonical display name."""

    entity_type: str
    """One of: company, person, country, policy, sector, technology, asset, institution, event, concept."""

    current_count: int
    """Mentions in the current window."""

    prior_count: int
    """Mentions in the preceding window."""

    delta: int
    """current_count minus prior_count."""

    velocity: float
    """Rate of change between the two windows."""

    source_breadth: int
    """Count of distinct senders mentioning this entity in the current window — enforces FR-014."""

    z_score: float | None
    """Standard-deviation movement against this entity's own daily history. None when fewer than 8 daily buckets exist (FR-016)."""

    net_sentiment: float
    """(positive - negative) / total, in the range -1.0 to 1.0."""

    is_new: bool
    """True when this entity first appears in the current window (FR-012)."""

    is_fading: bool
    """True when this entity was previously active and has gone silent (FR-012)."""

    sample_claims: tuple[str, ...] = field(default_factory=tuple)
    """Up to 3 verbatim claim excerpts, for traceability (SC-003)."""


@dataclass(frozen=True)
class CooccurrenceEdge:
    """A pair of entities that appeared together within the same idea."""

    entity_a: str
    """Canonical display name of the first entity."""

    entity_b: str
    """Canonical display name of the second entity."""

    count: int
    """Number of ideas in the window in which this pair co-occurred."""

    is_new: bool
    """True when this pair did not co-occur in the prior window."""


@dataclass(frozen=True)
class TrendBrief:
    """What the analysis model receives — the only thing it receives from the store."""

    window_days: int
    """Length of the analysis window, in days."""

    window_start: datetime
    """Start of the current analysis window."""

    window_end: datetime
    """End of the current analysis window."""

    trends: tuple[EntityTrend, ...]
    """Ranked, truncated to max_entities_in_prompt — already the final set the model will see."""

    new_edges: tuple[CooccurrenceEdge, ...]
    """Co-occurrence edges newly formed in this window."""

    total_observations: int
    """Full store observation count, for the cold-start check."""

    distinct_senders: int
    """Distinct senders across the entire store."""

    is_cold_start: bool
    """True when history spans fewer than two windows (FR-022)."""

    alias_candidates: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    """Near-duplicate name pairs proposed for adjudication, not yet merged."""


@dataclass(frozen=True)
class MacroIndicator:
    """A single macroeconomic series reading."""

    series_id: str
    """FRED series identifier (e.g. 'T10Y3M')."""

    label: str
    """Human-readable name."""

    value: float
    """Latest observed value."""

    as_of: str
    """ISO-8601 date of the latest observation (FR-037)."""

    direction: str
    """'rising' | 'falling' | 'flat', computed from trailing observations."""

    alarm: bool
    """True when this series has crossed its domain-knowledge threshold (FR-037)."""

    note: str
    """Plain-language reading of what this series means."""


@dataclass(frozen=True)
class MacroSnapshot:
    """A fetched set of macro indicators. None upstream means unconfigured."""

    indicators: tuple[MacroIndicator, ...]
    """One entry per configured series that could be fetched."""

    fetched_at: datetime
    """When this snapshot was fetched."""

    partial: bool
    """True when some series failed to fetch but at least one succeeded (FR-039)."""


@dataclass(frozen=True)
class SignalItem:
    """One interpreted finding in a Signals Report."""

    headline: str
    """Short statement of the finding."""

    body: str
    """Mechanism and consequence — not a restatement of the headline."""

    confidence: str
    """'HIGH' | 'MEDIUM' | 'LOW' (FR-018)."""

    entities: tuple[str, ...] = field(default_factory=tuple)
    """Entity names this item concerns — validated against the brief (FR-019)."""

    citations: tuple[str, ...] = field(default_factory=tuple)
    """Populated only when web search ran (FR-042)."""


@dataclass(frozen=True)
class SignalsReport:
    """The periodic Signals Report — the deliverable artifact of the trend-analysis pass."""

    generated_at: datetime
    """When this report was generated."""

    window_days: int
    """Length of the analysis window, in days."""

    macro: MacroSnapshot | None
    """Macro dashboard snapshot. None when unconfigured — an empty report with macro populated is still valid (FR-038)."""

    risks: tuple[SignalItem, ...] = field(default_factory=tuple)
    """Accelerating risks."""

    opportunities: tuple[SignalItem, ...] = field(default_factory=tuple)
    """Opportunities."""

    emerging: tuple[SignalItem, ...] = field(default_factory=tuple)
    """Emerging themes."""

    fading: tuple[SignalItem, ...] = field(default_factory=tuple)
    """Fading stories."""

    watch: tuple[SignalItem, ...] = field(default_factory=tuple)
    """Watch items."""

    divergences: tuple[SignalItem, ...] = field(default_factory=tuple)
    """Narrative-vs-indicator divergences (FR-044)."""

    is_cold_start: bool = False
    """True when history spans fewer than two windows (FR-022)."""

    observation_count: int = 0
    """Total observation count in the store at generation time."""
