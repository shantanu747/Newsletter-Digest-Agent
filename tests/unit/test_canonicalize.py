"""Unit tests for agent.knowledge.canonicalize (T018-T020)."""

from agent.knowledge.canonicalize import (
    find_alias_candidates,
    normalize_key,
    seed_aliases_from_profile,
)
from agent.utils.config import UserProfile


def _make_profile(
    interests: list[str] | None = None,
    portfolio: list[dict] | None = None,
    watchlist: list[dict] | None = None,
    custom_prompts: list[str] | None = None,
) -> UserProfile:
    return UserProfile(
        interests=interests or ["aviation", "electric vehicles"],
        portfolio=portfolio or [{"ticker": "UAL", "name": "United Airlines", "notes": "Watch fuel costs."}],
        watchlist=watchlist or [{"ticker": "NVDA", "name": "Nvidia"}],
        custom_prompts=custom_prompts or [],
    )


class TestNormalizeKey:
    def test_collapses_nvidia_variants_to_one_key(self):
        keys = {normalize_key("Nvidia"), normalize_key("NVIDIA Corp."), normalize_key("Nvidia's")}
        assert len(keys) == 1

    def test_strips_trailing_corporate_suffix(self):
        assert normalize_key("Acme Ltd") == normalize_key("Acme")

    def test_collapses_whitespace_and_punctuation(self):
        assert normalize_key("  Federal   Reserve! ") == "federal reserve"

    def test_casefold_insensitive(self):
        assert normalize_key("APPLE") == normalize_key("apple")


class TestSeedAliasesFromProfile:
    def test_maps_ticker_to_name_from_portfolio_and_watchlist(self):
        pairs = seed_aliases_from_profile(_make_profile())
        assert ("UAL", "United Airlines") in pairs
        assert ("NVDA", "Nvidia") in pairs

    def test_none_profile_returns_empty_list(self):
        assert seed_aliases_from_profile(None) == []

    def test_entry_missing_name_or_ticker_is_skipped(self):
        profile = _make_profile(portfolio=[{"ticker": "XYZ"}], watchlist=[{"name": "No Ticker Co"}])
        assert seed_aliases_from_profile(profile) == []


class TestFindAliasCandidates:
    def test_proposes_fed_and_federal_reserve(self):
        candidates = find_alias_candidates(["Fed", "Federal Reserve"])
        assert ("Fed", "Federal Reserve") in candidates

    def test_does_not_propose_apple_and_applied_materials(self):
        candidates = find_alias_candidates(["Apple", "Applied Materials"])
        assert candidates == []

    def test_identical_names_not_proposed(self):
        assert find_alias_candidates(["Nvidia", "Nvidia"]) == []
