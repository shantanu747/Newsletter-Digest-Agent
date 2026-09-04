"""Entity canonicalization — three stdlib-only tiers.

Tier 1: normalize_key() — deterministic folding (NFKD, casefold, possessive/suffix
stripping) so 'Nvidia' == 'NVIDIA Corp.' == "Nvidia's" collapse to one key.
Tier 2: seed_aliases_from_profile() — ticker/name pairs from user_profile.yaml, a
relationship no string algorithm can bridge on its own.
Tier 3: find_alias_candidates() — difflib-based near-duplicate proposals for human
(via the trend-analysis call) adjudication. Proposes; never merges.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

_CORPORATE_SUFFIXES = {
    "inc", "corp", "corporation", "ltd", "limited", "plc", "nv", "sa", "ag", "co", "llc",
}

_POSSESSIVE_RE = re.compile(r"['’]s\b")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")


def normalize_key(name: str) -> str:
    """Fold *name* into a canonicalization key.

    NFKD-normalizes and strips combining marks (accent-insensitive), casefolds,
    strips a trailing possessive ('s), strips punctuation, and drops a single
    trailing corporate suffix token (Inc, Corp, Ltd, ...). Whitespace is collapsed.
    """
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = _POSSESSIVE_RE.sub("", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    words = text.split()
    while words and words[-1] in _CORPORATE_SUFFIXES:
        words.pop()
    return " ".join(words)


def seed_aliases_from_profile(profile) -> list[tuple[str, str]]:
    """Map each portfolio/watchlist ticker to its display name.

    Returns (ticker, name) pairs — e.g. ('UAL', 'United Airlines') — a relationship
    normalize_key() alone cannot bridge. Returns [] when *profile* is None.
    """
    if profile is None:
        return []
    pairs: list[tuple[str, str]] = []
    for entry in list(profile.portfolio) + list(profile.watchlist):
        ticker = entry.get("ticker")
        name = entry.get("name")
        if ticker and name:
            pairs.append((str(ticker), str(name)))
    return pairs


def find_alias_candidates(names: list[str], threshold: float = 0.86) -> list[tuple[str, str]]:
    """Propose near-duplicate name pairs for adjudication. Does not merge anything.

    Compares the shorter name against the equal-length prefix of the longer one via
    difflib.SequenceMatcher, so an abbreviation ('Fed') matches its expansion
    ('Federal Reserve') while two merely similar-looking names ('Apple',
    'Applied Materials') do not.
    """
    unique = sorted(set(n for n in names if len(n) >= 3))
    candidates: list[tuple[str, str]] = []
    for i in range(len(unique)):
        for j in range(i + 1, len(unique)):
            a, b = unique[i], unique[j]
            short, long_ = (a, b) if len(a) <= len(b) else (b, a)
            prefix = long_[: len(short)]
            ratio = difflib.SequenceMatcher(None, short.casefold(), prefix.casefold()).ratio()
            if ratio >= threshold and short.casefold() != long_.casefold():
                candidates.append((short, long_))
    return candidates
