"""End-to-end pipeline test using real .eml files from eml_examples/.

Loads each .eml file, runs the full pipeline (parse → summarize → build), and
either saves the resulting HTML to eml_examples/test_digest_output.html (default
dry-run mode) or sends it via SMTP (--send flag).

Prints per-stage timing so bottlenecks are visible.

Usage:
    python scripts/test_pipeline.py             # dry-run, saves HTML locally
    python scripts/test_pipeline.py --send      # actually sends the digest email
    python scripts/test_pipeline.py --open      # dry-run + open in browser

Requires:
    - ANTHROPIC_API_KEY in .env (for summarization)
    - Full .env populated (for --send: SMTP_*, DELIVERY_EMAIL, etc.)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on the path when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from agent.digest.builder import DigestBuilder
from agent.digest.delivery import EmailDelivery
from agent.parsers.email_parser import EmailParser
from agent.summarizer.claude_summarizer import ClaudeSummarizer
from agent.utils.eml_loader import load_eml
from agent.utils.models import DigestBatch, DigestEntry


def _load_emails(eml_dir: Path) -> list:
    eml_files = sorted(eml_dir.glob("*.eml"))
    if not eml_files:
        print(f"No .eml files found in {eml_dir}/", file=sys.stderr)
        sys.exit(1)
    emails = []
    for path in eml_files:
        email = load_eml(path)
        print(f"  Loaded: {path.name} — {email.sender!r}")
        emails.append(email)
    return emails


def main() -> None:
    parser = argparse.ArgumentParser(description="Full pipeline test using .eml files")
    parser.add_argument("--send", action="store_true", help="Send the digest via SMTP")
    parser.add_argument("--open", action="store_true", help="Open output HTML in browser (dry-run only)")
    parser.add_argument("--eml-dir", default="eml_examples", help="Directory with .eml files")
    args = parser.parse_args()

    eml_dir = Path(args.eml_dir)
    if not eml_dir.exists():
        print(f"Directory not found: {eml_dir}", file=sys.stderr)
        sys.exit(1)

    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    run_date = datetime.now(timezone.utc)

    # --- Stage 1: Load ---
    t0 = time.perf_counter()
    print("\n[1/4] Loading .eml files …")
    emails = _load_emails(eml_dir)
    print(f"      {len(emails)} emails loaded in {time.perf_counter() - t0:.2f}s")

    # --- Stage 2: Parse ---
    t1 = time.perf_counter()
    print("\n[2/4] Parsing HTML …")
    email_parser = EmailParser()
    parsed_emails = []
    for email in emails:
        parsed = email_parser.parse(email)
        plain_len = len(parsed.plain_text or "")
        print(f"  {email.subject!r}: {plain_len} chars, {len(parsed.links)} links, {len(parsed.images)} images")
        parsed_emails.append(parsed)
    print(f"      Parsed in {time.perf_counter() - t1:.2f}s")

    # --- Stage 3: Summarize ---
    t2 = time.perf_counter()
    print("\n[3/4] Summarizing with Claude (percentage mode: 18%, 100–500 words) …")
    summarizer = ClaudeSummarizer(
        api_key=api_key,
        summary_length_mode="percentage",
        summary_percentage=18,
        summary_min_words=100,
        summary_max_words=500,
    )
    entries: list[DigestEntry] = []
    failed_subjects: list[str] = []
    for parsed in parsed_emails:
        try:
            summary = summarizer.summarize(parsed)
            entries.append(DigestEntry(summary=summary, links=parsed.links, images=parsed.images))
            print(f"  {parsed.subject!r}: {summary.word_count} words")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED {parsed.subject!r}: {exc}", file=sys.stderr)
            failed_subjects.append(parsed.subject)
    print(f"      Summarized in {time.perf_counter() - t2:.2f}s")

    # --- Stage 4: Build ---
    t3 = time.perf_counter()
    print("\n[4/4] Building digest HTML …")
    builder = DigestBuilder()
    batch = DigestBatch(
        batch_index=0,
        entries=entries,
        gmail_message_ids=[],
        total_batches=1,
    )
    html = builder.build(
        batch=batch,
        run_date=run_date,
        total_found=len(emails),
        failed_subjects=failed_subjects,
    )
    print(f"      Built in {time.perf_counter() - t3:.2f}s ({len(html)} chars)")

    total_elapsed = time.perf_counter() - t0
    print(f"\nTotal pipeline time: {total_elapsed:.2f}s")

    if args.send:
        # Need full config for SMTP
        from agent.utils.config import load_config
        config = load_config()
        subject = f"Newsletter Digest — {run_date.strftime('%B %-d, %Y')} ({len(entries)} newsletters)"
        print(f"\nSending digest to {config.delivery_recipient} …")
        delivery = EmailDelivery()
        delivery.send(html_body=html, subject=subject, config=config)
        print("Sent!")
    else:
        out_path = eml_dir / "test_digest_output.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"\nDry-run complete. HTML saved to {out_path}")
        if args.open:
            subprocess.run(["open", str(out_path)], check=False)


if __name__ == "__main__":
    main()
