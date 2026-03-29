"""Configuration loading — combines newsletters.yaml with environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from agent.utils.exceptions import ConfigurationError
from agent.utils.models import SenderConfig

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

_KNOWN_SENDER_KEYS = {"address", "display_name", "mode", "summary_word_target", "include_images", "max_images"}
_KNOWN_PROFILE_KEYS = {"interests", "portfolio", "watchlist", "custom_prompts"}
_KNOWN_HOLDING_KEYS = {"ticker", "name", "notes"}


@dataclass
class UserProfile:
    """Reader-specific context injected into the advisor prompt."""

    interests: list[str] = field(default_factory=list)
    """Topics and domains the reader cares about (e.g. 'aviation', 'AI')."""

    portfolio: list[dict] = field(default_factory=list)
    """Current holdings: [{ticker, name, notes?}, ...]."""

    watchlist: list[dict] = field(default_factory=list)
    """Stocks being watched but not held: [{ticker, name}, ...]."""

    custom_prompts: list[str] = field(default_factory=list)
    """Free-text instructions appended directly to the advisor prompt."""


@dataclass
class AgentConfiguration:
    # Detection
    senders: list[SenderConfig] = field(default_factory=list)
    subject_keywords: list[str] = field(default_factory=list)

    # Fetch behaviour
    poll_interval_hours: int = 4
    batch_size: int = 10
    max_newsletters_per_run: int = 20

    # Summarization
    summary_word_target: int = 225
    summary_length_mode: str = "fixed"   # "fixed" | "percentage"
    summary_percentage: int = 18
    summary_min_words: int = 100
    summary_max_words: int = 500

    # Schedule
    schedule_timezone: str = "UTC"

    # Personalization
    user_profile: UserProfile | None = None
    """Reader profile for the advisor layer. None disables all personalization."""

    # Secrets (from env)
    anthropic_api_key: str = ""
    gmail_token_path: str = "token.json"
    delivery_recipient: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""


def _parse_sender(raw: dict) -> SenderConfig:
    """Parse a single sender YAML entry into a SenderConfig.

    Warns on unknown keys but does not raise. Raises ConfigurationError on invalid mode.
    """
    from agent.utils.logger import get_logger
    log = get_logger(__name__)

    unknown = set(raw.keys()) - _KNOWN_SENDER_KEYS
    if unknown:
        log.warning("unknown_sender_config_keys", keys=sorted(unknown))

    address = raw.get("address", "")
    if not address:
        raise ConfigurationError("Sender entry is missing required 'address' field.")

    mode = raw.get("mode", "summarize")
    if mode not in ("pass_through", "summarize"):
        raise ConfigurationError(
            f"Invalid sender mode '{mode}' for address '{address}'. "
            "Must be 'pass_through' or 'summarize'."
        )

    summary_word_target = raw.get("summary_word_target")
    if summary_word_target is not None:
        try:
            summary_word_target = int(summary_word_target)
        except (ValueError, TypeError):
            raise ConfigurationError(
                f"summary_word_target for '{address}' must be a valid integer, got '{summary_word_target}'."
            )
        if summary_word_target < 50:
            raise ConfigurationError(
                f"summary_word_target for '{address}' must be >= 50, got {summary_word_target}."
            )

    max_images = raw.get("max_images")
    if max_images is not None:
        max_images = int(max_images)
        if max_images < 0:
            raise ConfigurationError(
                f"max_images for '{address}' must be >= 0, got {max_images}."
            )

    return SenderConfig(
        address=address.lower(),
        mode=mode,
        display_name=raw.get("display_name"),
        summary_word_target=summary_word_target,
        include_images=bool(raw.get("include_images", True)),
        max_images=max_images,
    )


def _parse_user_profile(raw: dict) -> UserProfile:
    """Parse the user_profile section of user_profile.yaml into a UserProfile.

    Warns on unknown top-level keys. Raises ConfigurationError if any portfolio
    or watchlist entry is missing 'ticker' or 'name'.
    """
    from agent.utils.logger import get_logger
    log = get_logger(__name__)

    unknown = set(raw.keys()) - _KNOWN_PROFILE_KEYS
    if unknown:
        log.warning("unknown_user_profile_keys", keys=sorted(unknown))

    def _parse_holdings(items: list, section: str) -> list[dict]:
        parsed = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ConfigurationError(
                    f"user_profile.{section}[{i}] must be a mapping, got {type(item).__name__}."
                )
            missing_keys = {"ticker", "name"} - set(item.keys())
            if missing_keys:
                raise ConfigurationError(
                    f"user_profile.{section}[{i}] is missing required field(s): "
                    f"{', '.join(sorted(missing_keys))}."
                )
            unknown_keys = set(item.keys()) - _KNOWN_HOLDING_KEYS
            if unknown_keys:
                log.warning("unknown_holding_keys", section=section, keys=sorted(unknown_keys))
            parsed.append({k: v for k, v in item.items()})
        return parsed

    return UserProfile(
        interests=[str(i) for i in (raw.get("interests") or [])],
        portfolio=_parse_holdings(raw.get("portfolio") or [], "portfolio"),
        watchlist=_parse_holdings(raw.get("watchlist") or [], "watchlist"),
        custom_prompts=[str(p) for p in (raw.get("custom_prompts") or [])],
    )


def load_config(yaml_path: str = "config/newsletters.yaml", profile_path: str = "config/user_profile.yaml") -> AgentConfiguration:
    """Load configuration from YAML file and environment variables.

    Optionally loads a user profile from profile_path (default:
    config/user_profile.yaml). If the profile file is absent, personalization
    is silently disabled (cfg.user_profile stays None).

    Raises ConfigurationError if any required ENV variable is missing or empty,
    or if either YAML file is malformed.
    """
    path = Path(yaml_path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {yaml_path}")

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Malformed YAML in {yaml_path}: {exc}") from exc

    schedule = raw.get("schedule", {}) or {}

    # Parse senders — support both new dict format and legacy flat string list
    raw_senders = raw.get("senders") or []
    senders: list[SenderConfig] = []
    for entry in raw_senders:
        if isinstance(entry, str):
            # Legacy flat string format — treat as summarize mode
            senders.append(SenderConfig(address=entry.lower(), mode="summarize"))
        elif isinstance(entry, dict):
            senders.append(_parse_sender(entry))
        else:
            raise ConfigurationError(f"Unexpected sender entry type: {type(entry)}")

    batch_size = int(raw.get("batch_size", 10))
    if batch_size < 1:
        raise ConfigurationError(f"batch_size must be >= 1, got {batch_size}.")

    cfg = AgentConfiguration(
        senders=senders,
        subject_keywords=[kw.lower() for kw in (raw.get("subject_keywords") or [])],
        poll_interval_hours=int(raw.get("poll_interval_hours", 4)),
        batch_size=batch_size,
        max_newsletters_per_run=int(raw.get("max_newsletters_per_run", 20)),
        summary_word_target=int(raw.get("summary_word_target", 225)),
        summary_length_mode=str(raw.get("summary_length_mode", "fixed")),
        summary_percentage=int(raw.get("summary_percentage", 18)),
        summary_min_words=int(raw.get("summary_min_words", 100)),
        summary_max_words=int(raw.get("summary_max_words", 500)),
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

    # Optionally load the user profile for advisor personalization
    profile_file = Path(profile_path)
    if profile_file.exists():
        try:
            profile_raw = yaml.safe_load(profile_file.read_text()) or {}
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Malformed YAML in {profile_path}: {exc}") from exc
        cfg.user_profile = _parse_user_profile(profile_raw.get("user_profile") or {})

    return cfg
