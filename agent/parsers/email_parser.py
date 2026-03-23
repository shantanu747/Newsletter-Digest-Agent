"""HTML-to-plaintext parser for newsletter emails.

Removes boilerplate markup (footers, nav bars, tracking pixels, unsubscribe
blocks) and converts the remaining HTML to clean plaintext using html2text.
Also extracts article links (for a "Further Reading" section) and content
image URLs (for inline rendering in the digest).
The plaintext output is truncated to 8 000 characters at the last sentence
boundary so downstream LLM calls stay within context limits.

For pass_through senders, parse_pass_through() is used instead — it preserves
headings, bullets, and structure, and truncates at 500 words.
"""

from __future__ import annotations

import dataclasses
import re

import html2text
from bs4 import BeautifulSoup, Tag

from agent.utils.logger import get_logger
from agent.utils.models import Email, EmailLink, SenderConfig

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

_MAX_LINKS = 8
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

# Trusted content CDN domains — images from these are treated favorably.
_CONTENT_IMG_DOMAINS: tuple[str, ...] = (
    "assets.bwbx.io",
    "media.beehiiv.com",
    "substackcdn.com",
)

# CSS class / ID name substrings that indicate non-content images.
_IMAGE_EXCLUDE_CLASS_SUBSTRINGS: tuple[str, ...] = (
    "banner",
    "header",
    "logo",
    "icon",
    "social",
    "ad",
    "advertisement",
    "promo",
    "footer",
    "brand",
    "sponsor",
    "spacer",
    "separator",
    "divider",
    "avatar",
    "bullet",
    "rule",
)

# Alt text keywords that explicitly exclude an image.
_IMAGE_EXCLUDE_ALT_KEYWORDS: tuple[str, ...] = (
    "logo",
    "icon",
    "badge",
    "banner",
    "social",
    "avatar",
    "sponsored",
    "advertisement",
)

# Alt text keywords that explicitly include an image.
_IMAGE_INCLUDE_ALT_KEYWORDS: tuple[str, ...] = (
    "chart",
    "graph",
    "data",
    "visualization",
    "meme",
)

