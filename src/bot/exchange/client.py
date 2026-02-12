"""Abstract exchange client interface.

Defines the contract for all exchange implementations.
Strategy and execution code depends only on this interface,
keeping Bybit-specific details isolated in the concrete implementation.
"""

from abc import ABC, abstractmethod

from bot.exchange.types import InstrumentInfo


class ExchangeClient(ABC):
    """Abstract base class for exchange API clients."""

    @abstractmethod
    async def connect(self) -> None:
        """Initialize connection and load markets/instruments."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (CRITICAL for ccxt async)."""
        ...

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> dict:
        """Fetch current ticker data for a single symbol."""
        ...

    @abstractmethod
    async def fetch_tickers(
        self, symbols: list[str] | None = None, params: dict | None = None
    ) -> dict:
        """Fetch ticker data for multiple symbols."""
        ...

    @abstractmethod
    async def fetch_perpetual_symbols(self) -> list[str]:
        """Return list of all available linear perpetual symbols."""
        ...

    @abstractmethod
    async def get_instrument_info(self, symbol: str) -> InstrumentInfo:
        """Get trading constraints for a symbol (lot size, tick size, etc.)."""
        ...

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: float | None = None,
        params: dict | None = None,
    ) -> dict:
        """Place an order on the exchange."""
        ...

    @abstractmethod
    async def cancel_order(
        self, order_id: str, symbol: str, params: dict | None = None
    ) -> dict:
        """Cancel an open order."""
        ...

    @abstractmethod
    async def fetch_balance(self) -> dict:
        """Fetch account balance."""
        ...

    @abstractmethod
    async def load_markets(self) -> dict:
        """Load and cache market/instrument data from the exchange."""
        ...

    @abstractmethod
    async def fetch_wallet_balance_raw(self) -> dict:
        """Fetch raw wallet balance data for margin monitoring.

        Returns a dict containing exchange-specific fields:
            - accountMMRate: Current maintenance margin rate as string
            - totalMaintenanceMargin: Total maintenance margin in USD as string
            - totalEquity: Total account equity in USD as string
            - totalAvailableBalance: Available balance in USD as string
        """
        ...

    @abstractmethod
    async def fetch_funding_rate_history(
        self,
        symbol: str,
        limit: int = 200,
        params: dict | None = None,
    ) -> list[dict]:
        """Fetch historical funding rate records.

        Returns list of dicts with keys: symbol, fundingRate, timestamp, datetime, info.
        Bybit max limit: 200 records per call.

        Pagination is NOT handled here -- callers are responsible for
        iterating with appropriate cursor/since parameters.
        """
        ...

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: int | None = None,
        limit: int = 1000,
        params: dict | None = None,
    ) -> list[list]:
        """Fetch OHLCV candle data.

        Returns list of [timestamp_ms, open, high, low, close, volume].
        Bybit max limit: 1000 records per call.

        Pagination is NOT handled here -- callers are responsible for
        iterating with appropriate since parameters.
        """
        ...

    @abstractmethod
    def get_markets(self) -> dict:
        """Return the cached markets dict from load_markets().

        This is synchronous since markets are loaded at connect() time.
        Used by OpportunityRanker to derive spot symbols without
        triggering new API calls.
        """
        ...
