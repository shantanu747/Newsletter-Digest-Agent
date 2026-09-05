"""Unit tests for agent.digest.builder.build_signals / templates/signals.html.j2 (T045).

Tests cover:
- A report with all sections empty and macro=None still renders valid HTML
- The cold-start banner appears only when report.is_cold_start
- The advice disclaimer is always present
- Confidence levels are rendered for every item
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent.digest.builder import build_signals
from agent.utils.models import MacroIndicator, MacroSnapshot, SignalItem, SignalsReport

_RUN_DATE = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _make_report(**overrides) -> SignalsReport:
    defaults = dict(
        generated_at=_RUN_DATE,
        window_days=7,
        macro=None,
        risks=(),
        opportunities=(),
        emerging=(),
        fading=(),
        watch=(),
        divergences=(),
        is_cold_start=False,
        observation_count=0,
    )
    defaults.update(overrides)
    return SignalsReport(**defaults)


def _make_item(**overrides) -> SignalItem:
    defaults = dict(
        headline="Nvidia export exposure grows",
        body="Tighter export rules could weigh on data center sales.",
        confidence="HIGH",
        entities=("Nvidia",),
    )
    defaults.update(overrides)
    return SignalItem(**defaults)


class TestEmptyReport:
    def test_all_sections_empty_and_macro_none_renders_valid_html(self):
        html = build_signals(_make_report(), _RUN_DATE)
        assert "<html" in html
        assert "</html>" in html
        assert "Signals Report" in html

    def test_empty_report_shows_no_signals_message(self):
        html = build_signals(_make_report(), _RUN_DATE)
        assert "No signals cleared the eligibility bar" in html


class TestColdStartBanner:
    def test_banner_present_when_cold_start(self):
        html = build_signals(_make_report(is_cold_start=True), _RUN_DATE)
        assert "Still building history" in html

    def test_banner_absent_when_not_cold_start(self):
        html = build_signals(_make_report(is_cold_start=False), _RUN_DATE)
        assert "Still building history" not in html


class TestDisclaimer:
    def test_disclaimer_present_on_empty_report(self):
        html = build_signals(_make_report(), _RUN_DATE)
        assert "not investment advice" in html

    def test_disclaimer_present_on_populated_report(self):
        report = _make_report(risks=(_make_item(),))
        html = build_signals(report, _RUN_DATE)
        assert "not investment advice" in html


class TestConfidenceRendering:
    def test_every_item_shows_confidence_level(self):
        report = _make_report(
            risks=(_make_item(confidence="HIGH"),),
            opportunities=(_make_item(confidence="MEDIUM", headline="Opportunity"),),
            watch=(_make_item(confidence="LOW", headline="Watch this"),),
        )
        html = build_signals(report, _RUN_DATE)
        assert "High Confidence" in html
        assert "Medium Confidence" in html
        assert "Low Confidence" in html

    def test_section_titles_present_only_when_populated(self):
        report = _make_report(risks=(_make_item(),))
        html = build_signals(report, _RUN_DATE)
        assert "Accelerating Risks" in html
        assert "Opportunities" not in html
        assert "Emerging Themes" not in html


class TestMacroDashboard:
    def test_macro_section_renders_indicators(self):
        macro = MacroSnapshot(
            indicators=(
                MacroIndicator(
                    series_id="T10Y3M",
                    label="10Y-3M Treasury Spread",
                    value=-0.4,
                    as_of="2026-09-01",
                    direction="falling",
                    alarm=True,
                    note="Inverted",
                ),
            ),
            fetched_at=_RUN_DATE,
            partial=False,
        )
        html = build_signals(_make_report(macro=macro), _RUN_DATE)
        assert "Macro Dashboard" in html
        assert "10Y-3M Treasury Spread" in html
        assert "Alarm" in html

    def test_macro_section_absent_when_none(self):
        html = build_signals(_make_report(macro=None), _RUN_DATE)
        assert "Macro Dashboard" not in html
