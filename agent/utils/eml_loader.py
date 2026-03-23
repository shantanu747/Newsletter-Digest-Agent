"""Load a local .eml file into an Email dataclass.

Shared by test fixtures (tests/fixtures/load_eml.py) and dev scripts
(scripts/grade_extraction.py, scripts/test_pipeline.py).

Usage:
    from agent.utils.eml_loader import load_eml
    email = load_eml("eml_examples/Bloomberg - Like 2008 all over again.eml")
"""

from __future__ import annotations

import email as _stdlib_email
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from agent.utils.models import Email


def load_eml(path: str | Path) -> Email:
    """Parse a .eml file and return a populated Email dataclass.

    - id: derived from filename stem (spaces → hyphens, lowercased)
    - source: always 'eml_file'
    - sender: value of the From header
    - subject: value of the Subject header
    - received_at: parsed from the Date header (UTC); falls back to now()
    - raw_html: text/html MIME part; empty string if absent
    - plain_text: text/plain MIME part; None if absent
    - links / images: always empty tuples (EmailParser populates these)
    """
    path = Path(path)
    msg = _stdlib_email.message_from_bytes(path.read_bytes())

    msg_id = path.stem.replace(" ", "-").lower()

    try:
        received_at = parsedate_to_datetime(msg.get("Date", "")).astimezone(timezone.utc)
    except Exception:
        received_at = datetime.now(timezone.utc)

    raw_html = ""
    plain_text_body: str | None = None

    for part in msg.walk():
        ct = part.get_content_type()
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")

        if ct == "text/html" and not raw_html:
            raw_html = decoded
        elif ct == "text/plain" and plain_text_body is None:
            plain_text_body = decoded

    def _decode_header(value: str) -> str:
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    return Email(
        id=msg_id,
        source="eml_file",
        sender=_decode_header(msg.get("From", "")),
        subject=_decode_header(msg.get("Subject", "")),
        received_at=received_at,
        raw_html=raw_html,
        plain_text=plain_text_body,
    )