_MAX_IMAGES = 4
_MAX_CHARS = 8_000
_PASS_THROUGH_MAX_WORDS = 500


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

    def parse(self, email: Email, sender_config: SenderConfig | None = None) -> Email:
        """Return a new Email with plain_text, links, images, and is_pass_through populated.

        For pass_through senders, uses parse_pass_through() for content preservation.
        For summarize senders (default), uses the standard boilerplate-stripping pipeline.

        Never raises — on any unexpected error it logs a warning and returns
        the best result obtained so far (with empty links/images tuples).
        """
        is_pass_through = sender_config is not None and sender_config.mode == "pass_through"

        # 1. Fast path: no HTML to parse
        if not email.raw_html or not email.raw_html.strip():
            fallback = email.plain_text if email.plain_text is not None else ""
            return dataclasses.replace(
                email,
                plain_text=fallback,
                links=(),
                images=(),
                is_pass_through=is_pass_through,
                gmail_message_id=email.gmail_message_id or email.id,
            )

        try:
            # 2. Parse HTML
            soup = BeautifulSoup(email.raw_html, "html.parser")

            # 3. Remove hidden preheader/preview divs (display:none / max-height:0)
            self._remove_hidden_divs(soup)

            # 4. Extract links BEFORE boilerplate removal
            links = self._extract_links(soup)

            # 5. Extract images using classifier
            max_imgs = None
            include_imgs = True
            if sender_config is not None:
                include_imgs = sender_config.include_images
                max_imgs = sender_config.max_images

            images = self._extract_images(soup, max_images=max_imgs) if include_imgs else ()

            if is_pass_through:
                # Pass-through: preserve structure, truncate at 500 words
                plain = self.parse_pass_through(email.raw_html)
            else:
                # Standard pipeline: remove boilerplate, convert to plaintext
                # 6. Remove boilerplate elements
                self._remove_boilerplate(soup)

                # 7. Remove 1×1 tracking pixels
                for img in soup.find_all("img"):
                    if img.parent is None:
                        continue
                    width = img.get("width", "")
                    height = img.get("height", "")
                    if str(width) == "1" and str(height) == "1":
                        img.decompose()

                # 8. Convert to plaintext
                h = html2text.HTML2Text()
                h.ignore_links = False
                h.body_width = 0
                plain = h.handle(str(soup))

                # 9. Truncate at last sentence boundary within 8 000 chars
                if len(plain) > _MAX_CHARS:
                    boundary = plain.rfind(".", 0, _MAX_CHARS)
                    plain = plain[: boundary + 1] if boundary != -1 else plain[:_MAX_CHARS]
                    log.debug(
                        "content_truncated",
                        message_id=email.id,
                        truncated_len=len(plain),
                    )

        except Exception as exc:  # noqa: BLE001
            log.warning("email_parse_error", message_id=email.id, error=str(exc))
            fallback = email.plain_text if email.plain_text is not None else ""
            return dataclasses.replace(
                email,
                plain_text=fallback,
                links=(),
                images=(),
                is_pass_through=is_pass_through,
                gmail_message_id=email.gmail_message_id or email.id,
            )

        return dataclasses.replace(
            email,
            plain_text=plain.strip(),
            links=links,
            images=images,
            is_pass_through=is_pass_through,
            gmail_message_id=email.gmail_message_id or email.id,
        )

    def parse_pass_through(self, raw_html: str) -> str:
        """Convert pass-through HTML to structure-preserving plaintext.

        Applies lighter boilerplate removal (keeps headings, bullets, numbered
        lists), converts to plaintext via html2text with structure-preserving
        settings, and truncates at the nearest sentence boundary within 500 words.
        Appends a "Read original →" marker if truncation occurred.

        Args:
            raw_html: Raw HTML body of the email.

        Returns:
            Structure-preserving plaintext, truncated to ~500 words.
        """
        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove only hard boilerplate: hidden divs, tracking pixels
        self._remove_hidden_divs(soup)

        # Remove tracking pixels from pass-through content too
        for img in soup.find_all("img"):
            if img.parent is None:
                continue
            width = img.get("width", "")
            height = img.get("height", "")
            if str(width) == "1" and str(height) == "1":
                img.decompose()

        # Convert with structure-preserving settings
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.body_width = 0
        h.protect_links = True
        h.wrap_links = False
        text = h.handle(str(soup))

        # Count words and truncate at sentence boundary within 500 words
        words = text.split()
        if len(words) <= _PASS_THROUGH_MAX_WORDS:
            return text.strip()

        # Rebuild text up to word limit then find last sentence boundary
        truncated_words = words[:_PASS_THROUGH_MAX_WORDS]
        truncated = " ".join(truncated_words)

        boundary = truncated.rfind(".")
        if boundary != -1:
            truncated = truncated[: boundary + 1]
        # else keep the 500-word cut as-is

        return truncated.strip() + "\n\nRead original →"

    # ---------------------------------------------------------------------- #
    # Private helpers                                                           #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _remove_hidden_divs(soup: BeautifulSoup) -> None:
        """Remove elements hidden via inline CSS (preheader / preview text)."""
        for tag in soup.find_all(style=True):
            if tag.parent is None:  # already decomposed (child of an earlier removed parent)
                continue
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
            if element.parent is None:
                continue
            classes_str = " ".join(element.get("class", [])).lower()
            if any(sub in classes_str for sub in _BOILERPLATE_SUBSTRINGS):
                element.decompose()

        for element in soup.find_all(id=True):
            if element.parent is None:
                continue
            element_id = (element.get("id") or "").lower()
            if any(sub in element_id for sub in _BOILERPLATE_SUBSTRINGS):
                element.decompose()

    @staticmethod
    def _classify_image(img_tag: Tag, soup: BeautifulSoup) -> bool:
        """Classify an image tag and return True if it should be included.

        Implements a 6-layer heuristic priority stack (first exclusion match wins):
          Layer 1: Known tracking domain → exclude
          Layer 2: Tracking pixel (width ≤ 1, height ≤ 1) → exclude
          Layer 3: CSS class/id contains exclusion keywords → exclude
          Layer 4: Parent element is <header>, <footer>, <nav> → exclude
          Layer 5: Alt text keywords → exclude or include
          Layer 6: Width < 100px AND near-square AND not on trusted CDN → exclude
          Default: exclude (opt-in policy)

        Returns:
            True if the image should be included; False if excluded.
        """
        src: str = img_tag.get("src", "").strip()

        if not src.startswith("https://"):
            return False

        src_lower = src.lower()

        # Layer 1: Known tracking domain → exclude
        if any(domain in src_lower for domain in _TRACKING_IMG_DOMAINS):
            return False

        # Layer 2: Tracking pixel → exclude
        width_str = str(img_tag.get("width", ""))
        height_str = str(img_tag.get("height", ""))
        try:
            w = int(re.sub(r"[^0-9]", "", width_str)) if width_str else None
            h = int(re.sub(r"[^0-9]", "", height_str)) if height_str else None
        except (ValueError, TypeError):
            w = h = None

        if w is not None and h is not None and w <= 1 and h <= 1:
            return False

        # Layer 3: CSS class/id exclusion keywords → exclude
        classes_str = " ".join(img_tag.get("class", [])).lower()
        img_id = (img_tag.get("id") or "").lower()
        if any(kw in classes_str for kw in _IMAGE_EXCLUDE_CLASS_SUBSTRINGS):
            return False
        if any(kw in img_id for kw in _IMAGE_EXCLUDE_CLASS_SUBSTRINGS):
            return False

        # Layer 4: Parent element is <header>, <footer>, <nav> → exclude
        parent = img_tag.parent
        if isinstance(parent, Tag):
            parent_name = (parent.name or "").lower()
            if parent_name in ("header", "footer", "nav"):
                return False

        # Layer 5: Alt text keywords
        alt = (img_tag.get("alt") or "").lower()
        if any(kw in alt for kw in _IMAGE_EXCLUDE_ALT_KEYWORDS):
            return False
        if any(kw in alt for kw in _IMAGE_INCLUDE_ALT_KEYWORDS):
            return True

        # Trusted CDN: require a content-placement signal — don't auto-include
        from_trusted_cdn = any(cdn in src_lower for cdn in _CONTENT_IMG_DOMAINS)
        if from_trusted_cdn and isinstance(parent, Tag):
            parent_name = (parent.name or "").lower()
            if parent_name in ("article", "section", "main", "p", "figure", "figcaption"):
                return True

        # Layer 6: Width < 100px AND near-square → exclude
        if w is not None and w < 100:
            if h is not None and h > 0:
                aspect = w / h
                if 0.8 <= aspect <= 1.2:
                    return False

        # Large content image in a content parent → include
        if w is not None and w >= 200 and isinstance(parent, Tag):
            parent_name = (parent.name or "").lower()
            if parent_name in ("article", "section", "main", "p", "figure", "figcaption"):
                return True

        # Default: exclude
        return False

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

    def _extract_images(
        self,
        soup: BeautifulSoup,
        max_images: int | None = None,
    ) -> tuple[str, ...]:
        """Extract content image URLs using the 6-layer heuristic classifier."""
        limit = max_images if max_images is not None else _MAX_IMAGES
        seen_urls: set[str] = set()
        results: list[str] = []

        for img in soup.find_all("img", src=True):
            src: str = img.get("src", "").strip()

            if not src.startswith("https://"):
                continue

            if src in seen_urls:
                continue

            if self._classify_image(img, soup):
                seen_urls.add(src)
                results.append(src)

                if len(results) >= limit:
                    break

        return tuple(results)
