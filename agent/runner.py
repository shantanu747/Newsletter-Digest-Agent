"""Newsletter Digest Agent — main orchestrator and CLI entry point.

Pipeline order:
    load_config() → GmailFetcher → EmailParser → ClaudeSummarizer → DigestBuilder → EmailDelivery

Extension points:
    - Add a new email source: subclass BaseFetcher (agent/fetchers/base_fetcher.py),
      implement fetch_newsletters(), and swap it in for GmailFetcher in NewsletterAgent.__init__.
    - Add a new output channel: implement a delivery class with a send() method and
      replace EmailDelivery in NewsletterAgent.__init__.
"""
from __future__ import annotations

import argparse
import email.utils
import math
import sys
from datetime import datetime, timezone

from agent.utils.config import AgentConfiguration, load_config
from agent.utils.exceptions import ConfigurationError, FetchError, SummarizationError, DeliveryError
from agent.utils.logger import get_logger
from agent.utils.models import DigestBatch, DigestEntry, SenderConfig, Theme
from agent.trends.synthesis import cluster_ideas, ThemeSynthesizer
from agent.fetchers.gmail_fetcher import GmailFetcher
from agent.parsers.email_parser import EmailParser
from agent.summarizer.claude_summarizer import ClaudeSummarizer
from agent.digest.builder import DigestBuilder
from agent.digest.delivery import EmailDelivery

log = get_logger(__name__)


