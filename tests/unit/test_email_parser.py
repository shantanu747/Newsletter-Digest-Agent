"""Unit tests for EmailParser.

Covers:
- parse_pass_through(): preserves headings/bullets, truncates at 500 words,
  appends "Read original" link when truncated, leaves short content untouched.
- parse(): sets is_pass_through correctly based on SenderConfig.mode.
- _classify_image(): 6-layer heuristic stack (layers tested individually).
"""

from datetime import datetime, timezone

import pytest
from bs4 import BeautifulSoup

from agent.parsers.email_parser import EmailParser
from agent.utils.models import Email, SenderConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email(raw_html: str = "", plain_text: str | None = None, msg_id: str = "msg-001") -> Email:
    return Email(
        id=msg_id,
        source="gmail",
        sender="newsletter@example.com",
        subject="Test Subject",
        received_at=datetime(2026, 3, 19, 7, 0, 0, tzinfo=timezone.utc),
        raw_html=raw_html,
        plain_text=plain_text,
    )


def _make_sender(mode: str = "summarize") -> SenderConfig:
    return SenderConfig(address="newsletter@example.com", mode=mode)


def _make_img_tag(src: str, width: str = "", height: str = "",
                  classes: list[str] | None = None, alt: str = "",
                  img_id: str = "", parent_tag: str = "div") -> tuple:
    """Return (img_tag, soup) for use in _classify_image tests."""
    classes_attr = f'class="{" ".join(classes)}"' if classes else ""
    id_attr = f'id="{img_id}"' if img_id else ""
    width_attr = f'width="{width}"' if width else ""
    height_attr = f'height="{height}"' if height else ""
    alt_attr = f'alt="{alt}"' if alt else ""
    html = (
        f"<{parent_tag}>"
        f'<img src="{src}" {width_attr} {height_attr} {classes_attr} {id_attr} {alt_attr}>'
        f"</{parent_tag}>"
    )
    soup = BeautifulSoup(html, "html.parser")
    img_tag = soup.find("img")
    return img_tag, soup


# ---------------------------------------------------------------------------
# parse_pass_through()
# ---------------------------------------------------------------------------

class TestParsePassThrough:
    """Tests for parse_pass_through() content preservation and truncation."""

    def test_preserves_heading_structure(self):
        """Headings in HTML are preserved as Markdown-style headings in output."""
        parser = EmailParser()
        html = "<html><body><h1>Top Stories</h1><p>Content here.</p></body></html>"
        result = parser.parse_pass_through(html)
        assert "Top Stories" in result

    def test_preserves_bullet_list(self):
        """Unordered list items are preserved in the output."""
        parser = EmailParser()
        html = "<ul><li>Item one</li><li>Item two</li></ul>"
        result = parser.parse_pass_through(html)
        assert "Item one" in result
        assert "Item two" in result

    def test_preserves_numbered_list(self):
        """Ordered list items are preserved in the output."""
        parser = EmailParser()
        html = "<ol><li>First</li><li>Second</li></ol>"
        result = parser.parse_pass_through(html)
        assert "First" in result
        assert "Second" in result

    def test_short_content_not_truncated(self):
        """Content under 500 words is returned without a 'Read original' suffix."""
        parser = EmailParser()
        html = "<p>Short content here.</p>"
        result = parser.parse_pass_through(html)
        assert "Read original" not in result

    def test_long_content_truncated_at_500_words(self):
        """Content over 500 words is truncated near the 500-word boundary."""
        parser = EmailParser()
        # 600 words of text
        long_text = " ".join([f"word{i}" for i in range(600)])
        html = f"<p>{long_text}</p>"
        result = parser.parse_pass_through(html)
        result_words = result.split()
        # Should be truncated — significantly fewer than 600 words
        assert len(result_words) <= 520  # allow some slack for "Read original →"

    def test_read_original_appended_when_truncated(self):
        """'Read original →' is appended when content exceeds 500 words."""
        parser = EmailParser()
        long_text = " ".join([f"word{i}." for i in range(600)])
        html = f"<p>{long_text}</p>"
        result = parser.parse_pass_through(html)
        assert "Read original →" in result

    def test_no_read_original_when_not_truncated(self):
        """'Read original →' is NOT appended when content is under 500 words."""
        parser = EmailParser()
        html = "<p>This is short. Just a few sentences here.</p>"
        result = parser.parse_pass_through(html)
        assert "Read original →" not in result

    def test_truncation_at_sentence_boundary(self):
        """Truncation occurs at a sentence boundary (period), not mid-word."""
        parser = EmailParser()
        # Build exactly 510 words, each word followed by a period to create sentences
        sentences = [f"Sentence{i} ends." for i in range(102)]  # ~3 words each = 306 words
        # Make it longer: use longer sentences
        sentences = [f"This is sentence number {i} and it has exactly eight words." for i in range(65)]
        html = "<p>" + " ".join(sentences) + "</p>"
        result = parser.parse_pass_through(html)
        # Result should end with a period (sentence boundary) or "Read original →"
        stripped = result.replace("\n\nRead original →", "")
        assert stripped.strip().endswith(".")


# ---------------------------------------------------------------------------
# parse() — is_pass_through propagation
# ---------------------------------------------------------------------------

