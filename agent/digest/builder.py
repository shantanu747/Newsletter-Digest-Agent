"""Assembles the HTML digest from a DigestBatch using a Jinja2 template."""

from __future__ import annotations

import markupsafe
from datetime import datetime
from pathlib import Path

import jinja2

from agent.utils.logger import get_logger
from agent.utils.models import DigestBatch, DigestEntry

log = get_logger(__name__)

# Only these URL schemes are permitted in href/src attributes.
_SAFE_URL_SCHEMES = ("https://",)


def _nl2br(value: str) -> markupsafe.Markup:
    """Jinja2 filter: escape *value* then replace newlines with <br> tags."""
    escaped = markupsafe.escape(value)
    return markupsafe.Markup(escaped.replace("\n", markupsafe.Markup("<br>\n")))


def _safe_url(url: str) -> str:
    """Return *url* only if it starts with an allowed scheme, else ''."""
    return url if any(url.startswith(s) for s in _SAFE_URL_SCHEMES) else ""


class DigestBuilder:
    """Renders a DigestBatch into an HTML digest string."""

    def build(
        self,
        batch: DigestBatch,
        run_date: datetime,
        total_found: int = 0,
        total_summarized: int | None = None,
        failed_subjects: list[str] | None = None,
    ) -> str:
        """Render the digest template and return the resulting HTML string.

        Args:
            batch: The DigestBatch containing entries and batch metadata.
            run_date: The datetime representing when this digest run was triggered.
            total_found: Total number of newsletters found before filtering.
            total_summarized: Override for total summarized count (defaults to len(batch.entries)).
            failed_subjects: Subject lines of newsletters that could not be summarized.

        Returns:
            Rendered HTML string ready for delivery.
        """
        failed_subjects = failed_subjects or []
        _total_summarized = total_summarized if total_summarized is not None else len(batch.entries)

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(
                str(Path(__file__).parent.parent.parent / "templates")
            ),
            autoescape=True,
        )
        env.filters["nl2br"] = _nl2br
        env.filters["safe_url"] = _safe_url

        template = env.get_template("digest.html.j2")

        log.info(
            "digest_rendered",
            batch_index=batch.batch_index + 1,
            total_batches=batch.total_batches,
            total_found=total_found,
            total_summarized=_total_summarized,
            failed_count=len(failed_subjects),
        )

        return template.render(
            entries=batch.entries,
            batch=batch,
            run_date=run_date,
            total_found=total_found,
            total_summarized=_total_summarized,
            failed_subjects=failed_subjects,
        )
