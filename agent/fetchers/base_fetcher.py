"""Abstract base class for newsletter fetchers."""

from abc import ABC, abstractmethod

from agent.utils.models import Email


class BaseFetcher(ABC):
    """Abstract fetcher — all email source integrations must implement this."""

    @abstractmethod
    def fetch_newsletters(self, config: "AgentConfiguration") -> list[Email]:  # noqa: F821
        """Fetch newsletters matching the detection rules in config.

        Returns a list of Email objects with plain_text=None (pre-parsing).
        Raises FetchError on unrecoverable failure.
        """
