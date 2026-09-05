"""Cross-newsletter theme synthesis — clusters ideas by shared entities and merges them.

This module is pure and deterministic: clustering uses only the entities already
extracted during summarization (US1). It never makes network calls. All API calls
are isolated in `ThemeSynthesizer.synthesize`, which mirrors `TrendAnalyzer`'s
retry/backoff/never-raises contract.

Clustering rule:
- Two ideas are linked when they share >= _MIN_SHARED_ENTITIES entities after
  `normalize_key`.
- Clusters are connected components of that link graph.
- Only clusters spanning >= 2 distinct senders are returned (FR-049).
- Clusters are ranked by sender count desc, then idea count desc, then earliest
  idea position, and capped at _MAX_THEMES.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Sequence

import anthropic

from agent.knowledge.canonicalize import normalize_key
from agent.utils.anthropic_text import extract_text
from agent.utils.logger import get_logger
from agent.utils.models import DigestEntry, Theme
from agent.utils.rate_limiter import TokenBucketLimiter

_MIN_SHARED_ENTITIES = 2
_MAX_THEMES = 5

IdeaKey = tuple[str, int]  # (email_id, idea_index)

_SYSTEM_PROMPT = (
    "You are merging coverage of one story from several financial/tech newsletters into a single "
    "reading for a busy investor. You will receive the story as a list of ideas, each labelled with "
    "its source newsletter.\n\n"
    "Write:\n"
    "TITLE: one line, 10 words or fewer, the story itself (not \"Several newsletters discuss...\")\n"
    "BODY: 2-4 sentences. Merge the facts. Name each source newsletter where its contribution is "
    "used, e.g. \"Bloomberg reports X while The AI Journal adds Y.\" Every source must be named at "
    "least once. No bullet points, no markdown.\n"
    "DISAGREEMENT: one or two sentences stating where the sources conflict or emphasize different "
    "things, naming which source holds which view. If they genuinely agree, write exactly NONE.\n\n"
    "Output those three labelled lines and nothing else."
)

log = get_logger(__name__)


def cluster_ideas(entries: Sequence[DigestEntry]) -> list[list[IdeaKey]]:
    """Group ideas that tell the same story across different newsletters.

    Two ideas are linked when they share at least ``_MIN_SHARED_ENTITIES`` entities after
    ``normalize_key``. Clusters are connected components of that link graph. Only clusters
    spanning >=2 distinct senders are returned, ranked by sender count, then size, then the
    position of their earliest idea, and capped at ``_MAX_THEMES``.
    Pass-through entries and entries without ideas are ignored.
    """
    # Build keyed list: (idea_key, sender_lower, frozenset_of_normalized_entities)
    keyed: list[tuple[IdeaKey, str, frozenset[str]]] = []

    for entry in entries:
        if entry.is_pass_through:
            continue
        summary = entry.summary
        if summary.ideas is None:
            continue
        sender_lower = summary.sender.lower()
        for idx, idea in enumerate(summary.ideas):
            if not idea.entities:
                continue
            norm_entities = frozenset(normalize_key(e.name) for e in idea.entities)
            if len(norm_entities) < _MIN_SHARED_ENTITIES:
                continue
            keyed.append(((summary.email_id, idx), sender_lower, norm_entities))

    if not keyed:
        return []

    # Union-Find
    n = len(keyed)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # O(n^2) pairwise comparison
    for i in range(n):
        _, _, entities_i = keyed[i]
        for j in range(i + 1, n):
            _, _, entities_j = keyed[j]
            if len(entities_i & entities_j) >= _MIN_SHARED_ENTITIES:
                union(i, j)

    # Group by root
    clusters: dict[int, list[tuple[IdeaKey, str]]] = {}
    for idx, (key, sender, _) in enumerate(keyed):
        root = find(idx)
        clusters.setdefault(root, []).append((key, sender))

    # Filter clusters with >= 2 distinct senders
    qualified = []
    for cluster in clusters.values():
        senders = {s for _, s in cluster}
        if len(senders) >= 2:
            # Sort by original order (email_id, idea_index)
            cluster.sort(key=lambda x: x[0])
            qualified.append(cluster)

    # Rank: sender count desc, then size desc, then earliest idea position
    def rank_key(cluster: list[tuple[IdeaKey, str]]) -> tuple[int, int, tuple[str, int]]:
        senders = {s for _, s in cluster}
        earliest = cluster[0][0]
        return (-len(senders), -len(cluster), earliest)

    qualified.sort(key=rank_key)

    # Cap at _MAX_THEMES and return just the keys
    return [[key for key, _ in cluster] for cluster in qualified[:_MAX_THEMES]]


class ThemeSynthesizer:
    """Synthesizes merged themes from clustered ideas. Never raises."""

    def __init__(self, api_key: str, *, model: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._limiter = TokenBucketLimiter(rate=0.5, capacity=1)
        self._log = get_logger(__name__)

    def synthesize(self, clusters: list[list[IdeaKey]], entries: Sequence[DigestEntry]) -> tuple[Theme, ...]:
        """One Claude call per cluster. A cluster whose call fails or parses badly yields no
        theme (its ideas then render normally). Never raises."""
        if not clusters:
            return ()

        # Build email_id -> entry lookup
        entry_by_email = {e.summary.email_id: e for e in entries}

        themes: list[Theme] = []
        for cluster in clusters:
            theme = self._synthesize_cluster(cluster, entry_by_email)
            if theme is not None:
                themes.append(theme)
        return tuple(themes)

    def _synthesize_cluster(
        self, cluster: list[IdeaKey], entry_by_email: dict[str, DigestEntry]
    ) -> Theme | None:
        # Build user message with all ideas in this cluster
        sources_ordered: list[str] = []
        seen_senders: set[str] = set()
        parts: list[str] = []

        for email_id, idea_idx in cluster:
            entry = entry_by_email.get(email_id)
            if entry is None or entry.summary.ideas is None:
                continue
            if idea_idx >= len(entry.summary.ideas):
                continue
            idea = entry.summary.ideas[idea_idx]
            display_name = entry.display_name or entry.summary.sender
            if display_name not in seen_senders:
                seen_senders.add(display_name)
                sources_ordered.append(display_name)
            parts.append(
                f"--- {display_name} ---\n"
                f"Title: {idea.title}\n"
                f"{idea.summary_text}\n"
            )

        if not parts:
            return None

        user_message = f"Sources: {len(sources_ordered)}\n\n" + "\n".join(parts)

        last_exc = None
        for attempt in range(3):
            try:
                self._limiter.acquire()
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=1500,
                    output_config={"effort": "medium"},
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}],
                )
                raw = extract_text(response)
                theme = self._parse_theme(raw, tuple(sources_ordered), tuple(cluster))
                if theme is not None:
                    self._log.info(
                        "theme_synthesis_complete",
                        title=theme.title,
                        sources=sources_ordered,
                        attempt=attempt + 1,
                    )
                    return theme
                else:
                    self._log.warning(
                        "theme_synthesis_parse_failed",
                        raw=raw[:200],
                        attempt=attempt + 1,
                    )
            except (anthropic.APIError, anthropic.RateLimitError) as exc:
                last_exc = exc
                wait = 1 * (2**attempt) + random.uniform(0, 1)
                self._log.warning(
                    "theme_synthesis_retry",
                    attempt=attempt + 1,
                    wait=round(wait, 2),
                    error=str(exc),
                )
                time.sleep(wait)

        self._log.error(
            "theme_synthesis_failed",
            error=str(last_exc),
            cluster_keys=cluster,
            message="Theme synthesis failed after 3 attempts — ideas will render normally.",
        )
        return None

    def _parse_theme(
        self, raw: str, sources: tuple[str, ...], keys: tuple[IdeaKey, ...]
    ) -> Theme | None:
        # Regex for labelled lines (TITLE, BODY, DISAGREEMENT) at line start
        # Note: DOTALL makes . match newlines, so use non-greedy or limit to line
        title_match = re.search(r"^TITLE:\s*(.+?)$", raw, re.MULTILINE)
        body_match = re.search(r"^BODY:\s*(.+?)$", raw, re.MULTILINE)
        disagreement_match = re.search(r"^DISAGREEMENT:\s*(.+?)$", raw, re.MULTILINE)

        title = title_match.group(1).strip() if title_match else ""
        body = body_match.group(1).strip() if body_match else ""

        if not title or not body:
            return None

        disagreement = None
        if disagreement_match:
            disc = disagreement_match.group(1).strip()
            if disc and disc.upper() != "NONE":
                disagreement = disc.replace("**", "")

        return Theme(
            title=title,
            body=body,
            sources=sources,
            disagreement=disagreement,
            absorbed_idea_keys=keys,
        )


def synthesize_themes(
    clusters: list[list[IdeaKey]], entries: Sequence[DigestEntry], api_key: str, *, model: str
) -> tuple[Theme, ...]:
    """Convenience function mirroring T069 name. Builds ThemeSynthesizer and calls synthesize."""
    return ThemeSynthesizer(api_key=api_key, model=model).synthesize(clusters, entries)