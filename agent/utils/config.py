"""Configuration loading — combines newsletters.yaml with environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agent.utils.exceptions import ConfigurationError

load_dotenv()

_REQUIRED_ENV = [
    "ANTHROPIC_API_KEY",
    "GMAIL_OAUTH_TOKEN_PATH",
    "DELIVERY_EMAIL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
]


@dataclass
class AgentConfiguration:
    # Detection
    senders: list[str] = field(default_factory=list)
    subject_keywords: list[str] = field(default_factory=list)

    # Fetch behaviour
    lookback_hours: int = 24
    max_newsletters_per_run: int = 20

    # Summarization
    summary_word_target: int = 225
    summary_length_mode: str = "fixed"   # "fixed" | "percentage"
    summary_percentage: int = 18
    summary_min_words: int = 100
    summary_max_words: int = 500

    # Schedule
    schedule_hour: int = 6
    schedule_minute: int = 30
    schedule_timezone: str = "UTC"

    # Secrets (from env)
    anthropic_api_key: str = ""
    gmail_token_path: str = "token.json"
    delivery_recipient: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""


def load_config(yaml_path: str = "config/newsletters.yaml") -> AgentConfiguration:
    """Load configuration from YAML file and environment variables.

    Raises ConfigurationError if any required ENV variable is missing or empty,
    or if the YAML file is missing / malformed.
    """
    path = Path(yaml_path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {yaml_path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Malformed YAML in {yaml_path}: {exc}") from exc

    schedule = raw.get("schedule", {}) or {}

    cfg = AgentConfiguration(
        senders=[s.lower() for s in (raw.get("senders") or [])],
        subject_keywords=[kw.lower() for kw in (raw.get("subject_keywords") or [])],
        lookback_hours=int(raw.get("lookback_hours", 24)),
        max_newsletters_per_run=int(raw.get("max_newsletters_per_run", 20)),
        summary_word_target=int(raw.get("summary_word_target", 225)),
        summary_length_mode=str(raw.get("summary_length_mode", "fixed")),
        summary_percentage=int(raw.get("summary_percentage", 18)),
        summary_min_words=int(raw.get("summary_min_words", 100)),
        summary_max_words=int(raw.get("summary_max_words", 500)),
        schedule_hour=int(schedule.get("hour", 6)),
        schedule_minute=int(schedule.get("minute", 30)),
        schedule_timezone=str(schedule.get("timezone", "UTC")),
    )

    # Validate required env vars — treat blank strings the same as missing
    missing = [key for key in _REQUIRED_ENV if not (os.getenv(key) or "").strip()]
    if missing:
        raise ConfigurationError(
            f"Missing or empty environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in all values."
        )

    smtp_port = int(os.environ["SMTP_PORT"])
    if not 1 <= smtp_port <= 65535:
        raise ConfigurationError(
            f"SMTP_PORT must be between 1 and 65535, got {smtp_port}"
        )

    cfg.anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    cfg.gmail_token_path = os.environ["GMAIL_OAUTH_TOKEN_PATH"]
    cfg.delivery_recipient = os.environ["DELIVERY_EMAIL"]
    cfg.smtp_host = os.environ["SMTP_HOST"]
    cfg.smtp_port = smtp_port
    cfg.smtp_user = os.environ["SMTP_USER"]
    cfg.smtp_password = os.environ["SMTP_PASSWORD"]

    if not cfg.senders and not cfg.subject_keywords:
        from agent.utils.logger import get_logger
        get_logger(__name__).warning(
            "no_detection_rules",
            message="Both senders and subject_keywords are empty — no newsletters will be fetched.",
        )

    return cfg
