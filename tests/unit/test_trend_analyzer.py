"""Unit tests for TrendAnalyzer (T041). Zero real API calls.

Tests cover:
- Well-formed delimited response parses into the right sections
- SignalItem naming an entity absent from the brief is dropped (FR-019, SC-003)
- Evidence-free HIGH confidence is downgraded to MEDIUM (FR-020)
- 3 consecutive anthropic.APIError does not propagate — empty report returned (FR-029)
- The rate limiter is acquired before every attempt (Constitution IV)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import anthropic

from agent.trends.analyzer import TrendAnalyzer
from agent.utils.config import SignalsConfig
from agent.utils.models import CallReview, EntityTrend, TrendBrief


def _make_config(**overrides) -> SignalsConfig:
    return SignalsConfig(**overrides)


def _make_trend(name: str = "Nvidia", **overrides) -> EntityTrend:
    defaults = dict(
        entity_id=1,
        name=name,
        entity_type="company",
        current_count=12,
        prior_count=7,
        delta=5,
        velocity=0.71,
        source_breadth=4,
        z_score=2.1,
        net_sentiment=0.6,
        is_new=False,
        is_fading=False,
        sample_claims=("Nvidia posted strong data center growth.",),
    )
    defaults.update(overrides)
    return EntityTrend(**defaults)


def _make_brief(trends=None, **overrides) -> TrendBrief:
    defaults = dict(
        window_days=7,
        window_start=datetime(2026, 8, 27, tzinfo=timezone.utc),
        window_end=datetime(2026, 9, 3, tzinfo=timezone.utc),
        trends=trends if trends is not None else (_make_trend(),),
        new_edges=(),
        total_observations=50,
        distinct_senders=5,
        is_cold_start=False,
        alias_candidates=(),
    )
    defaults.update(overrides)
    return TrendBrief(**defaults)


def _make_analyzer() -> TrendAnalyzer:
    return TrendAnalyzer(api_key="test-key", config=_make_config(), user_profile=None)


def _mock_response(text: str) -> MagicMock:
    response = MagicMock()
    response.content = [MagicMock(type="text", text=text)]
    return response


def _make_review(call_id: int = 17, **overrides) -> CallReview:
    defaults = dict(
        call_id=call_id,
        made_on=date(2026, 8, 5),
        horizon_days=30,
        section="opportunities",
        headline="Data center demand still climbing",
        confidence="HIGH",
        entities=("Nvidia",),
        ticker="NVDA",
        price_change_pct=12.4,
        mentions_since=9,
        sources_since=4,
        sentiment_since=0.5,
    )
    defaults.update(overrides)
    return CallReview(**defaults)


def _analyze_with_mock(mocker, raw: str, track_record=()):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_response(raw)
    mocker.patch("anthropic.Anthropic", return_value=mock_client)
    mocker.patch("agent.trends.analyzer.TokenBucketLimiter.acquire")

    analyzer = _make_analyzer()
    report = analyzer.analyze(_make_brief(), macro=None, track_record=track_record)
    return report, mock_client


class TestParseResponse:
    def test_well_formed_response_parses_into_sections(self, mocker):
        raw = (
            "---RISKS---\n"
            "HEADLINE: Export controls tighten on Nvidia\n"
            "CONFIDENCE: HIGH\n"
            "ENTITIES: Nvidia\n"
            "BODY: New restrictions could cut into data center revenue.\n"
            "---OPPORTUNITIES---\n"
            "HEADLINE: Data center demand still climbing\n"
            "CONFIDENCE: MEDIUM\n"
            "ENTITIES: Nvidia\n"
            "BODY: Hyperscaler capex guidance remains strong.\n"
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(raw)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("agent.trends.analyzer.TokenBucketLimiter.acquire")

        analyzer = _make_analyzer()
        report = analyzer.analyze(_make_brief(), macro=None)

        assert len(report.risks) == 1
        assert report.risks[0].headline == "Export controls tighten on Nvidia"
        assert report.risks[0].confidence == "HIGH"
        assert len(report.opportunities) == 1
        assert report.opportunities[0].confidence == "MEDIUM"
        assert report.emerging == ()
        assert report.fading == ()
        assert report.watch == ()
        assert report.divergences == ()

    def test_item_naming_absent_entity_is_dropped(self, mocker):
        raw = (
            "---RISKS---\n"
            "HEADLINE: Fabricated risk\n"
            "CONFIDENCE: HIGH\n"
            "ENTITIES: Ghost Corp\n"
            "BODY: This entity was never in the brief.\n"
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(raw)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("agent.trends.analyzer.TokenBucketLimiter.acquire")

        analyzer = _make_analyzer()
        report = analyzer.analyze(_make_brief(), macro=None)

        assert report.risks == ()

    def test_evidence_free_high_confidence_downgraded_to_medium(self, mocker):
        raw = (
            "---WATCH---\n"
            "HEADLINE: General market commentary\n"
            "CONFIDENCE: HIGH\n"
            "ENTITIES: \n"
            "BODY: Broad observation with no specific entity backing.\n"
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response(raw)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("agent.trends.analyzer.TokenBucketLimiter.acquire")

        analyzer = _make_analyzer()
        report = analyzer.analyze(_make_brief(), macro=None)

        assert len(report.watch) == 1
        assert report.watch[0].confidence == "MEDIUM"


class TestTrackRecordCommentary:
    def test_prompt_contains_track_record_block_only_when_supplied(self, mocker):
        _, mock_client = _analyze_with_mock(mocker, "---RISKS---\n", track_record=(_make_review(),))
        system_prompt = mock_client.messages.create.call_args.kwargs["system"]
        assert "TRACK RECORD" in system_prompt
        assert "CALL_ID 17" in system_prompt

        _, mock_client_empty = _analyze_with_mock(mocker, "---RISKS---\n")
        system_prompt_empty = mock_client_empty.messages.create.call_args.kwargs["system"]
        assert "TRACK RECORD" not in system_prompt_empty

    def test_commentary_attached_to_right_review(self, mocker):
        raw = (
            "---RISKS---\n"
            "---TRACK RECORD---\n"
            "CALL_ID: 17\n"
            "BODY: The call played out — price and coverage both confirm it.\n"
            "CALL_ID: 18\n"
            "BODY: Too early to tell; evidence is flat.\n"
        )
        report, _ = _analyze_with_mock(
            mocker, raw, track_record=(_make_review(17), _make_review(18))
        )

        by_id = {r.call_id: r for r in report.track_record}
        assert by_id[17].commentary == "The call played out — price and coverage both confirm it."
        assert by_id[18].commentary == "Too early to tell; evidence is flat."

    def test_unknown_id_dropped(self, mocker):
        raw = (
            "---RISKS---\n"
            "---TRACK RECORD---\n"
            "CALL_ID: 999\n"
            "BODY: Fabricated commentary.\n"
        )
        report, _ = _analyze_with_mock(mocker, raw, track_record=(_make_review(17),))

        assert len(report.track_record) == 1
        assert report.track_record[0].commentary == ""

    def test_missing_section_leaves_commentary_empty(self, mocker):
        report, _ = _analyze_with_mock(mocker, "---RISKS---\n", track_record=(_make_review(),))

        assert report.track_record[0].commentary == ""

    def test_exhaustion_passes_reviews_through(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError.__new__(anthropic.APIError)
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")
        mocker.patch("agent.trends.analyzer.TokenBucketLimiter.acquire")

        analyzer = _make_analyzer()
        reviews = (_make_review(),)
        report = analyzer.analyze(_make_brief(), macro=None, track_record=reviews)

        assert report.track_record == reviews


class TestAnalyzeRetryAndDegradation:
    def test_three_consecutive_api_errors_returns_empty_report(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError.__new__(
            anthropic.APIError
        )
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")
        mocker.patch("agent.trends.analyzer.TokenBucketLimiter.acquire")

        analyzer = _make_analyzer()
        brief = _make_brief()
        report = analyzer.analyze(brief, macro=None)

        assert mock_client.messages.create.call_count == 3
        assert report.risks == ()
        assert report.opportunities == ()
        assert report.emerging == ()
        assert report.fading == ()
        assert report.watch == ()
        assert report.divergences == ()
        assert report.is_cold_start == brief.is_cold_start
        assert report.observation_count == brief.total_observations

    def test_macro_passed_through_unchanged_on_exhaustion(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError.__new__(
            anthropic.APIError
        )
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")
        mocker.patch("agent.trends.analyzer.TokenBucketLimiter.acquire")

        macro = MagicMock()
        analyzer = _make_analyzer()
        report = analyzer.analyze(_make_brief(), macro=macro)

        assert report.macro is macro

    def test_rate_limiter_acquired_before_every_attempt(self, mocker):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError.__new__(
            anthropic.APIError
        )
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("time.sleep")
        acquire_mock = mocker.patch("agent.trends.analyzer.TokenBucketLimiter.acquire")

        analyzer = _make_analyzer()
        analyzer.analyze(_make_brief(), macro=None)

        assert acquire_mock.call_count == 3
