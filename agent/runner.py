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
from agent.utils.models import DigestBatch, DigestEntry, SenderConfig
from agent.fetchers.gmail_fetcher import GmailFetcher
from agent.parsers.email_parser import EmailParser
from agent.summarizer.claude_summarizer import ClaudeSummarizer
from agent.digest.builder import DigestBuilder
from agent.digest.delivery import EmailDelivery

log = get_logger(__name__)


class NewsletterAgent:
    def __init__(self, config: AgentConfiguration, dry_run: bool = False, preview: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self.preview = preview
        self._fetcher = GmailFetcher()
        self._parser = EmailParser()
        self._summarizer = ClaudeSummarizer(
            api_key=config.anthropic_api_key,
            summary_length_mode=config.summary_length_mode,
            summary_word_target=config.summary_word_target,
            summary_percentage=config.summary_percentage,
            summary_min_words=config.summary_min_words,
            summary_max_words=config.summary_max_words,
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
        """Execute a full agent run: fetch → sort → batch → parse → summarize → build → deliver."""
        run_date = datetime.now(timezone.utc)
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
                    summary = self._summarizer.summarize(parsed)
                    entries.append(DigestEntry(
                        summary=summary,
                        links=parsed.links,
                        images=parsed.images,
                        is_pass_through=parsed.is_pass_through,
                        display_name=display_name,
                        gmail_message_id=parsed.gmail_message_id,
                    ))
                    log.info(
                        "newsletter_processed",
                        message_id=em.id,
                        sender=em.sender,
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

            # Advisor analysis — one call across all summaries in this batch
            advisor = None
            if self.config.user_profile is not None and entries:
                from agent.advisor.analyzer import AdvisorAnalyzer
                advisor = AdvisorAnalyzer(
                    api_key=self.config.anthropic_api_key,
                    user_profile=self.config.user_profile,
                ).analyze([e.summary for e in entries])

            gmail_ids = [e.gmail_message_id for e in entries if e.gmail_message_id]
            digest_batch = DigestBatch(
                batch_index=batch_idx,
                entries=entries,
                gmail_message_ids=gmail_ids,
                total_batches=total_batches,
                advisor=advisor,
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
                for entry in entries:
                    mode = "[PASS-THROUGH]" if entry.is_pass_through else "[SUMMARIZED]"
                    print(f"\n{mode} [{entry.display_name}] {entry.summary.subject}")
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
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        config = load_config(args.config)
    except ConfigurationError as exc:
        log.error("configuration_error", error=str(exc))
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    agent = NewsletterAgent(config=config, dry_run=args.dry_run, preview=args.preview)
    try:
        agent.run()
    except FetchError as exc:
        log.error("fatal_error", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
