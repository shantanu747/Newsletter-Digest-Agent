"""Assembles the HTML digest from a list of DigestEntry objects using a Jinja2 template."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import jinja2

from agent.utils.logger import get_logger
from agent.utils.models import DigestEntry

log = get_logger(__name__)


class DigestBuilder:
    """Renders a list of DigestEntry objects into an HTML digest string."""

    def build(
        self,
        entries: list[DigestEntry],
        run_date: datetime,
        total_found: int = 0,
        total_summarized: int | None = None,
        failed_subjects: list[str] | None = None,
    ) -> str:
        """Render the digest template and return the resulting HTML string.

        Args:
            entries: Ordered list of DigestEntry objects to include in the digest.
            run_date: The datetime representing when this digest run was triggered.
            total_found: Total number of newsletters found before summarization filtering.
            failed_subjects: Subject lines of newsletters that could not be summarized.

        Returns:
            Rendered HTML string ready for delivery.
        """
        failed_subjects = failed_subjects or []
        _total_summarized = total_summarized if total_summarized is not None else len(entries)

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(
                str(Path(__file__).parent.parent.parent / "templates")
            ),
            autoescape=True,
        )

        template = env.get_template("digest.html.j2")

        log.info(
            "digest_rendered",
            total_found=total_found,
            total_summarized=_total_summarized,
            failed_count=len(failed_subjects),
        )

        return template.render(
            entries=entries,
            run_date=run_date,
            total_found=total_found,
            total_summarized=_total_summarized,
            failed_subjects=failed_subjects,
        )
