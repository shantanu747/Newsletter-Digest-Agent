"""SMTP-based email delivery for the assembled HTML digest."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from agent.utils.config import AgentConfiguration
from agent.utils.exceptions import DeliveryError
from agent.utils.logger import get_logger

log = get_logger(__name__)


class EmailDelivery:
    """Delivers an HTML digest via SMTP with one automatic retry."""

    def __init__(self, config: AgentConfiguration | None = None) -> None:
        """Optionally store config at construction time.

        If config is provided here, send() can be called without the config argument.
        """
        self._config = config

    def send(
        self,
        html_body: str,
        subject: str,
        config: AgentConfiguration | None = None,
    ) -> None:
        """Send the digest email to the configured recipient.

        Args:
            html_body: Fully rendered HTML string.
            subject: Subject line for the outgoing email.
            config: AgentConfiguration. If omitted, uses the config passed to __init__.

        Raises:
            DeliveryError: If delivery fails on both the initial attempt and the retry.
        """
        cfg = config or self._config
        if cfg is None:
            raise DeliveryError("No AgentConfiguration provided to EmailDelivery")

        msg = MIMEMultipart("alternative")
        msg["From"] = cfg.smtp_user
        msg["To"] = cfg.delivery_recipient
        msg["Subject"] = subject

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        for attempt in range(2):
            try:
                with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
                    server.starttls()
                    server.login(cfg.smtp_user, cfg.smtp_password)
                    server.sendmail(cfg.smtp_user, cfg.delivery_recipient, msg.as_string())
                log.info("digest_delivered", recipient=cfg.delivery_recipient, attempt=attempt + 1)
                return
            except smtplib.SMTPException as exc:
                log.warning("smtp_error", attempt=attempt + 1, error=str(exc))

        raise DeliveryError("Failed to deliver digest after 2 attempts")
