"""Funding rate monitor -- streams funding rates for all perpetual pairs.

Uses REST polling (not WebSocket) for Phase 1. The research confirms funding
rates change slowly (every 8h), so 30-second REST polling is sufficient.
WebSocket streaming can be added in Phase 2 for lower latency.

BYBIT CONVENTION: Positive funding rate means longs pay shorts.
Our strategy: LONG spot + SHORT perp = we COLLECT when rate > 0.
"""

import asyncio
import time

from decimal import Decimal

from bot.exchange.client import ExchangeClient
from bot.logging import get_logger
from bot.market_data.ticker_service import TickerService
from bot.models import FundingRateData

logger = get_logger(__name__)


class FundingMonitor:
    """Monitors and caches funding rates for all perpetual pairs.

    Fetches tickers via REST polling at a configurable interval,
    extracts funding rate data, and updates a shared TickerService
    with the latest prices.
    """

    def __init__(
        self,
        exchange: ExchangeClient,
        ticker_service: TickerService,
        poll_interval: float = 30.0,
    ) -> None:
        self._exchange = exchange
        self._ticker_service = ticker_service
        self._poll_interval = poll_interval
        self._funding_rates: dict[str, FundingRateData] = {}
        self._running = False
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]

    async def start(self) -> None:
        """Begin streaming funding rates in the background."""
        if self._running:
            logger.warning("funding_monitor_already_running")
            return
        self._running = True
        self._task = asyncio.create_task(self._stream_loop())
        logger.info("funding_monitor_started", poll_interval=self._poll_interval)

    async def stop(self) -> None:
        """Stop the funding rate monitor gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("funding_monitor_stopped")

    async def _stream_loop(self) -> None:
        """Main polling loop: fetch tickers, parse funding rates, update caches."""
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "funding_monitor_poll_error",
                    exc_info=True,
                )
            if self._running:
                await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        """Execute a single poll: fetch all linear tickers and update caches."""
        tickers = await self._exchange.fetch_tickers(
            params={"category": "linear"}
        )

        now = time.time()
        updated = 0

        for symbol, ticker in tickers.items():
            info = ticker.get("info", {})
            raw_rate = info.get("fundingRate")

            if raw_rate is None:
                continue

            try:
                funding_rate = Decimal(str(raw_rate))
            except Exception:
                logger.warning("invalid_funding_rate", symbol=symbol, raw=raw_rate)
                continue

            # Parse next funding time and interval
            next_funding_time = int(info.get("nextFundingTime", 0))
            interval_hours = int(info.get("fundingIntervalHour", 8))

            # Extract last price
            last_price_raw = ticker.get("last")
            if last_price_raw is not None:
                try:
                    last_price = Decimal(str(last_price_raw))
                except Exception:
                    last_price = Decimal("0")
            else:
                last_price = Decimal("0")

            # Volume
            volume_raw = info.get("volume24h", 0)
            try:
                volume_24h = Decimal(str(volume_raw))
            except Exception:
                volume_24h = Decimal("0")

            self._funding_rates[symbol] = FundingRateData(
                symbol=symbol,
                rate=funding_rate,
                next_funding_time=next_funding_time,
                interval_hours=interval_hours,
                mark_price=last_price,
                volume_24h=volume_24h,
                updated_at=now,
            )

            # Update shared price cache
            if last_price > 0:
                await self._ticker_service.update_price(symbol, last_price, now)

            updated += 1

        logger.debug("funding_rates_updated", count=updated)

    def get_all_funding_rates(self) -> list[FundingRateData]:
        """Return all cached funding rates, sorted by rate descending."""
        return sorted(
            self._funding_rates.values(),
            key=lambda x: x.rate,
            reverse=True,
        )

    def get_funding_rate(self, symbol: str) -> FundingRateData | None:
        """Return the cached funding rate for a specific symbol."""
        return self._funding_rates.get(symbol)

    def get_profitable_pairs(self, min_rate: Decimal) -> list[FundingRateData]:
        """Return pairs with funding rate above threshold, sorted descending.

        Args:
            min_rate: Minimum funding rate (e.g., Decimal("0.0003") for 0.03%).

        Returns:
            List of FundingRateData for profitable pairs, sorted by rate descending.
        """
        return sorted(
            [fr for fr in self._funding_rates.values() if fr.rate >= min_rate],
            key=lambda x: x.rate,
            reverse=True,
        )
