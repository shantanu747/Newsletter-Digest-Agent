"""Custom exception hierarchy for the Newsletter Digest Agent."""


class NewsletterAgentError(Exception):
    """Base class for all agent errors."""


class ConfigurationError(NewsletterAgentError):
    """Raised when configuration is missing, invalid, or incomplete."""


class FetchError(NewsletterAgentError):
    """Raised on unrecoverable failure to fetch emails from Gmail."""


class SummarizationError(NewsletterAgentError):
    """Raised when AI summarization fails after all retry attempts."""


class DeliveryError(NewsletterAgentError):
    """Raised when digest email delivery fails after retry."""
