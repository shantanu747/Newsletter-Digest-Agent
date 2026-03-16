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
import sys
from datetime import datetime, timezone

from agent.utils.config import AgentConfiguration, load_config
from agent.utils.exceptions import ConfigurationError, FetchError, SummarizationError, DeliveryError
from agent.utils.logger import get_logger
from agent.utils.models import DigestEntry
from agent.fetchers.gmail_fetcher import GmailFetcher
from agent.parsers.email_parser import EmailParser
from agent.summarizer.claude_summarizer import ClaudeSummarizer
from agent.digest.builder import DigestBuilder
from agent.digest.delivery import EmailDelivery

log = get_logger(__name__)


class NewsletterAgent:
    def __init__(self, config: AgentConfiguration, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self._fetcher = GmailFetcher()
        self._parser = EmailParser()
        self._summarizer = ClaudeSummarizer(api_key=config.anthropic_api_key)
        self._builder = DigestBuilder()
        self._delivery = EmailDelivery()

    def run(self) -> None:
        """Execute a full agent run: fetch → parse → summarize → build → deliver."""
        run_date = datetime.now(timezone.utc)
        log.info("agent_run_started", dry_run=self.dry_run, lookback_hours=self.config.lookback_hours)

        # Fetch
        try:
            emails = self._fetcher.fetch_newsletters(self.config)
        except FetchError as exc:
            log.error("fetch_failed", error=str(exc))
            raise

        if not emails:
            log.info("no_newsletters_found", lookback_hours=self.config.lookback_hours)
            return

        # Deduplicate and cap
        seen: dict[str, ...] = {}
        for e in emails:
            seen[e.id] = e
        unique_emails = list(seen.values())[: self.config.max_newsletters_per_run]
        log.info("newsletters_to_process", count=len(unique_emails), total_found=len(emails))

        # Parse + Summarize
        entries: list[DigestEntry] = []
        failed_subjects: list[str] = []

        for email in unique_emails:
            parsed = self._parser.parse(email)
            try:
                summary = self._summarizer.summarize(parsed)
                entries.append(DigestEntry(summary=summary))
                log.info("newsletter_processed", message_id=email.id, sender=email.sender, word_count=summary.word_count)
            except SummarizationError as exc:
                log.warning("newsletter_summarization_failed", message_id=email.id, subject=email.subject, error=str(exc))
                failed_subjects.append(email.subject)

        # Build digest
        html = self._builder.build(
            entries=entries,
            run_date=run_date,
            total_found=len(emails),
            failed_subjects=failed_subjects,
        )

        # Deliver or dry-run
        if self.dry_run:
            log.info("dry_run_complete", summarized=len(entries), failed=len(failed_subjects))
            print(f"\n{'='*60}")
            print(f"DRY RUN — Digest for {run_date.strftime('%Y-%m-%d')}")
            print(f"Newsletters summarized: {len(entries)}, Failed: {len(failed_subjects)}")
            if failed_subjects:
                print(f"Failed: {', '.join(failed_subjects)}")
            print('='*60)
            for entry in entries:
                print(f"\n[{entry.summary.sender}] {entry.summary.subject}")
                print(f"Words: {entry.summary.word_count}")
                print(entry.summary.summary_text[:300] + "..." if len(entry.summary.summary_text) > 300 else entry.summary.summary_text)
        else:
            digest_subject = f"Newsletter Digest — {run_date.strftime('%B %-d, %Y')} ({len(entries)} newsletters)"
            try:
                self._delivery.send(html_body=html, subject=digest_subject, config=self.config)
            except DeliveryError as exc:
                log.error("delivery_failed", error=str(exc))
                raise

        log.info("agent_run_complete", summarized=len(entries), failed=len(failed_subjects), dry_run=self.dry_run)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Newsletter Digest Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and summarize newsletters but do not send the digest email.",
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

    agent = NewsletterAgent(config=config, dry_run=args.dry_run)
    try:
        agent.run()
    except (FetchError, DeliveryError) as exc:
        log.error("fatal_error", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
