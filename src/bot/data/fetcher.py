"""Paginated historical data fetch pipeline with retry, resume, and progress logging.

Orchestrates fetching historical funding rates and OHLCV candles from the exchange
API, storing them via HistoricalDataStore. Handles backward pagination, exponential
backoff retry, fetch state resume, and per-pair progress logging.

CRITICAL implementation notes (from research):
- Always pass endTime to Bybit funding rate history (pitfall #1)
- Dynamic funding intervals: interval stored per record, not assumed 8h (pitfall #2)
- Bybit kline response is REVERSE-SORTED: newest first (pitfall #3)
- Funding rate limit: 200, OHLCV limit: 1000 (pitfall #4)
- Use ccxt unified symbols like BTC/USDT:USDT everywhere (pitfall #5)
"""

import asyncio
import time
from collections.abc import Callable
from decimal import Decimal

import ccxt.async_support

from bot.config import HistoricalDataSettings
from bot.data.store import HistoricalDataStore
from bot.exchange.client import ExchangeClient
from bot.logging import get_logger

logger = get_logger(__name__)


class HistoricalDataFetcher:
    """Fetches historical data from exchange and persists via store.

    Handles paginated backward-walking through Bybit's API, exponential
    backoff retry on errors, fetch state tracking for resume capability,
    and per-pair progress logging.

    Usage:
        fetcher = HistoricalDataFetcher(exchange, store, settings)
        await fetcher.ensure_data_ready(["BTC/USDT:USDT", "ETH/USDT:USDT"])
    """

    def __init__(
        self,
        exchange: ExchangeClient,
        store: HistoricalDataStore,
        settings: HistoricalDataSettings,
    ) -> None:
        self._exchange = exchange
        self._store = store
        self._settings = settings

    # ──────────────────────────────────────────────
    # Public methods
    # ──────────────────────────────────────────────

    async def ensure_data_ready(
        self,
        symbols: list[str],
        progress_callback: Callable | None = None,
    ) -> None:
        """Fetch all missing historical data. Blocks until complete.

        Main entry point called on startup. For each symbol, fetches
        funding rate history and OHLCV candles, then updates tracked pairs.
        """
        start_time = time.monotonic()

        for i, symbol in enumerate(symbols, 1):
            logger.info(
                "fetching_historical_data",
                symbol=symbol,
                progress=f"{i}/{len(symbols)}",
            )
            await self._fetch_funding_history(symbol)
            await self._fetch_ohlcv_history(symbol)

            # Update tracked pair (volume not known here; use 0 as placeholder)
            await self._store.update_tracked_pair(symbol, Decimal("0"))

            if progress_callback is not None:
                await progress_callback(symbol, i, len(symbols))

        duration = time.monotonic() - start_time
        logger.info(
            "historical_data_ready",
            pairs=len(symbols),
            total_duration_seconds=round(duration, 1),
        )

    async def incremental_update(self, symbols: list[str]) -> None:
        """Fetch only new records since last sync for each symbol.

        Called on each scan cycle. Fetches from latest_ms to now.
        Logs at DEBUG level per pair, INFO level for summary.
        """
        now_ms = int(time.time() * 1000)
        total_funding = 0
        total_ohlcv = 0

        for symbol in symbols:
            # Funding rates: fetch from latest to now
            funding_state = await self._store.get_fetch_state(symbol, "funding")
            if funding_state and funding_state["latest_ms"]:
                batch = await self._fetch_with_retry(
                    self._exchange.fetch_funding_rate_history,
                    symbol,
                    limit=200,
                    params={"endTime": now_ms},
                )
                if batch:
                    # Filter to only new records
                    new_records = [
                        r for r in batch if r["timestamp"] > funding_state["latest_ms"]
                    ]
                    if new_records:
                        inserted = await self._store.insert_funding_rates(new_records)
                        total_funding += inserted
                        # Update fetch state with new latest
                        new_latest = max(r["timestamp"] for r in new_records)
                        await self._store.update_fetch_state(
                            symbol,
                            "funding",
                            funding_state["earliest_ms"],
                            new_latest,
                        )
                        logger.debug(
                            "incremental_funding_update",
                            symbol=symbol,
                            new_records=inserted,
                        )

            # OHLCV: fetch from latest to now
            ohlcv_state = await self._store.get_fetch_state(symbol, "ohlcv")
            if ohlcv_state and ohlcv_state["latest_ms"]:
                batch = await self._fetch_with_retry(
                    self._exchange.fetch_ohlcv,
                    symbol,
                    timeframe=self._settings.ohlcv_interval,
                    limit=1000,
                    params={"endTime": now_ms},
                )
                if batch:
                    new_candles = [
                        c for c in batch if c[0] > ohlcv_state["latest_ms"]
                    ]
                    if new_candles:
                        inserted = await self._store.insert_ohlcv_candles(
                            symbol, new_candles
                        )
                        total_ohlcv += inserted
                        new_latest = max(c[0] for c in new_candles)
                        await self._store.update_fetch_state(
                            symbol,
                            "ohlcv",
                            ohlcv_state["earliest_ms"],
                            new_latest,
                        )
                        logger.debug(
                            "incremental_ohlcv_update",
                            symbol=symbol,
                            new_records=inserted,
                        )

        logger.info(
            "incremental_update_complete",
            pairs=len(symbols),
            new_funding_records=total_funding,
            new_ohlcv_records=total_ohlcv,
        )

    # ──────────────────────────────────────────────
    # Internal fetch orchestration
    # ──────────────────────────────────────────────

    async def _fetch_funding_history(self, symbol: str) -> None:
        """Fetch complete funding rate history for a symbol with resume support."""
        now_ms = int(time.time() * 1000)
        since_ms = now_ms - self._settings.lookback_days * 86_400 * 1000

        state = await self._store.get_fetch_state(symbol, "funding")

        if state:
            earliest = state["earliest_ms"]
            latest = state["latest_ms"]

            if earliest <= since_ms:
                # Historical data is complete. Only fetch new data forward.
                if latest < now_ms:
                    new_count = await self._fetch_funding_rates_paginated(
                        symbol, latest, now_ms
                    )
                    if new_count > 0:
                        await self._store.update_fetch_state(
                            symbol, "funding", earliest, now_ms
                        )
                return

            # Need to fetch backward from earliest to since_ms
            backward_count = await self._fetch_funding_rates_paginated(
                symbol, since_ms, earliest
            )
            # Also fetch forward from latest to now
            forward_count = 0
            if latest < now_ms:
                forward_count = await self._fetch_funding_rates_paginated(
                    symbol, latest, now_ms
                )

            new_earliest = since_ms if backward_count > 0 else earliest
            new_latest = now_ms if forward_count > 0 else latest
            await self._store.update_fetch_state(
                symbol, "funding", new_earliest, new_latest
            )
        else:
            # No state: full backward fetch from now to since_ms
            total = await self._fetch_funding_rates_paginated(
                symbol, since_ms, now_ms
            )
            if total > 0:
                await self._store.update_fetch_state(
                    symbol, "funding", since_ms, now_ms
                )

    async def _fetch_ohlcv_history(self, symbol: str) -> None:
        """Fetch complete OHLCV candle history for a symbol with resume support."""
        now_ms = int(time.time() * 1000)
        since_ms = now_ms - self._settings.lookback_days * 86_400 * 1000

        state = await self._store.get_fetch_state(symbol, "ohlcv")

        if state:
            earliest = state["earliest_ms"]
            latest = state["latest_ms"]

            if earliest <= since_ms:
                # Historical data is complete. Only fetch new data forward.
                if latest < now_ms:
                    new_count = await self._fetch_ohlcv_paginated(
                        symbol, latest, now_ms
                    )
                    if new_count > 0:
                        await self._store.update_fetch_state(
                            symbol, "ohlcv", earliest, now_ms
                        )
                return

            # Need to fetch backward from earliest to since_ms
            backward_count = await self._fetch_ohlcv_paginated(
                symbol, since_ms, earliest
            )
            # Also fetch forward from latest to now
            forward_count = 0
            if latest < now_ms:
                forward_count = await self._fetch_ohlcv_paginated(
                    symbol, latest, now_ms
                )

            new_earliest = since_ms if backward_count > 0 else earliest
            new_latest = now_ms if forward_count > 0 else latest
            await self._store.update_fetch_state(
                symbol, "ohlcv", new_earliest, new_latest
            )
        else:
            # No state: full backward fetch from now to since_ms
            total = await self._fetch_ohlcv_paginated(symbol, since_ms, now_ms)
            if total > 0:
                await self._store.update_fetch_state(
                    symbol, "ohlcv", since_ms, now_ms
                )

    # ──────────────────────────────────────────────
    # Paginated fetch methods
    # ──────────────────────────────────────────────

    async def _fetch_funding_rates_paginated(
        self,
        symbol: str,
        since_ms: int,
        until_ms: int,
    ) -> int:
        """Walk BACKWARD from until_ms to since_ms fetching funding rates.

        Uses endTime parameter for backward pagination. Returns total
        records inserted.
        """
        total_inserted = 0
        current_end = until_ms

        while current_end > since_ms:
            batch = await self._fetch_with_retry(
                self._exchange.fetch_funding_rate_history,
                symbol,
                limit=200,
                params={"endTime": current_end},
            )

            if not batch:
                break

            # Filter to only records within our target range
            batch = [r for r in batch if r["timestamp"] >= since_ms]

            if not batch:
                break

            inserted = await self._store.insert_funding_rates(batch)
            total_inserted += inserted

            # Move backward: use the oldest timestamp in this batch
            oldest_ts = min(r["timestamp"] for r in batch)
            if oldest_ts >= current_end:
                break  # No progress guard -- avoid infinite loop

            current_end = oldest_ts

            # Rate limit safety delay between paginated calls
            await asyncio.sleep(self._settings.fetch_batch_delay)

        logger.info(
            "funding_fetch_progress",
            symbol=symbol,
            records_fetched=total_inserted,
        )
        return total_inserted

    async def _fetch_ohlcv_paginated(
        self,
        symbol: str,
        since_ms: int,
        until_ms: int,
    ) -> int:
        """Walk BACKWARD from until_ms to since_ms fetching OHLCV candles.

        Uses endTime parameter for backward pagination. Bybit kline response
        is REVERSE-SORTED (newest first) -- we reverse before processing.
        Returns total records inserted.
        """
        total_inserted = 0
        current_end = until_ms

        while current_end > since_ms:
            batch = await self._fetch_with_retry(
                self._exchange.fetch_ohlcv,
                symbol,
                timeframe=self._settings.ohlcv_interval,
                limit=1000,
                params={"endTime": current_end},
            )

            if not batch:
                break

            # CRITICAL: Bybit kline is reverse-sorted (newest first).
            # Reverse to chronological order for processing.
            batch.reverse()

            # Filter to only candles within our target range
            batch = [c for c in batch if c[0] >= since_ms]

            if not batch:
                break

            inserted = await self._store.insert_ohlcv_candles(symbol, batch)
            total_inserted += inserted

            # Move backward: oldest timestamp is now first after reverse
            oldest_ts = batch[0][0]
            if oldest_ts >= current_end:
                break  # No progress guard

            current_end = oldest_ts

            # Rate limit safety delay between paginated calls
            await asyncio.sleep(self._settings.fetch_batch_delay)

        logger.info(
            "ohlcv_fetch_progress",
            symbol=symbol,
            records_fetched=total_inserted,
        )
        return total_inserted

    # ──────────────────────────────────────────────
    # Retry wrapper
    # ──────────────────────────────────────────────

    async def _fetch_with_retry(self, fetch_fn: Callable, *args, **kwargs) -> list:
        """Execute a fetch function with exponential backoff retry.

        Retries up to max_retries times with delays: 1s, 2s, 4s, 8s, 16s.
        Handles ccxt rate limit errors with a longer delay multiplier.
        Re-raises on final failure.
        """
        max_retries = self._settings.max_retries
        base_delay = self._settings.retry_base_delay

        for attempt in range(max_retries):
            try:
                return await fetch_fn(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        "fetch_failed_permanently",
                        error=str(e),
                        attempts=max_retries,
                    )
                    raise

                delay = base_delay * (2**attempt)

                # Rate limit errors get a longer delay
                if isinstance(e, ccxt.async_support.RateLimitExceeded):
                    delay *= 3
                    logger.warning(
                        "rate_limit_exceeded",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                    )
                else:
                    logger.warning(
                        "fetch_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(e),
                    )

                await asyncio.sleep(delay)

        return []  # Unreachable, but satisfies type checker