class NewsletterAgent:
    def __init__(
        self,
        config: AgentConfiguration,
        dry_run: bool = False,
        preview: bool = False,
        skip_signals: bool = False,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.preview = preview
        self.skip_signals = skip_signals
        self._fetcher = GmailFetcher()
        self._parser = EmailParser()
        self._summarizer = ClaudeSummarizer(
            api_key=config.anthropic_api_key,
            model=config.model,
            summary_length_mode=config.summary_length_mode,
            summary_word_target=config.summary_word_target,
            summary_percentage=config.summary_percentage,
            summary_min_words=config.summary_min_words,
            summary_max_words=config.summary_max_words,
            knowledge_config=config.knowledge,
        )
        self._builder = DigestBuilder()
        self._delivery = EmailDelivery()

    def _lookup_sender_config(self, sender_header: str) -> SenderConfig | None:
        """Find the SenderConfig for a sender header value (case-insensitive)."""
        bare_addr = email.utils.parseaddr(sender_header)[1].lower()
        for sc in self.config.senders:
            if sc.address == bare_addr:
                return sc
        return None

    def run(self) -> None:
        """Execute a full agent run, then evaluate whether a periodic Signals Report is due.

        The Signals Report cadence check runs in `finally` so that neither an empty inbox
        nor a digest-pipeline exception can suppress a due report (FR-026, SC-006) — those
        quiet stretches, with no digest arriving either, are exactly when a trend report
        is most useful.
        """
        now = datetime.now(timezone.utc)
        try:
            self._run_digest(now)
        finally:
            if not self.skip_signals:
                self.maybe_run_signals(now)

    def _run_digest(self, run_date: datetime) -> None:
        """Execute the digest pipeline: fetch → sort → batch → parse → summarize → build → deliver."""
        log.info("agent_run_started", dry_run=self.dry_run)

        # Fetch
        try:
            emails = self._fetcher.fetch_newsletters(self.config)
        except FetchError as exc:
            log.error("fetch_failed", error=str(exc))
            raise

        if not emails:
            log.info("poll_complete_no_emails")
            return

        observation_store = None
        if self.config.knowledge is not None and self.config.knowledge.enabled:
            from agent.knowledge.store import ObservationStore
            observation_store = ObservationStore(self.config.knowledge.db_path)

        # Sort oldest-first, then cap
        sorted_emails = sorted(emails, key=lambda e: e.received_at)
        unique_emails = list({e.id: e for e in sorted_emails}.values())[: self.config.max_newsletters_per_run]

        # Batch into DigestBatch groups
        batch_size = self.config.batch_size
        total_batches = math.ceil(len(unique_emails) / batch_size)

        log.info(
            "poll_started",
            total_unread=len(unique_emails),
            total_batches=total_batches,
        )

        for batch_idx in range(total_batches):
            batch_emails = unique_emails[batch_idx * batch_size : (batch_idx + 1) * batch_size]

            # Parse + Summarize
            entries: list[DigestEntry] = []
            failed_subjects: list[str] = []

            for em in batch_emails:
                sender_cfg = self._lookup_sender_config(em.sender)
                parsed = self._parser.parse(em, sender_config=sender_cfg)

                display_name = ""
                if sender_cfg is not None and sender_cfg.display_name:
                    display_name = sender_cfg.display_name
                else:
                    display_name = email.utils.parseaddr(em.sender)[0] or em.sender

                try:
                    idea_mode = self.config.digest_format == "idea_based"
                    if idea_mode and not parsed.is_pass_through:
                        summary = self._summarizer.summarize_as_ideas(parsed, self.config.user_profile)
                    else:
                        summary = self._summarizer.summarize(parsed)
                    entries.append(DigestEntry(
                        summary=summary,
                        links=() if idea_mode else parsed.links,
                        images=parsed.images,
                        is_pass_through=parsed.is_pass_through,
                        display_name=display_name,
                        gmail_message_id=parsed.gmail_message_id,
                    ))
                    log.info(
                        "newsletter_processed",
                        message_id=em.id,
                        sender=em.sender,
                        digest_format=self.config.digest_format,
                        idea_count=len(summary.ideas) if summary.ideas else None,
                        word_count=summary.word_count,
                        pass_through=parsed.is_pass_through,
                    )
                except SummarizationError as exc:
                    log.warning(
                        "newsletter_summarization_failed",
                        message_id=em.id,
                        subject=em.subject,
                        error=str(exc),
                    )
                    failed_subjects.append(em.subject)

            if not entries and not failed_subjects:
                continue

            # Observation recording — must happen before delivery/move_to_trash, since a
            # trashed email's mentions become unrecoverable (FR-007). --preview writes here
            # deliberately; --dry-run only reads (recording stays gated below).
            if observation_store is not None and not self.dry_run:
                for entry in entries:
                    observation_store.record_summary(entry.summary)

            # Recurring-entity context — one store query per batch. `until` is the start
            # of today so today's own mentions are excluded from the window.
            entity_context: dict = {}
            if observation_store is not None:
                from agent.knowledge.context import collect_norm_keys, context_window
                since, until = context_window(run_date)
                entity_context = observation_store.recent_context(
                    collect_norm_keys(entries), since, until
                )

            # Advisor analysis — one call across all summaries in this batch
            advisor = None
            if self.config.user_profile is not None and entries:
                from agent.advisor.analyzer import AdvisorAnalyzer
                advisor = AdvisorAnalyzer(
                    api_key=self.config.anthropic_api_key,
                    user_profile=self.config.user_profile,
                    model=self.config.model,
                ).analyze([e.summary for e in entries], entity_context=entity_context)

            # Theme synthesis — merge cross-newsletter stories into Today's Themes block
            themes: tuple[Theme, ...] = ()
            if (
                self.config.knowledge is not None
                and self.config.knowledge.enabled
                and self.config.knowledge.synthesis_enabled
                and entries
            ):
                clusters = cluster_ideas(entries)
                if clusters:
                    themes = ThemeSynthesizer(
                        api_key=self.config.anthropic_api_key, model=self.config.model
                    ).synthesize(clusters, entries)

            gmail_ids = [e.gmail_message_id for e in entries if e.gmail_message_id]
            digest_batch = DigestBatch(
                batch_index=batch_idx,
                entries=entries,
                gmail_message_ids=gmail_ids,
                total_batches=total_batches,
                advisor=advisor,
                themes=themes,
                entity_context=entity_context,
            )

            # Build digest HTML
            html = self._builder.build(
                batch=digest_batch,
                run_date=run_date,
                total_found=len(unique_emails),
                failed_subjects=failed_subjects,
            )

            # Deliver or dry-run
            batch_label = f"Batch {batch_idx + 1} of {total_batches}"
            if self.dry_run:
                log.info(
                    "dry_run_batch_complete",
                    batch_index=batch_idx + 1,
                    total_batches=total_batches,
                    summarized=len(entries),
                    failed=len(failed_subjects),
                )
                print(f"\n{'='*60}")
                print(f"DRY RUN — Digest {batch_label} — {run_date.strftime('%Y-%m-%d')}")
                print(f"Newsletters: {len(entries)}, Failed: {len(failed_subjects)}")
                if failed_subjects:
                    print(f"Failed: {', '.join(failed_subjects)}")
                print('='*60)
                if digest_batch.advisor:
                    adv = digest_batch.advisor
                    if adv.relevance_text:
                        print("\n--- What This Means For You ---")
                        r = adv.relevance_text
                        print(r[:400] + "..." if len(r) > 400 else r)
                    if adv.signals_text:
                        print("\n--- Action Signals ---")
                        s = adv.signals_text
                        print(s[:400] + "..." if len(s) > 400 else s)
                if digest_batch.themes:
                    print("\n--- Today's Themes ---")
                    for theme in digest_batch.themes:
                        sources_str = ", ".join(theme.sources)
                        body_preview = theme.body[:300]
                        print(f"• {theme.title}  [{sources_str}]")
                        print(f"  {body_preview}")
                        if theme.disagreement:
                            print(f"  Disagreement: {theme.disagreement}")
                for entry in entries:
                    mode = "[PASS-THROUGH]" if entry.is_pass_through else "[SUMMARIZED]"
                    print(f"\n{mode} [{entry.display_name}] {entry.summary.subject}")
                    if entry.summary.ideas:
                        from agent.knowledge.context import badge_for_idea
                        for idea in entry.summary.ideas:
                            print(f"  • {idea.title}")
                            badge = badge_for_idea(idea, digest_batch.entity_context)
                            if badge is not None:
                                print(f"    {badge}")
                            body = idea.summary_text
                            print(f"    {body[:200] + '...' if len(body) > 200 else body}")
                    else:
                        print(f"Words: {entry.summary.word_count}")
                        preview = entry.summary.summary_text
                        print(preview[:300] + "..." if len(preview) > 300 else preview)
            else:
                digest_subject = (
                    f"Newsletter Digest — {batch_label} — "
                    f"{run_date.strftime('%B %-d, %Y')} ({len(entries)} newsletters)"
                )
                delivery_succeeded = False
                try:
                    self._delivery.send(html_body=html, subject=digest_subject, config=self.config)
                    delivery_succeeded = True
                except DeliveryError as exc:
                    log.error(
                        "delivery_failed",
                        batch_index=batch_idx + 1,
                        total_batches=total_batches,
                        error=str(exc),
                    )

                if delivery_succeeded:
                    if not self.preview:
                        # Post-delivery: mark as read then trash each source email
                        for msg_id in digest_batch.gmail_message_ids:
                            self._fetcher.mark_as_read(msg_id)
                            self._fetcher.move_to_trash(msg_id)
                    else:
                        log.info("preview_skipped_mutations", message_ids=digest_batch.gmail_message_ids)

                    emails_remaining = len(unique_emails) - (batch_idx + 1) * batch_size
                    log.info(
                        "batch_complete",
                        batch_index=batch_idx + 1,
                        total_batches=total_batches,
                        emails_in_batch=len(entries),
                        emails_remaining=max(0, emails_remaining),
                    )

        log.info("single_run_complete", dry_run=self.dry_run)

    def maybe_run_signals(self, now: datetime, force: bool = False, dry_run: bool = False) -> None:
        """Evaluate cadence and, if due, run the periodic Signals Report. Never raises (FR-029).

        *force* bypasses the `job_due` cadence check (used by `--signals`/`--signals-dry-run`).
        *dry_run* renders and prints the report instead of sending it, and does not update
        `job_run` — it's a diagnostic pass, not a real cycle.
        """
        if self.config.signals is None or not self.config.signals.enabled:
            return
        if self.config.knowledge is None:
            return

        from agent.knowledge.store import ObservationStore
        store = ObservationStore(self.config.knowledge.db_path)

        if not force and not store.job_due("signals_report", self.config.signals.interval_days, now):
            return

        status = "failure"
        try:
            from agent.trends.metrics import compute_brief
            from agent.trends.analyzer import TrendAnalyzer
            from agent.digest.builder import build_signals

            brief = compute_brief(store, self.config.signals, now)
            # FredFetcher lands in a later phase (US2) — the macro dashboard renders
            # nothing until then, which is a valid, expected render (report.macro is None).
            macro = None

            report = TrendAnalyzer(
                api_key=self.config.anthropic_api_key,
                config=self.config.signals,
                user_profile=self.config.user_profile,
            ).analyze(brief, macro)

            html = build_signals(report, now)
            subject = f"Signals Report — {now.strftime('%B %-d, %Y')}"

            if dry_run:
                print(f"\n{'='*60}")
                print(f"DRY RUN — {subject}")
                print(
                    f"Risks: {len(report.risks)}, Opportunities: {len(report.opportunities)}, "
                    f"Emerging: {len(report.emerging)}, Fading: {len(report.fading)}, "
                    f"Watch: {len(report.watch)}"
                )
                print("=" * 60)
            else:
                self._delivery.send(html_body=html, subject=subject, config=self.config)

            status = "success"
            log.info("signals_report_complete", dry_run=dry_run, forced=force)
        except Exception as exc:
            log.error("signals_report_failed", error=str(exc), exc_info=True)
        finally:
            if not dry_run:
                store.mark_job_run("signals_report", status, now)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Newsletter Digest Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and summarize newsletters but do not send the digest email.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Deliver the digest email but skip mark-as-read and move-to-trash.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll and exit without starting the scheduler.",
    )
    parser.add_argument(
        "--config",
        default="config/newsletters.yaml",
        help="Path to newsletters.yaml config file (default: config/newsletters.yaml).",
    )
    parser.add_argument(
        "--signals",
        action="store_true",
        help="Run only the Signals Report pipeline (bypassing cadence) and exit. No digest fetch.",
    )
    parser.add_argument(
        "--signals-dry-run",
        action="store_true",
        help="Run the Signals Report pipeline end-to-end but print instead of sending. No digest fetch.",
    )
    parser.add_argument(
        "--skip-signals",
        action="store_true",
        help="Run the digest but skip the Signals Report cadence check for this run.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        config = load_config(args.config)
    except ConfigurationError as exc:
        log.error("configuration_error", error=str(exc))
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.signals or args.signals_dry_run:
        agent = NewsletterAgent(config=config)
        agent.maybe_run_signals(datetime.now(timezone.utc), force=True, dry_run=args.signals_dry_run)
        return

    if args.once or args.dry_run or args.preview:
        agent = NewsletterAgent(
            config=config,
            dry_run=args.dry_run,
            preview=args.preview,
            skip_signals=args.skip_signals,
        )
        try:
            agent.run()
        except FetchError as exc:
            log.error("fatal_error", error=str(exc))
            sys.exit(1)
    else:
        from agent.scheduler import DigestScheduler
        DigestScheduler(config=config).start()


if __name__ == "__main__":
    main()
