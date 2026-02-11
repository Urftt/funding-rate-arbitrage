"""Shared in-memory price cache for market data consumers.

Provides a thread-safe (async-safe via asyncio.Lock) price cache that the
FundingMonitor updates and other components (e.g., PaperExecutor) read from.

This solves Open Question #3 from research: shared price cache between
funding monitor and paper executor without tight coupling.
"""

import asyncio
import time

from decimal import Decimal

from bot.logging import get_logger

logger = get_logger(__name__)


class TickerService:
    """Shared in-memory price cache with staleness detection.

    Stores the latest price and timestamp for each symbol.
    Uses asyncio.Lock for safe concurrent reads/writes from multiple coroutines.
    """

    def __init__(self) -> None:
        self._prices: dict[str, tuple[Decimal, float]] = {}
        self._lock = asyncio.Lock()

    async def update_price(self, symbol: str, price: Decimal, timestamp: float) -> None:
        """Store the latest price for a symbol.

        Args:
            symbol: The trading pair symbol (e.g., "BTC/USDT:USDT").
            price: The latest price as Decimal.
            timestamp: Unix timestamp of the price update.
        """
        async with self._lock:
            self._prices[symbol] = (price, timestamp)

    async def get_price(self, symbol: str) -> Decimal | None:
        """Return the latest cached price for a symbol, or None if not cached."""
        async with self._lock:
            entry = self._prices.get(symbol)
            return entry[0] if entry is not None else None

    async def get_price_age(self, symbol: str) -> float | None:
        """Return seconds since the last price update for a symbol.

        Returns None if the symbol has no cached price.
        """
        async with self._lock:
            entry = self._prices.get(symbol)
            if entry is None:
                return None
            return time.time() - entry[1]

    async def is_stale(self, symbol: str, max_age_seconds: float = 60.0) -> bool:
        """Check if a cached price is stale or missing.

        Returns True if:
        - The symbol has no cached price, or
        - The cached price is older than max_age_seconds.
        """
        age = await self.get_price_age(symbol)
        if age is None:
            return True
        return age > max_age_seconds
