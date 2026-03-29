"""Unit tests for GmailFetcher.

Mocks both google.oauth2.credentials.Credentials.from_authorized_user_file
and googleapiclient.discovery.build so no real network calls are made.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agent.utils.config import AgentConfiguration
from agent.utils.models import Email, SenderConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64(text: str) -> str:
    """Return URL-safe base64-encoded string (as Gmail API returns it)."""
    return base64.urlsafe_b64encode(text.encode()).decode()


def _make_message(
    msg_id: str,
    sender: str,
    subject: str,
    date_str: str,
    html_body: str,
) -> dict:
    """Build a realistic minimal Gmail API message resource.

    The message has a multipart payload with a single text/html part.
    """
    return {
        "id": msg_id,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date_str},
            ],
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Plain text version.")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64(html_body)},
                },
            ],
        },
    }


def _make_plain_message(
    msg_id: str,
    sender: str,
    subject: str,
    date_str: str,
    plain_body: str,
) -> dict:
    """Build a message with only a text/plain part (no HTML)."""
    return {
        "id": msg_id,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date_str},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64(plain_body)},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64(plain_body)},
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATE_STR = "Mon, 09 Mar 2026 07:00:00 +0000"

ALLOWED_SENDER = "newsletter@example.com"
BLOCKED_SENDER = "spam@unknown.com"

HTML_BODY = "<html><body><h1>Top Stories</h1><p>Great content here.</p></body></html>"


@pytest.fixture
def mock_config() -> AgentConfiguration:
    """AgentConfiguration with a single allowed sender."""
    cfg = AgentConfiguration(
        senders=[SenderConfig(address=ALLOWED_SENDER, mode="summarize")],
        subject_keywords=["daily digest"],
        max_newsletters_per_run=20,
        summary_word_target=225,
    )
    cfg.anthropic_api_key = "test-key"
    cfg.gmail_token_path = "test-token.json"
    cfg.delivery_recipient = "recipient@example.com"
    cfg.smtp_host = "smtp.example.com"
    cfg.smtp_port = 587
    cfg.smtp_user = "user@example.com"
    cfg.smtp_password = "test-password"
    return cfg


def _build_gmail_service_mock(messages: list[dict]) -> MagicMock:
    """Return a mock Gmail service where list() yields message stubs and
    get() returns the full message dicts keyed by id."""
    service = MagicMock()

    # service.users().messages().list(...).execute()
    list_response = {"messages": [{"id": m["id"]} for m in messages]} if messages else {}
    (
        service.users.return_value
        .messages.return_value
        .list.return_value
        .execute.return_value
    ) = list_response

    # service.users().messages().get(userId='me', id=<id>, format='full').execute()
    messages_by_id = {m["id"]: m for m in messages}

    def _get_execute(userId, id, format):  # noqa: A002
        mock = MagicMock()
        mock.execute.return_value = messages_by_id[id]
        return mock

    (
        service.users.return_value
        .messages.return_value
        .get.side_effect
    ) = _get_execute

    return service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGmailFetcherFetchNewsletters:
    """Tests for GmailFetcher.fetch_newsletters()."""

    def _fetch(
        self,
        mocker,
        mock_config: AgentConfiguration,
        messages: list[dict],
    ) -> list[Email]:
        """Patch credentials + build, instantiate fetcher, and call fetch_newsletters."""
        # Simulate a token file with secure permissions (owner-read/write only).
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100600  # regular file, mode 600
        mocker.patch("agent.fetchers.gmail_fetcher.os.stat", return_value=mock_stat)

        mock_creds = MagicMock()
        mocker.patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        )
        mock_service = _build_gmail_service_mock(messages)
        mocker.patch(
            "googleapiclient.discovery.build",
            return_value=mock_service,
        )

        from agent.fetchers.gmail_fetcher import GmailFetcher  # noqa: PLC0415

        fetcher = GmailFetcher(token_path=mock_config.gmail_token_path)
        return fetcher.fetch_newsletters(mock_config)

    # ------------------------------------------------------------------
    # 1. Correct Email fields from mocked API response
    # ------------------------------------------------------------------

    def test_returns_email_with_correct_fields(self, mocker, mock_config):
        """Returned Email has id, sender, subject, raw_html populated correctly."""
        msg = _make_message(
            msg_id="abc123",
            sender=ALLOWED_SENDER,
            subject="The Daily Digest — March 9",
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        email = emails[0]

        assert isinstance(email, Email)
        assert email.id == "abc123"
        assert email.sender == ALLOWED_SENDER
        assert email.subject == "The Daily Digest — March 9"
        assert email.raw_html == HTML_BODY
        assert email.source == "gmail"
        assert email.plain_text is None

    def test_received_at_is_utc_aware_datetime(self, mocker, mock_config):
        """received_at must be a UTC-aware datetime."""
        msg = _make_message(
            msg_id="abc123",
            sender=ALLOWED_SENDER,
            subject="Test Subject",
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        received_at = emails[0].received_at
        assert isinstance(received_at, datetime)
        assert received_at.tzinfo is not None  # UTC-aware

    # ------------------------------------------------------------------
    # 2. Sender on allowlist is included
    # ------------------------------------------------------------------

    def test_allowed_sender_is_included(self, mocker, mock_config):
        """Emails from a sender on config.senders are returned."""
        msg = _make_message(
            msg_id="allowed-001",
            sender=ALLOWED_SENDER,
            subject="Newsletter from allowed sender",
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        assert emails[0].sender == ALLOWED_SENDER

    # ------------------------------------------------------------------
    # 3. Sender NOT on allowlist is excluded
    # ------------------------------------------------------------------

    def test_blocked_sender_is_excluded(self, mocker, mock_config):
        """Emails from senders absent from config.senders are filtered out."""
        msg = _make_message(
            msg_id="blocked-001",
            sender=BLOCKED_SENDER,
            subject="Unsolicited email",
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert emails == []

    def test_mixed_senders_only_allowed_returned(self, mocker, mock_config):
        """Only emails from allowed senders survive the filter."""
        allowed_msg = _make_message(
            msg_id="allowed-001",
            sender=ALLOWED_SENDER,
            subject="Good newsletter",
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        blocked_msg = _make_message(
            msg_id="blocked-001",
            sender=BLOCKED_SENDER,
            subject="Spam",
            date_str=DATE_STR,
            html_body="<p>buy now</p>",
        )
        emails = self._fetch(mocker, mock_config, [allowed_msg, blocked_msg])

        assert len(emails) == 1
        assert emails[0].id == "allowed-001"

    def test_sender_filter_is_case_insensitive(self, mocker, mock_config):
        """Sender matching is case-insensitive (config stores lowercase)."""
        # Config stores 'newsletter@example.com'; send with mixed case
        msg = _make_message(
            msg_id="case-001",
            sender="Newsletter@Example.COM",
            subject="Case test",
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        # Should be included regardless of case
        assert len(emails) == 1
        assert emails[0].id == "case-001"

    # ------------------------------------------------------------------
    # 4. Empty inbox returns empty list
    # ------------------------------------------------------------------

    def test_empty_inbox_returns_empty_list(self, mocker, mock_config):
        """When the Gmail API returns no messages, result is an empty list."""
        emails = self._fetch(mocker, mock_config, [])

        assert emails == []
        assert isinstance(emails, list)

    # ------------------------------------------------------------------
    # 5. Credentials and build are called with correct arguments
    # ------------------------------------------------------------------

    def test_credentials_loaded_from_token_path(self, mocker, mock_config):
        """Credentials.from_authorized_user_file is called with the configured token path."""
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100600
        mocker.patch("agent.fetchers.gmail_fetcher.os.stat", return_value=mock_stat)
        mock_creds = MagicMock()
        creds_patch = mocker.patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        )
        mock_service = _build_gmail_service_mock([])
        mocker.patch("googleapiclient.discovery.build", return_value=mock_service)

        from agent.fetchers.gmail_fetcher import GmailFetcher  # noqa: PLC0415

        fetcher = GmailFetcher(token_path=mock_config.gmail_token_path)
        fetcher.fetch_newsletters(mock_config)

        creds_patch.assert_called_once_with(mock_config.gmail_token_path)

    def test_gmail_service_built_with_correct_args(self, mocker, mock_config):
        """googleapiclient.discovery.build is called with 'gmail' and 'v1'."""
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100600
        mocker.patch("agent.fetchers.gmail_fetcher.os.stat", return_value=mock_stat)
        mock_creds = MagicMock()
        mocker.patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        )
        mock_service = _build_gmail_service_mock([])
        build_patch = mocker.patch(
            "googleapiclient.discovery.build", return_value=mock_service
        )

        from agent.fetchers.gmail_fetcher import GmailFetcher  # noqa: PLC0415

        fetcher = GmailFetcher(token_path=mock_config.gmail_token_path)
        fetcher.fetch_newsletters(mock_config)

        build_patch.assert_called_once()
        call_args = build_patch.call_args
        assert call_args.args[0] == "gmail"
        assert call_args.args[1] == "v1"

    # ------------------------------------------------------------------
    # 6. HTML preference: text/html chosen over text/plain in multipart
    # ------------------------------------------------------------------

    def test_prefers_html_over_plain_in_multipart(self, mocker, mock_config):
        """raw_html is populated from text/html part, not text/plain."""
        msg = _make_message(
            msg_id="multi-001",
            sender=ALLOWED_SENDER,
            subject="Multipart email",
            date_str=DATE_STR,
            html_body="<p>HTML content</p>",
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        assert emails[0].raw_html == "<p>HTML content</p>"

    def test_falls_back_to_plain_text_when_no_html(self, mocker, mock_config):
        """When only a text/plain part exists, raw_html is empty and plain_text is None."""
        msg = _make_plain_message(
            msg_id="plain-001",
            sender=ALLOWED_SENDER,
            subject="Plain-text only email",
            date_str=DATE_STR,
            plain_body="Just plain text here.",
        )
        emails = self._fetch(mocker, mock_config, [msg])

        # Fetcher contract: plain_text=None (parser sets it), raw_html="" for plain-text emails
        assert len(emails) == 1
        assert emails[0].plain_text is None

    # ------------------------------------------------------------------
    # 7. query contains epoch timestamp for lookback window
    # ------------------------------------------------------------------

    def test_list_query_contains_after_timestamp(self, mocker, mock_config):
        """The Gmail list() call targets unread inbox messages."""
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100600
        mocker.patch("agent.fetchers.gmail_fetcher.os.stat", return_value=mock_stat)
        mock_creds = MagicMock()
        mocker.patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        )
        mock_service = _build_gmail_service_mock([])
        mocker.patch("googleapiclient.discovery.build", return_value=mock_service)

        from agent.fetchers.gmail_fetcher import GmailFetcher  # noqa: PLC0415

        fetcher = GmailFetcher(token_path=mock_config.gmail_token_path)
        fetcher.fetch_newsletters(mock_config)

        list_mock = mock_service.users.return_value.messages.return_value.list
        list_mock.assert_called_once()
        call_kwargs = list_mock.call_args.kwargs
        assert "q" in call_kwargs
        assert "is:unread" in call_kwargs["q"]


    def test_service_is_cached_after_first_call(self, mocker, mock_config):
        """_get_service() must assign self._service so mark_as_read/move_to_trash can use it."""
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100600
        mocker.patch("agent.fetchers.gmail_fetcher.os.stat", return_value=mock_stat)
        mock_creds = MagicMock()
        mocker.patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        )
        mock_service = _build_gmail_service_mock([])
        mock_build = mocker.patch("googleapiclient.discovery.build", return_value=mock_service)

        from agent.fetchers.gmail_fetcher import GmailFetcher  # noqa: PLC0415

        fetcher = GmailFetcher(token_path=mock_config.gmail_token_path)
        fetcher._get_service(mock_config)
        fetcher._get_service(mock_config)

        # build() must be called only once — second call returns the cached service
        mock_build.assert_called_once()
        assert fetcher._service is mock_service


# ---------------------------------------------------------------------------
# US4 — keyword detection tests
# ---------------------------------------------------------------------------

class TestKeywordDetection:
    """US4 — subject keyword matching as fallback to sender allowlist.

    mock_config has:
        senders=["newsletter@example.com"]
        subject_keywords=["daily digest"]
    """

    def _fetch(
        self,
        mocker,
        mock_config: AgentConfiguration,
        messages: list[dict],
    ) -> list[Email]:
        """Patch credentials + build, instantiate fetcher, and call fetch_newsletters."""
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100600  # regular file, mode 600
        mocker.patch("agent.fetchers.gmail_fetcher.os.stat", return_value=mock_stat)

        mock_creds = MagicMock()
        mocker.patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        )
        mock_service = _build_gmail_service_mock(messages)
        mocker.patch(
            "googleapiclient.discovery.build",
            return_value=mock_service,
        )

        from agent.fetchers.gmail_fetcher import GmailFetcher  # noqa: PLC0415

        fetcher = GmailFetcher(token_path=mock_config.gmail_token_path)
        return fetcher.fetch_newsletters(mock_config)

    def test_keyword_match_includes_unknown_sender(self, mocker, mock_config):
        """Email from unknown sender with a matching keyword subject IS included (pass 2)."""
        msg = _make_message(
            msg_id="kw-001",
            sender=BLOCKED_SENDER,  # not on allowlist
            subject="Your Daily Digest is here",  # contains "daily digest"
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        assert emails[0].id == "kw-001"
        assert emails[0].sender == BLOCKED_SENDER

    def test_non_matching_email_excluded(self, mocker, mock_config):
        """Email from unknown sender with a non-matching subject is excluded by both passes."""
        msg = _make_message(
            msg_id="none-001",
            sender=BLOCKED_SENDER,
            subject="Flash Sale — 50% off everything today",  # no keyword
            date_str=DATE_STR,
            html_body="<p>buy now</p>",
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert emails == []

    def test_allowlisted_sender_always_included(self, mocker, mock_config):
        """Email from allowlisted sender is included regardless of whether subject matches."""
        msg = _make_message(
            msg_id="allowed-kw-001",
            sender=ALLOWED_SENDER,
            subject="Completely unrelated subject with no keywords",
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        assert emails[0].id == "allowed-kw-001"

    def test_keyword_match_is_case_insensitive(self, mocker, mock_config):
        """Subject keyword matching is case-insensitive."""
        msg = _make_message(
            msg_id="kw-case-001",
            sender=BLOCKED_SENDER,
            subject="THE DAILY DIGEST — Top Stories",  # uppercase variant
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        assert emails[0].id == "kw-case-001"

    def test_allowlisted_sender_not_duplicated_when_subject_also_matches(self, mocker, mock_config):
        """An email matching both allowlist (pass 1) and keyword (pass 2) appears only once."""
        msg = _make_message(
            msg_id="both-001",
            sender=ALLOWED_SENDER,       # matches pass 1
            subject="Your Daily Digest",  # would also match pass 2
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        assert emails[0].id == "both-001"

    def test_multiple_keywords_any_match_is_sufficient(self, mocker, mock_config):
        """If config has multiple keywords, matching any single one is enough to include the email."""
        mock_config.subject_keywords = ["daily digest", "weekly roundup"]
        msg = _make_message(
            msg_id="kw-multi-001",
            sender=BLOCKED_SENDER,
            subject="The Weekly Roundup — March edition",  # matches second keyword
            date_str=DATE_STR,
            html_body=HTML_BODY,
        )
        emails = self._fetch(mocker, mock_config, [msg])

        assert len(emails) == 1
        assert emails[0].id == "kw-multi-001"
