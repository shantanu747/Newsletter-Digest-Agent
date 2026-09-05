"""Assembles the HTML digest from a DigestBatch using a Jinja2 template."""

from __future__ import annotations

import markupsafe
from datetime import datetime
from pathlib import Path

import jinja2

from agent.knowledge.context import badge_for_idea
from agent.utils.logger import get_logger
from agent.utils.models import DigestBatch, Idea, SignalsReport

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


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(
            str(Path(__file__).parent.parent.parent / "templates")
        ),
        autoescape=True,
    )
    env.filters["nl2br"] = _nl2br
    env.filters["safe_url"] = _safe_url
    return env


def _compute_theme_data(batch: DigestBatch) -> tuple[dict[tuple[str, int], str], dict[str, list[tuple[int, Idea]]], dict[str, list[str]]]:
    """Compute theme-related data for template rendering.

    Returns:
        absorbed: map from (email_id, idea_index) -> theme title
        visible_ideas: map from email_id -> list of (original_index, idea) not absorbed
        absorbed_titles_by_email: map from email_id -> list of theme titles for absorbed ideas
    """
    absorbed: dict[tuple[str, int], str] = {}
    for theme in batch.themes:
        for key in theme.absorbed_idea_keys:
            absorbed.setdefault(key, theme.title)

    visible_ideas: dict[str, list[tuple[int, Idea]]] = {}
    absorbed_titles_by_email: dict[str, list[str]] = {}

    for entry in batch.entries:
        email_id = entry.summary.email_id
        if entry.summary.ideas is None:
            visible_ideas[email_id] = []
            continue

        visible: list[tuple[int, Idea]] = []
        absorbed_titles: list[str] = []
        for idx, idea in enumerate(entry.summary.ideas):
            key = (email_id, idx)
            if key in absorbed:
                title = absorbed[key]
                if title not in absorbed_titles:
                    absorbed_titles.append(title)
            else:
                visible.append((idx, idea))
        visible_ideas[email_id] = visible
        absorbed_titles_by_email[email_id] = absorbed_titles

    return absorbed, visible_ideas, absorbed_titles_by_email


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

        absorbed, visible_ideas, absorbed_titles_by_email = _compute_theme_data(batch)

        badges: dict[tuple[str, int], str] = {}
        for entry in batch.entries:
            email_id = entry.summary.email_id
            if entry.summary.ideas is None:
                continue
            for idx, idea in enumerate(entry.summary.ideas):
                if (email_id, idx) in absorbed:
                    continue
                badge = badge_for_idea(idea, batch.entity_context)
                if badge is not None:
                    badges[(email_id, idx)] = badge

        env = _make_env()
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
            absorbed=absorbed,
            visible_ideas=visible_ideas,
            absorbed_titles_by_email=absorbed_titles_by_email,
            badges=badges,
        )


def build_signals(report: SignalsReport, run_date: datetime) -> str:
    """Render a SignalsReport into an HTML report string."""
    env = _make_env()
    template = env.get_template("signals.html.j2")

    log.info(
        "signals_report_rendered",
        window_days=report.window_days,
        risk_count=len(report.risks),
        opportunity_count=len(report.opportunities),
        emerging_count=len(report.emerging),
        fading_count=len(report.fading),
        watch_count=len(report.watch),
        divergence_count=len(report.divergences),
        track_record_count=len(report.track_record),
        is_cold_start=report.is_cold_start,
    )

    return template.render(report=report, run_date=run_date)
