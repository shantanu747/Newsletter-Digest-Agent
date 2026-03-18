"""Gmail fetcher — retrieves newsletter emails via the Gmail API."""

from __future__ import annotations

import base64
import email.utils
import os
import stat
from datetime import datetime, timedelta, timezone

import google.auth.transport.requests
import google.oauth2.credentials
import googleapiclient.discovery
import googleapiclient.errors

from agent.fetchers.base_fetcher import BaseFetcher
from agent.utils.config import AgentConfiguration
from agent.utils.exceptions import FetchError
from agent.utils.logger import get_logger
from agent.utils.models import Email

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

log = get_logger(__name__)


class GmailFetcher(BaseFetcher):
    """Fetches newsletter emails from a Gmail account using the Gmail API."""

    def __init__(self, token_path: str | None = None) -> None:
        self._token_path = token_path

    def fetch_newsletters(self, config: AgentConfiguration) -> list[Email]:
        """Fetch emails from Gmail and return those matching sender/keyword rules.

        Args:
            config: Fully-loaded AgentConfiguration instance.

        Returns:
            Deduplicated list of Email objects that match at least one detection rule.

        Raises:
            FetchError: Wraps any googleapiclient.errors.HttpError.
        """
        token_path = self._token_path or config.gmail_token_path

        # Refuse to load a token file that is readable by group or others — OAuth
        # refresh tokens must be kept private (owner-only: mode 600).
        try:
            file_mode = os.stat(token_path).st_mode
            if file_mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
                raise FetchError(
                    f"Insecure permissions on {token_path} — run: chmod 600 {token_path}"
                )
        except FileNotFoundError:
            raise FetchError(
                f"Gmail token file not found: {token_path}. "
                "Run scripts/gmail_auth.py to authenticate."
            )

        try:
            creds = google.oauth2.credentials.Credentials.from_authorized_user_file(
                token_path
            )

            if creds.expired and creds.refresh_token:
                creds.refresh(google.auth.transport.requests.Request())

            service = googleapiclient.discovery.build(
                "gmail", "v1", credentials=creds
            )

            after_epoch = int(
                (datetime.now(timezone.utc) - timedelta(hours=config.lookback_hours)).timestamp()
            )
            q = f"after:{after_epoch}"

            # --- Fetch all message IDs (paginated) ---
            message_ids: list[str] = []
            response = (
                service.users()
                .messages()
                .list(userId="me", q=q)
                .execute()
            )
            for stub in response.get("messages", []):
                message_ids.append(stub["id"])

            while "nextPageToken" in response:
                response = (
                    service.users()
                    .messages()
                    .list(userId="me", q=q, pageToken=response["nextPageToken"])
                    .execute()
                )
                for stub in response.get("messages", []):
                    message_ids.append(stub["id"])

            # --- Fetch full message details ---
            raw_emails: list[Email] = []
            for msg_id in message_ids:
                full_msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="full")
                    .execute()
                )
                email_obj = self._parse_message(msg_id, full_msg)
                if email_obj is not None:
                    raw_emails.append(email_obj)

        except googleapiclient.errors.HttpError as exc:
            raise FetchError(f"Gmail API error: {exc}") from exc

        # --- Two-pass client-side filter + deduplication ---
        seen: dict[str, Email] = {}

        # Pass 1: sender allowlist
        for em in raw_emails:
            if em.sender.lower() in config.senders:
                seen[em.id] = em

        # Pass 2: subject keywords (union — add any not yet kept)
        for em in raw_emails:
            if em.id not in seen:
                if any(kw in em.subject.lower() for kw in config.subject_keywords):
                    seen[em.id] = em

        # Log and return
        result = list(seen.values())
        for em in result:
            log.info(
                "newsletter_found",
                message_id=em.id,
                sender=em.sender,
                subject=em.subject,
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_message(self, msg_id: str, full_msg: dict) -> Email | None:
        """Parse a raw Gmail API message resource into an Email dataclass.

        Returns None if required headers cannot be found.
        """
        payload = full_msg.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

        from_header = headers.get("From", "")
        subject_header = headers.get("Subject", "")
        date_header = headers.get("Date", "")

        # Parse date to UTC-aware datetime
        try:
            received_at: datetime = email.utils.parsedate_to_datetime(date_header)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
        except Exception:
            received_at = datetime.now(timezone.utc)

        # Decode body — prefer text/html, fall back to text/plain
        html_body = self._extract_body(payload)

        return Email(
            id=msg_id,
            source="gmail",
            sender=from_header,
            subject=subject_header,
            received_at=received_at,
            raw_html=html_body,
        )

    def _extract_body(self, payload: dict) -> str:
        """Extract the best available body from a Gmail message payload.

        Prefers text/html from multipart messages; falls back to text/plain.
        For non-multipart messages uses the top-level body data.
        """
        parts = payload.get("parts")
        if parts:
            # Prefer HTML part
            for part in parts:
                if part.get("mimeType") == "text/html":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return self._decode_base64(data)
            # Fall back to plain text
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return self._decode_base64(data)
            return ""

        # Non-multipart: use top-level body
        data = payload.get("body", {}).get("data", "")
        return self._decode_base64(data) if data else ""

    @staticmethod
    def _decode_base64(data: str) -> str:
        """Decode a base64url-encoded string, padding as needed."""
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
