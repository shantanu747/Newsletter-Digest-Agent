"""HTML-to-plaintext parser for newsletter emails.

Removes boilerplate markup (footers, nav bars, tracking pixels, unsubscribe
blocks) and converts the remaining HTML to clean plaintext using html2text.
Also extracts article links (for a "Further Reading" section) and content
image URLs (for inline rendering in the digest).
The plaintext output is truncated to 8 000 characters at the last sentence
boundary so downstream LLM calls stay within context limits.
"""

from __future__ import annotations

import dataclasses
import re

import html2text
from bs4 import BeautifulSoup, Tag

from agent.utils.logger import get_logger
from agent.utils.models import Email, EmailLink

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Boilerplate detection
# ---------------------------------------------------------------------------

# Class / ID substrings that indicate boilerplate blocks (case-insensitive).
_BOILERPLATE_SUBSTRINGS: tuple[str, ...] = (
    "unsubscribe",
    "footer",
    "header",
    "preheader",
    "social",   # social sharing sections (Beehiiv, Substack)
    "share",    # "share this email" divs
)

# ---------------------------------------------------------------------------
# Link filtering
# ---------------------------------------------------------------------------

# Anchor text substrings that mark non-article links (case-insensitive).
_LINK_DISCARD_TEXT: tuple[str, ...] = (
    "unsubscribe",
    "read online",
    "read in browser",
    "view online",
    "view in browser",
    "sign up",
    "advertise",
    "forward",
    "manage",
    "terms of service",
    "privacy policy",
    "contact us",
    "email preferences",
    "update your email",
    "click here",
    "learn more",
)

# URL substrings that mark non-article links.
_LINK_DISCARD_URL: tuple[str, ...] = (
    "unsubscribe",
    "mailto:",
    "manage-preferences",
    "/account/",
    "/settings/",
)

_MAX_LINKS = 20
_MAX_TITLE_CHARS = 60
_MAX_CONTEXT_CHARS = 120

# ---------------------------------------------------------------------------
# Image filtering
# ---------------------------------------------------------------------------

# Tracking / redirect domains whose images should be excluded entirely.
_TRACKING_IMG_DOMAINS: tuple[str, ...] = (
    "sli.bloomberg.com",
    "link.mail.beehiiv.com",
    "eotrx.substackcdn.com",
    "post.spmailtechnolo.com",
    "links.message.bloomberg.com",
    "email.mg-d0.substack.com",
)

# Trusted content CDN domains — any image from these passes the content check.
_CONTENT_IMG_DOMAINS: tuple[str, ...] = (
    "assets.bwbx.io",
    "media.beehiiv.com",
    "substackcdn.com",
)

_MAX_IMAGES = 10
_MIN_CONTENT_WIDTH = 50  # px — images smaller than this from non-CDN domains are ignored