class TestParseIsPassThrough:
    """Tests for parse() setting is_pass_through on the returned Email."""

    def test_pass_through_mode_sets_flag(self):
        """Email.is_pass_through is True when SenderConfig.mode == 'pass_through'."""
        parser = EmailParser()
        em = _make_email(raw_html="<p>Content.</p>")
        sender_cfg = _make_sender(mode="pass_through")
        result = parser.parse(em, sender_config=sender_cfg)
        assert result.is_pass_through is True

    def test_summarize_mode_clears_flag(self):
        """Email.is_pass_through is False when SenderConfig.mode == 'summarize'."""
        parser = EmailParser()
        em = _make_email(raw_html="<p>Content.</p>")
        sender_cfg = _make_sender(mode="summarize")
        result = parser.parse(em, sender_config=sender_cfg)
        assert result.is_pass_through is False

    def test_no_sender_config_clears_flag(self):
        """Email.is_pass_through is False when no SenderConfig is provided."""
        parser = EmailParser()
        em = _make_email(raw_html="<p>Content.</p>")
        result = parser.parse(em, sender_config=None)
        assert result.is_pass_through is False

    def test_gmail_message_id_propagated(self):
        """gmail_message_id from input Email is preserved in parsed output."""
        parser = EmailParser()
        em = Email(
            id="msg-xyz",
            source="gmail",
            sender="newsletter@example.com",
            subject="Test",
            received_at=datetime(2026, 3, 19, tzinfo=timezone.utc),
            raw_html="<p>Content.</p>",
            gmail_message_id="gmail-id-123",
        )
        result = parser.parse(em)
        assert result.gmail_message_id == "gmail-id-123"

    def test_standard_parse_path_unchanged(self):
        """Standard (summarize) parse path still populates plain_text."""
        parser = EmailParser()
        em = _make_email(raw_html="<html><body><h1>News</h1><p>Body text here.</p></body></html>")
        result = parser.parse(em)
        assert result.plain_text is not None
        assert len(result.plain_text) > 0


# ---------------------------------------------------------------------------
# _classify_image() — layer-by-layer tests
# ---------------------------------------------------------------------------

class TestClassifyImage:
    """Tests for _classify_image() heuristic signal stack."""

    def test_tracking_domain_excluded(self):
        """Images from known tracking domains are excluded (Layer 1)."""
        parser = EmailParser()
        img, soup = _make_img_tag("https://sli.bloomberg.com/track.gif")
        assert parser._classify_image(img, soup) is False

    def test_tracking_pixel_excluded(self):
        """1x1 pixel images are excluded (Layer 2)."""
        parser = EmailParser()
        img, soup = _make_img_tag("https://example.com/pixel.gif", width="1", height="1")
        assert parser._classify_image(img, soup) is False

    def test_banner_class_excluded(self):
        """Images with 'banner' in CSS class are excluded (Layer 3)."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://example.com/banner.jpg",
            width="600", height="100",
            classes=["email-banner"],
        )
        assert parser._classify_image(img, soup) is False

    def test_logo_class_excluded(self):
        """Images with 'logo' in CSS class are excluded (Layer 3)."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://example.com/logo.png",
            width="200", height="200",
            classes=["company-logo"],
        )
        assert parser._classify_image(img, soup) is False

    def test_social_icon_excluded_by_class(self):
        """Images with 'social' in CSS class are excluded (Layer 3)."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://example.com/twitter.png",
            width="24", height="24",
            classes=["social-icon"],
        )
        assert parser._classify_image(img, soup) is False

    def test_parent_header_excluded(self):
        """Images inside a <header> element are excluded (Layer 4)."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://example.com/header-image.jpg",
            width="600", height="200",
            parent_tag="header",
        )
        assert parser._classify_image(img, soup) is False

    def test_logo_alt_excluded(self):
        """Images with 'logo' in alt text are excluded (Layer 5 exclusion)."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://example.com/image.png",
            width="200", height="200",
            alt="Company logo",
        )
        assert parser._classify_image(img, soup) is False

    def test_chart_alt_included(self):
        """Images with 'chart' in alt text are included (Layer 5 inclusion)."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://example.com/chart.png",
            width="400", height="300",
            alt="Revenue chart Q1",
        )
        assert parser._classify_image(img, soup) is True

    def test_small_square_excluded(self):
        """Small (< 100px) near-square images from non-CDN are excluded (Layer 6)."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://example.com/icon.png",
            width="48", height="50",
        )
        assert parser._classify_image(img, soup) is False

    def test_trusted_cdn_included(self):
        """Images from trusted CDN domains in a content parent are included."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://media.beehiiv.com/content/chart-q1.png",
            width="600", height="400",
            parent_tag="p",
        )
        assert parser._classify_image(img, soup) is True

    def test_default_exclude_for_ambiguous_image(self):
        """Ambiguous images (no signals match) are excluded by default."""
        parser = EmailParser()
        img, soup = _make_img_tag(
            "https://example.com/unknown.jpg",
            # No width, no height, no alt, non-CDN domain
        )
        assert parser._classify_image(img, soup) is False

    def test_non_https_excluded(self):
        """Non-HTTPS image URLs are excluded before any other check."""
        parser = EmailParser()
        img, soup = _make_img_tag("http://example.com/image.jpg")
        assert parser._classify_image(img, soup) is False
