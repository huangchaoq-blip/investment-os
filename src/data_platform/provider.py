"""Provider-neutral canonical market-data acquisition interface."""

from abc import ABC, abstractmethod

from .models import DailyBarRequest, ProviderCapabilities, ProviderFetchResult


class CanonicalMarketDataProvider(ABC):
    """Boundary consumed by future publication services through dependency injection."""

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Return stable identity, qualification, and limitation information."""

    @abstractmethod
    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderFetchResult:
        """Fetch a full-bootstrap daily-bar request without publishing a dataset."""

    @abstractmethod
    def fetch_incremental_daily_bars(
        self, request: DailyBarRequest
    ) -> ProviderFetchResult:
        """Fetch an incremental daily-bar request without publishing a dataset."""

    @abstractmethod
    def fetch_corporate_actions(self, request: DailyBarRequest) -> ProviderFetchResult:
        """Fetch canonical corporate-action evidence when the provider supports it."""
