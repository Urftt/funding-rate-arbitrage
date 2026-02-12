"""Time-bounded data store wrapper for backtest mode.

Wraps HistoricalDataStore and automatically caps all read queries at the
current simulated time. This prevents look-ahead bias by ensuring signal
calculations only see data that would have been available at each point
in the backtest.

BKTS-01: No look-ahead bias -- all queries time-bounded.
"""

from bot.data.models import HistoricalFundingRate, OHLCVCandle
from bot.data.store import HistoricalDataStore
from bot.logging import get_logger

logger = get_logger(__name__)


class BacktestDataStoreWrapper:
    """Wrapper around HistoricalDataStore that enforces time boundaries.

    The SignalEngine calls data_store.get_funding_rates(symbol=...) without
    time bounds. This wrapper intercepts those calls and caps until_ms at
    the current simulated time, preventing the signal engine from seeing
    future data.

    Only read methods used by SignalEngine are wrapped. Write methods are
    not implemented (backtest only reads pre-loaded data).

    Args:
        store: The real HistoricalDataStore to delegate to.
    """

    def __init__(self, store: HistoricalDataStore) -> None:
        self._store = store
        self._current_time_ms: int = 0

    def set_current_time(self, timestamp_ms: int) -> None:
        """Advance the simulated clock.

        All subsequent read queries will be capped at this timestamp.

        Args:
            timestamp_ms: Current backtest time in milliseconds.
        """
        self._current_time_ms = timestamp_ms

    async def get_funding_rates(
        self,
        symbol: str,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> list[HistoricalFundingRate]:
        """Query funding rates, capping until_ms at current simulated time.

        Delegates to the underlying store with time boundary enforcement.

        Args:
            symbol: Trading pair symbol.
            since_ms: Optional start time filter.
            until_ms: Optional end time filter (will be capped at current time).

        Returns:
            List of HistoricalFundingRate within the time-bounded range.
        """
        capped_until = self._cap_until(until_ms)
        return await self._store.get_funding_rates(
            symbol=symbol,
            since_ms=since_ms,
            until_ms=capped_until,
        )

    async def get_ohlcv_candles(
        self,
        symbol: str,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> list[OHLCVCandle]:
        """Query OHLCV candles, capping until_ms at current simulated time.

        Delegates to the underlying store with time boundary enforcement.

        Args:
            symbol: Trading pair symbol.
            since_ms: Optional start time filter.
            until_ms: Optional end time filter (will be capped at current time).

        Returns:
            List of OHLCVCandle within the time-bounded range.
        """
        capped_until = self._cap_until(until_ms)
        return await self._store.get_ohlcv_candles(
            symbol=symbol,
            since_ms=since_ms,
            until_ms=capped_until,
        )

    async def get_data_status(self) -> dict:
        """Get aggregate data status (metadata query, not time-sensitive).

        Delegates directly to the underlying store without time filtering.

        Returns:
            Dict with data status information.
        """
        return await self._store.get_data_status()

    async def get_tracked_pairs(self, active_only: bool = True) -> list[dict]:
        """Get tracked pairs (metadata query, not time-sensitive).

        Delegates directly to the underlying store without time filtering.

        Args:
            active_only: If True, only return active pairs.

        Returns:
            List of tracked pair dicts.
        """
        return await self._store.get_tracked_pairs(active_only=active_only)

    def _cap_until(self, until_ms: int | None) -> int:
        """Cap an until_ms parameter at the current simulated time.

        If until_ms is None or exceeds current time, returns current time.
        If until_ms is already within bounds, returns it unchanged.

        Args:
            until_ms: The requested upper bound (or None for unbounded).

        Returns:
            The effective upper bound, capped at current simulated time.
        """
        if self._current_time_ms <= 0:
            # No time set yet; if until_ms provided, use it; otherwise no cap
            return until_ms if until_ms is not None else 0

        if until_ms is None:
            return self._current_time_ms

        return min(until_ms, self._current_time_ms)
