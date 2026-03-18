"""Unit tests for EmailDelivery.

Tests cover:
- Happy path: SMTP connection is set up and sendmail called with correct arguments
- Retry success: sendmail raises SMTPException on first call, succeeds on second
- Both attempts fail: DeliveryError raised after two consecutive SMTPExceptions
"""

import smtplib
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest

from agent.utils.exceptions import DeliveryError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_smtp_context_manager(mock_smtp_instance: MagicMock):
    """Return a mock that behaves as an smtplib.SMTP context manager."""
    mock_smtp_cls = MagicMock()
    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp_instance)
    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_smtp_cls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEmailDeliveryHappyPath:
    """Successful delivery: SMTP handshake and sendmail complete in one attempt."""

    def test_starttls_called_once(self, mocker, mock_config):
        """starttls() is called exactly once during successful delivery."""
        mock_smtp_instance = MagicMock()
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)
        delivery.send(
            subject="Test Digest",
            html_body="<html><body>Hello</body></html>",
        )

        mock_smtp_instance.starttls.assert_called_once()

    def test_login_called_with_credentials(self, mocker, mock_config):
        """login() is called with the SMTP username and password from config."""
        mock_smtp_instance = MagicMock()
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)
        delivery.send(
            subject="Test Digest",
            html_body="<html><body>Hello</body></html>",
        )

        mock_smtp_instance.login.assert_called_once_with(
            mock_config.smtp_user,
            mock_config.smtp_password,
        )

    def test_sendmail_called_once(self, mocker, mock_config):
        """sendmail() is called exactly once on a successful first attempt."""
        mock_smtp_instance = MagicMock()
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)
        delivery.send(
            subject="Test Digest",
            html_body="<html><body>Hello</body></html>",
        )

        mock_smtp_instance.sendmail.assert_called_once()

    def test_sendmail_called_with_correct_addresses(self, mocker, mock_config):
        """sendmail() receives from_addr and to_addr from config."""
        mock_smtp_instance = MagicMock()
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)
        delivery.send(
            subject="Test Digest",
            html_body="<html><body>Hello</body></html>",
        )

        positional_args = mock_smtp_instance.sendmail.call_args[0]
        from_addr, to_addr = positional_args[0], positional_args[1]
        assert from_addr == mock_config.smtp_user
        assert to_addr == mock_config.delivery_recipient

    def test_smtp_constructed_with_host_and_port(self, mocker, mock_config):
        """smtplib.SMTP is constructed with the configured host and port."""
        mock_smtp_instance = MagicMock()
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        patched = mocker.patch("smtplib.SMTP", mock_smtp_cls)

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)
        delivery.send(
            subject="Test Digest",
            html_body="<html><body>Hello</body></html>",
        )

        patched.assert_called_once_with(mock_config.smtp_host, mock_config.smtp_port)


class TestEmailDeliveryRetryOnSMTPException:
    """sendmail retries once after SMTPException."""

    def test_sendmail_called_twice_on_first_failure(self, mocker, mock_config):
        """sendmail() is called twice when the first attempt raises SMTPException."""
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.side_effect = [
            smtplib.SMTPException("Temporary failure"),
            None,  # second call succeeds
        ]
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)
        mocker.patch("time.sleep")

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)
        # Should NOT raise
        delivery.send(
            subject="Test Digest",
            html_body="<html><body>Hello</body></html>",
        )

        assert mock_smtp_instance.sendmail.call_count == 2

    def test_no_exception_raised_when_retry_succeeds(self, mocker, mock_config):
        """No exception propagates when the retry attempt succeeds."""
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.side_effect = [
            smtplib.SMTPException("Temporary failure"),
            None,
        ]
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)
        mocker.patch("time.sleep")

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)

        # Should complete without raising
        delivery.send(
            subject="Test Digest",
            html_body="<html><body>Hello</body></html>",
        )


class TestEmailDeliveryBothAttemptsFail:
    """DeliveryError raised when both sendmail attempts raise SMTPException."""

    def test_delivery_error_raised_after_two_failures(self, mocker, mock_config):
        """DeliveryError is raised when every sendmail call fails."""
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.side_effect = smtplib.SMTPException("Persistent failure")
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)
        mocker.patch("time.sleep")

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)

        with pytest.raises(DeliveryError):
            delivery.send(
                subject="Test Digest",
                html_body="<html><body>Hello</body></html>",
            )

    def test_sendmail_attempted_twice_before_raising(self, mocker, mock_config):
        """sendmail() is attempted twice before DeliveryError is raised."""
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.side_effect = smtplib.SMTPException("Persistent failure")
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)
        mocker.patch("time.sleep")

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)

        with pytest.raises(DeliveryError):
            delivery.send(
                subject="Test Digest",
                html_body="<html><body>Hello</body></html>",
            )

        assert mock_smtp_instance.sendmail.call_count == 2

    def test_delivery_error_not_smtp_exception(self, mocker, mock_config):
        """The raised exception is DeliveryError, not raw SMTPException."""
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.side_effect = smtplib.SMTPException("Persistent failure")
        mock_smtp_cls = _make_smtp_context_manager(mock_smtp_instance)
        mocker.patch("smtplib.SMTP", mock_smtp_cls)
        mocker.patch("time.sleep")

        from agent.digest.delivery import EmailDelivery

        delivery = EmailDelivery(config=mock_config)

        with pytest.raises(DeliveryError):
            delivery.send(
                subject="Test Digest",
                html_body="<html><body>Hello</body></html>",
            )
