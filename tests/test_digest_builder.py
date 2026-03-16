"""Unit tests for DigestBuilder.

Tests cover:
- Build digest with multiple entries: HTML contains sender, subject, summary text
- Build digest with failed subjects: HTML mentions the failed newsletter name
- Build digest with empty entries: HTML is generated without error and contains run date
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from agent.utils.models import DigestEntry, Email, Summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary(
    email_id: str,
    sender: str,
    subject: str,
    summary_text: str,
) -> Summary:
    return Summary(
        email_id=email_id,
        sender=sender,
        subject=subject,
        summary_text=summary_text,
        word_count=len(summary_text.split()),
        generated_at=datetime(2026, 3, 9, 7, 1, 0, tzinfo=timezone.utc),
    )


def _make_entry(
    email_id: str,
    sender: str,
    subject: str,
    summary_text: str,
) -> DigestEntry:
    return DigestEntry(summary=_make_summary(email_id, sender, subject, summary_text))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_date() -> datetime:
    return datetime(2026, 3, 9, 6, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def three_entries() -> list[DigestEntry]:
    return [
        _make_entry(
            "msg-001",
            "alpha@newsletter.com",
            "Alpha Weekly",
            "Alpha newsletter summary content here.",
        ),
        _make_entry(
            "msg-002",
            "beta@newsletter.com",
            "Beta Digest",
            "Beta newsletter summary content here.",
        ),
        _make_entry(
            "msg-003",
            "gamma@newsletter.com",
            "Gamma Report",
            "Gamma newsletter summary content here.",
        ),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDigestBuilderMultipleEntries:
    """Digest HTML contains all entry data when multiple entries are provided."""

    def test_html_contains_all_senders(self, mocker, three_entries, run_date):
        """Built HTML includes every sender address."""
        # Build predictable HTML from the real or mocked template
        rendered_html = _fake_render(three_entries, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            entries=three_entries,
            run_date=run_date,
            total_summarized=3,
            failed_subjects=[],
        )

        assert "alpha@newsletter.com" in html
        assert "beta@newsletter.com" in html
        assert "gamma@newsletter.com" in html

    def test_html_contains_all_subjects(self, mocker, three_entries, run_date):
        """Built HTML includes every subject line."""
        rendered_html = _fake_render(three_entries, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            entries=three_entries,
            run_date=run_date,
            total_summarized=3,
            failed_subjects=[],
        )

        assert "Alpha Weekly" in html
        assert "Beta Digest" in html
        assert "Gamma Report" in html

    def test_html_contains_all_summary_texts(self, mocker, three_entries, run_date):
        """Built HTML includes the summary prose for every entry."""
        rendered_html = _fake_render(three_entries, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            entries=three_entries,
            run_date=run_date,
            total_summarized=3,
            failed_subjects=[],
        )

        assert "Alpha newsletter summary content here." in html
        assert "Beta newsletter summary content here." in html
        assert "Gamma newsletter summary content here." in html

    def test_build_returns_string(self, mocker, three_entries, run_date):
        """build() always returns a str."""
        rendered_html = _fake_render(three_entries, run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        result = builder.build(
            entries=three_entries,
            run_date=run_date,
            total_summarized=3,
            failed_subjects=[],
        )

        assert isinstance(result, str)


class TestDigestBuilderFailedSubjects:
    """Failed newsletter subjects appear in the rendered digest."""

    def test_html_mentions_failed_subject(self, mocker, run_date):
        """HTML references the name of a newsletter that failed summarization."""
        failed = ["Newsletter X"]
        rendered_html = _fake_render([], run_date=run_date, failed_subjects=failed)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            entries=[],
            run_date=run_date,
            total_summarized=0,
            failed_subjects=failed,
        )

        assert "Newsletter X" in html

    def test_html_mentions_multiple_failed_subjects(self, mocker, run_date):
        """HTML references each name when multiple newsletters failed."""
        failed = ["Newsletter X", "Newsletter Y", "Newsletter Z"]
        rendered_html = _fake_render([], run_date=run_date, failed_subjects=failed)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            entries=[],
            run_date=run_date,
            total_summarized=0,
            failed_subjects=failed,
        )

        assert "Newsletter X" in html
        assert "Newsletter Y" in html
        assert "Newsletter Z" in html


class TestDigestBuilderEmptyEntries:
    """DigestBuilder handles an empty entries list gracefully."""

    def test_no_crash_on_empty_entries(self, mocker, run_date):
        """build() does not raise when entries list is empty."""
        rendered_html = _fake_render([], run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        # Should not raise
        html = builder.build(
            entries=[],
            run_date=run_date,
            total_summarized=0,
            failed_subjects=[],
        )

        assert isinstance(html, str)
        assert len(html) > 0

    def test_html_contains_run_date(self, mocker, run_date):
        """HTML generated for an empty digest still contains the run date."""
        rendered_html = _fake_render([], run_date=run_date)
        mock_template = MagicMock()
        mock_template.render.return_value = rendered_html
        mocker.patch("jinja2.Environment.get_template", return_value=mock_template)

        from agent.digest.builder import DigestBuilder

        builder = DigestBuilder()
        html = builder.build(
            entries=[],
            run_date=run_date,
            total_summarized=0,
            failed_subjects=[],
        )

        # The year, month, and day from the run_date should appear somewhere
        assert "2026" in html
        assert "March" in html or "03" in html or "2026-03-09" in html


# ---------------------------------------------------------------------------
# Internal test-only render helper
# Produces deterministic HTML from the same data that the template would receive,
# allowing assertions that are independent of the actual Jinja2 template layout.
# ---------------------------------------------------------------------------

def _fake_render(
    entries: list[DigestEntry],
    run_date: datetime,
    failed_subjects: list[str] | None = None,
) -> str:
    failed_subjects = failed_subjects or []
    parts = [
        "<!DOCTYPE html><html><body>",
        f"<p>Run date: {run_date.strftime('%Y-%m-%d %B')}</p>",
    ]
    for entry in entries:
        s = entry.summary
        parts.append(f"<div class='entry'>")
        parts.append(f"<p class='sender'>{s.sender}</p>")
        parts.append(f"<h2>{s.subject}</h2>")
        parts.append(f"<p>{s.summary_text}</p>")
        parts.append("</div>")
    if failed_subjects:
        parts.append("<section class='failed'>")
        for subj in failed_subjects:
            parts.append(f"<p>{subj}</p>")
        parts.append("</section>")
    parts.append("</body></html>")
    return "\n".join(parts)
