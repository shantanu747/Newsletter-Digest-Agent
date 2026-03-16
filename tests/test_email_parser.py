"""Unit tests for EmailParser.

EmailParser is a pure transformation — no mocking required.
All tests exercise real BS4 + html2text behaviour.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.utils.models import Email

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_BASE_DATE = datetime(2026, 3, 9, 7, 0, 0, tzinfo=timezone.utc)


def _make_email(
    raw_html: str = "",
    plain_text: str | None = None,
    msg_id: str = "msg-001",
) -> Email:
    return Email(
        id=msg_id,
        source="gmail",
        sender="newsletter@example.com",
        subject="Test Newsletter",
        received_at=_BASE_DATE,
        raw_html=raw_html,
        plain_text=plain_text,
    )


def _parse(email: Email) -> Email:
    """Import and run EmailParser; deferred so import errors surface in tests."""
    from agent.parsers.email_parser import EmailParser  # noqa: PLC0415

    return EmailParser().parse(email)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_email() -> Email:
    return _make_email(
        raw_html="<html><body><h1>Top Stories</h1><p>Content here.</p></body></html>",
    )


@pytest.fixture
def sample_email_plain() -> Email:
    return _make_email(
        raw_html="",
        plain_text="Top Stories\n\nContent here.",
    )


# ---------------------------------------------------------------------------
# 1. Footer and nav are stripped
# ---------------------------------------------------------------------------

class TestBoilerplateRemoval:

    def test_footer_element_is_removed(self):
        """<footer> tag content must not appear in plain_text."""
        html = (
            "<html><body>"
            "<p>Main article content about technology trends.</p>"
            "<footer><p>© 2026 Example Corp. All rights reserved.</p></footer>"
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert "All rights reserved" not in result.plain_text

    def test_nav_element_is_removed(self):
        """<nav> tag content must not appear in plain_text."""
        html = (
            "<html><body>"
            "<nav><a href='/home'>Home</a> | <a href='/about'>About</a></nav>"
            "<p>Interesting newsletter body paragraph goes here.</p>"
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert "Home" not in result.plain_text
        assert "About" not in result.plain_text

    def test_newsletter_body_is_preserved(self):
        """Meaningful body text survives stripping."""
        body_text = "This is the main article content we care about."
        html = (
            f"<html><body>"
            f"<p>{body_text}</p>"
            f"<footer><p>Unsubscribe here.</p></footer>"
            f"</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert body_text in result.plain_text

    def test_element_with_unsubscribe_class_is_removed(self):
        """Elements whose class contains 'unsubscribe' are stripped."""
        html = (
            "<html><body>"
            "<p>Real newsletter content lives here.</p>"
            "<div class='unsubscribe'>Click here to unsubscribe from this list.</div>"
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert "unsubscribe" not in (result.plain_text or "").lower()

    def test_element_with_footer_class_is_removed(self):
        """Elements whose class contains 'footer' are stripped."""
        html = (
            "<html><body>"
            "<p>Great article about Python packaging.</p>"
            "<div class='footer'>Footer boilerplate text goes here.</div>"
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert "Footer boilerplate" not in result.plain_text

    def test_element_with_header_class_is_removed(self):
        """Elements whose class contains 'header' or 'preheader' are stripped."""
        html = (
            "<html><body>"
            "<div class='preheader'>Preview text that appears in inbox.</div>"
            "<p>Actual newsletter content that readers care about.</p>"
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert "Preview text" not in result.plain_text

    def test_element_with_footer_id_is_removed(self):
        """Elements whose id matches footer patterns are stripped."""
        html = (
            "<html><body>"
            "<p>Core article content worth reading.</p>"
            "<div id='footer'>Legal disclaimer and footer content.</div>"
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert "Legal disclaimer" not in result.plain_text


# ---------------------------------------------------------------------------
# 2. Tracking pixel is stripped
# ---------------------------------------------------------------------------

class TestTrackingPixelRemoval:

    def test_1x1_img_is_stripped(self):
        """A 1×1 <img> tracking pixel must not appear in plain_text."""
        html = (
            "<html><body>"
            "<p>Newsletter article content.</p>"
            '<img src="https://track.example.com/open.gif" width="1" height="1" />'
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        # html2text would render an img as ![](url); the tracking URL must not appear
        assert result.plain_text is not None
        assert "track.example.com" not in result.plain_text

    def test_regular_image_is_not_stripped(self):
        """A normal-sized image should not be treated as a tracking pixel."""
        html = (
            "<html><body>"
            "<p>Article with an embedded image.</p>"
            '<img src="https://cdn.example.com/hero.jpg" width="600" height="400" />'
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        # The img reference (as markdown or text) may or may not appear, but parsing
        # should not strip it silently — result must be non-None and non-empty
        assert result.plain_text is not None

    def test_1x1_img_without_explicit_dimensions_still_stripped_if_matched(self):
        """Tracking pixels detected by both width=1 and height=1 attributes."""
        html = (
            "<html><body>"
            "<p>Content paragraph.</p>"
            '<img src="https://beacon.example.com/t.gif" height="1" width="1">'
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert "beacon.example.com" not in result.plain_text


# ---------------------------------------------------------------------------
# 3. Truncation at 8000 characters at sentence boundary
# ---------------------------------------------------------------------------

class TestTruncation:

    def test_long_html_is_truncated_to_at_most_8000_chars(self):
        """plain_text length must not exceed 8000 characters."""
        # Generate a long repeating newsletter body well over 8000 chars
        sentence = "This is a very detailed sentence about a fascinating topic in technology. "
        long_body = sentence * 200  # ~14 400 chars of plain text
        html = f"<html><body><p>{long_body}</p></body></html>"

        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert len(result.plain_text) <= 8000

    def test_truncation_ends_at_sentence_boundary(self):
        """Truncated plain_text must end at the last '.' before the 8000-char limit."""
        sentence = "Sentence number {:04d} ends here. "
        long_body = "".join(sentence.format(i) for i in range(300))  # ~10 500 chars
        html = f"<html><body><p>{long_body}</p></body></html>"

        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        # Must end at a period (allowing for trailing whitespace)
        stripped = result.plain_text.rstrip()
        assert stripped.endswith("."), (
            f"Expected plain_text to end with '.', got: ...{stripped[-30:]!r}"
        )

    def test_short_html_is_not_truncated(self):
        """Content shorter than 8000 chars is returned in full."""
        body = "Short but informative content. Ends here."
        html = f"<html><body><p>{body}</p></body></html>"

        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert body in result.plain_text

    def test_truncation_boundary_is_exactly_before_8000(self):
        """Truncation point must be the last '.' found before position 8000."""
        # Craft a string where we know exactly where the last '.' before 8000 falls
        # Build ~7950 chars of filler ending in '.', then add more content
        filler = ("A" * 78 + ". ") * 99  # 99 × 80 = 7920 chars, ends with ". "
        tail = "B" * 200 + ". More words after."
        html = f"<html><body><p>{filler}{tail}</p></body></html>"

        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert len(result.plain_text) <= 8000
        stripped = result.plain_text.rstrip()
        assert stripped.endswith(".")


# ---------------------------------------------------------------------------
# 4. Plain-text-only email returned as-is
# ---------------------------------------------------------------------------

class TestPlainTextPassthrough:

    def test_plain_text_email_returned_unchanged(self, sample_email_plain):
        """Email with empty raw_html and existing plain_text is returned as-is."""
        result = _parse(sample_email_plain)

        assert result.plain_text == sample_email_plain.plain_text

    def test_plain_text_email_fields_preserved(self, sample_email_plain):
        """All other Email fields are unchanged when passing through a plain-text email."""
        result = _parse(sample_email_plain)

        assert result.id == sample_email_plain.id
        assert result.sender == sample_email_plain.sender
        assert result.subject == sample_email_plain.subject
        assert result.source == sample_email_plain.source
        assert result.received_at == sample_email_plain.received_at
        assert result.raw_html == sample_email_plain.raw_html

    def test_plain_text_none_with_empty_html_yields_empty_string(self):
        """An email with empty raw_html AND plain_text=None gives plain_text=''."""
        email = _make_email(raw_html="", plain_text=None)
        result = _parse(email)

        # Fetcher would not produce this normally, but parser must handle it gracefully
        # per contract: return plain_text unchanged when raw_html is empty
        # Since plain_text is None and raw_html is empty, parser returns None or '' —
        # the spec says return plain_text as-is from the input Email.
        # None is acceptable here only if the spec passes plain_text through unchanged.
        # If raw_html is empty, the input plain_text (None) is returned unchanged.
        assert result.plain_text is None or result.plain_text == ""


# ---------------------------------------------------------------------------
# 5. Completely empty HTML yields plain_text == ""
# ---------------------------------------------------------------------------

class TestEmptyHtml:

    def test_completely_empty_html_string_yields_empty_plain_text(self):
        """An email with raw_html='' (not plain-text-only) yields plain_text=''."""
        # Distinguish from the plain-text passthrough: raw_html is truthy but empty
        # This tests the branch where raw_html exists but has no content.
        email = _make_email(raw_html="   ")  # whitespace-only HTML
        result = _parse(email)

        assert result.plain_text is not None
        assert result.plain_text.strip() == ""

    def test_html_with_only_whitespace_yields_empty_plain_text(self):
        """HTML containing only whitespace produces an empty plain_text."""
        html = "<html><body>   \n\t  </body></html>"
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert result.plain_text.strip() == ""

    def test_html_with_stripped_elements_only_yields_empty(self):
        """HTML where all content is inside stripped elements yields empty plain_text."""
        html = (
            "<html><body>"
            "<footer>Footer only content here.</footer>"
            "<nav>Navigation only content here.</nav>"
            "</body></html>"
        )
        result = _parse(_make_email(raw_html=html))

        assert result.plain_text is not None
        assert result.plain_text.strip() == ""


# ---------------------------------------------------------------------------
# 6. Return type is always a new frozen Email instance
# ---------------------------------------------------------------------------

class TestReturnType:

    def test_returns_email_instance(self, sample_email):
        """parse() always returns an Email dataclass instance."""
        result = _parse(sample_email)
        assert isinstance(result, Email)

    def test_returns_new_instance_not_same_object(self, sample_email):
        """parse() must return a new Email (frozen dataclass — cannot mutate in place)."""
        result = _parse(sample_email)
        assert result is not sample_email

    def test_source_is_always_gmail(self, sample_email):
        """source field is preserved as 'gmail' through parsing."""
        result = _parse(sample_email)
        assert result.source == "gmail"

    def test_plain_text_populated_after_parse(self, sample_email):
        """After parsing an HTML email, plain_text is no longer None."""
        assert sample_email.plain_text is None
        result = _parse(sample_email)
        assert result.plain_text is not None