_MAX_CHARS = 8_000


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class EmailParser:
    """Convert an Email's raw HTML body into clean plaintext.

    Also extracts article links and content image URLs, populating
    Email.links and Email.images on the returned instance.

    All methods are stateless; a single instance can be reused across many
    emails without side effects.
    """

    # ---------------------------------------------------------------------- #
    # Public API                                                               #
    # ---------------------------------------------------------------------- #

    def parse(self, email: Email) -> Email:
        """Return a new Email with plain_text, links, and images populated.

        Never raises — on any unexpected error it logs a warning and returns
        the best result obtained so far (with empty links/images tuples).
        """
        # 1. Fast path: no HTML to parse
        if not email.raw_html or not email.raw_html.strip():
            fallback = email.plain_text if email.plain_text is not None else ""
            return dataclasses.replace(email, plain_text=fallback, links=(), images=())

        try:
            # 2. Parse HTML
            soup = BeautifulSoup(email.raw_html, "html.parser")

            # 3. Remove hidden preheader/preview divs (display:none / max-height:0)
            self._remove_hidden_divs(soup)

            # 4. Extract links BEFORE boilerplate removal (so footer links are visible
            #    to the filter and correctly excluded)
            links = self._extract_links(soup)

            # 5. Extract images BEFORE boilerplate removal
            images = self._extract_images(soup)

            # 6. Remove boilerplate elements
            self._remove_boilerplate(soup)

            # 7. Remove 1×1 tracking pixels (already excluded from images tuple;
            #    this strips them from the soup before text conversion)
            for img in soup.find_all("img"):
                width = img.get("width", "")
                height = img.get("height", "")
                if str(width) == "1" and str(height) == "1":
                    img.decompose()

            # 8. Convert to plaintext
            h = html2text.HTML2Text()
            h.ignore_links = False
            h.body_width = 0
            plain: str = h.handle(str(soup))

        except Exception as exc:  # noqa: BLE001
            log.warning("email_parse_error", message_id=email.id, error=str(exc))
            fallback = email.plain_text if email.plain_text is not None else ""
            return dataclasses.replace(email, plain_text=fallback, links=(), images=())

        # 9. Truncate at last sentence boundary within 8 000 chars
        result = plain
        if len(plain) > _MAX_CHARS:
            boundary = plain.rfind(".", 0, _MAX_CHARS)
            result = plain[: boundary + 1] if boundary != -1 else plain[:_MAX_CHARS]
            log.debug(
                "content_truncated",
                message_id=email.id,
                original_len=len(plain),
                truncated_len=len(result),
            )

        # 10. Return new frozen dataclass instance
        return dataclasses.replace(
            email,
            plain_text=result.strip(),
            links=links,
            images=images,
        )

    # ---------------------------------------------------------------------- #
    # Private helpers                                                           #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _remove_hidden_divs(soup: BeautifulSoup) -> None:
        """Remove elements hidden via inline CSS (preheader / preview text)."""
        for tag in soup.find_all(style=True):
            style = (tag.get("style") or "").lower().replace(" ", "")
            if "display:none" in style or (
                "max-height:0" in style and "overflow:hidden" in style
            ):
                tag.decompose()

    @staticmethod
    def _remove_boilerplate(soup: BeautifulSoup) -> None:
        """Remove structural boilerplate: footer, nav, class/id keyword matches."""
        for tag_name in ("footer", "nav"):
            for tag in soup.find_all(tag_name):
                tag.decompose()

        for element in soup.find_all(class_=True):
            classes_str = " ".join(element.get("class", [])).lower()
            if any(sub in classes_str for sub in _BOILERPLATE_SUBSTRINGS):
                element.decompose()

        for element in soup.find_all(id=True):
            element_id = (element.get("id") or "").lower()
            if any(sub in element_id for sub in _BOILERPLATE_SUBSTRINGS):
                element.decompose()

    @staticmethod
    def _extract_links(soup: BeautifulSoup) -> tuple[EmailLink, ...]:
        """Extract article links from the soup, filtering boilerplate URLs."""
        seen_urls: set[str] = set()
        results: list[EmailLink] = []

        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag.get("href", "").strip()

            # Must be HTTPS
            if not href.startswith("https://"):
                continue

            # URL-level discard
            href_lower = href.lower()
            if any(bad in href_lower for bad in _LINK_DISCARD_URL):
                continue

            # Anchor text
            anchor_text = a_tag.get_text(separator=" ").strip()
            if len(anchor_text) < 4:
                continue

            anchor_lower = anchor_text.lower()
            if any(bad in anchor_lower for bad in _LINK_DISCARD_TEXT):
                continue

            # Deduplicate
            if href in seen_urls:
                continue
            seen_urls.add(href)

            # Build title (truncate long anchor text)
            title = anchor_text
            if len(title) > _MAX_TITLE_CHARS:
                title = title[:_MAX_TITLE_CHARS].rstrip() + "…"

            # Context: try parent element's text
            parent = a_tag.parent
            if isinstance(parent, Tag):
                ctx = parent.get_text(separator=" ").strip()
                # Walk up one more level if context == anchor text
                if ctx == anchor_text and isinstance(parent.parent, Tag):
                    ctx = parent.parent.get_text(separator=" ").strip()
            else:
                ctx = ""

            # Collapse whitespace and truncate
            ctx = re.sub(r"\s+", " ", ctx)
            if len(ctx) > _MAX_CONTEXT_CHARS:
                ctx = ctx[:_MAX_CONTEXT_CHARS].rstrip() + "…"

            results.append(EmailLink(url=href, title=title, context=ctx))

            if len(results) >= _MAX_LINKS:
                break

        return tuple(results)

    @staticmethod
    def _extract_images(soup: BeautifulSoup) -> tuple[str, ...]:
        """Extract content image URLs, filtering tracking pixels and tracking domains."""
        seen_urls: set[str] = set()
        results: list[str] = []

        for img in soup.find_all("img", src=True):
            src: str = img.get("src", "").strip()

            # Must be HTTPS (excludes data: URIs and relative paths)
            if not src.startswith("https://"):
                continue

            # Skip 1×1 tracking pixels
            width_str = str(img.get("width", ""))
            height_str = str(img.get("height", ""))
            if width_str == "1" and height_str == "1":
                continue

            # Skip known tracking domains
            src_lower = src.lower()
            if any(domain in src_lower for domain in _TRACKING_IMG_DOMAINS):
                continue

            # Must be from a trusted content CDN OR have a parseable width ≥ MIN
            from_content_cdn = any(cdn in src_lower for cdn in _CONTENT_IMG_DOMAINS)
            if not from_content_cdn:
                try:
                    w = int(re.sub(r"[^0-9]", "", width_str))
                    if w < _MIN_CONTENT_WIDTH:
                        continue
                except (ValueError, TypeError):
                    continue  # no width attr and not a known CDN → skip

            # Deduplicate
            if src in seen_urls:
                continue
            seen_urls.add(src)

            results.append(src)

            if len(results) >= _MAX_IMAGES:
                break

        return tuple(results)
