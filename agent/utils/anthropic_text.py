"""Helpers for reading Anthropic Messages responses.

Sonnet 5 / Opus 5 may return thinking blocks before the text block, and server-side tool
blocks can also precede it, so callers must never index ``response.content[0]``.
"""

from __future__ import annotations


def extract_text(response) -> str:
    """Concatenate every ``type == "text"`` content block, stripped of surrounding whitespace.

    Returns "" when the response has no text blocks (e.g. ``stop_reason == "refusal"``).
    """
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()
