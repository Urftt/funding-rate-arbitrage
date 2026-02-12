"""Typed SQLite read/write abstraction for historical data.

Provides HistoricalDataStore with typed methods for inserting and querying
funding rates, OHLCV candles, fetch state, and tracked pairs. All SQL is
isolated behind this interface.

CRITICAL: All monetary/rate values stored as TEXT in SQLite, restored as Decimal on read.
"""

import time
from decimal import Decimal

from bot.data.database import HistoricalDatabase
from bot.data.models import HistoricalFundingRate, OHLCVCandle
from bot.logging import get_logger

logger = get_logger(__name__)


class HistoricalDataStore:
    """Async SQLite store for historical funding rates and OHLCV candles.

    Wraps HistoricalDatabase with typed read/write methods. All SQL access
    goes through self._database.db (the aiosqlite Connection).

    Usage:
        async with HistoricalDatabase("data/historical.db") as database:
            store = HistoricalDataStore(database)
            count = await store.insert_funding_rates(records)
    """

    def __init__(self, database: HistoricalDatabase) -> None:
        self._database = database

    # ──────────────────────────────────────────────
    # Write methods
    # ──────────────────────────────────────────────

    async def insert_funding_rates(self, records: list[dict]) -> int:
        """Insert funding rate records, ignoring duplicates via INSERT OR IGNORE.

        Accepts ccxt-format dicts with keys: symbol, fundingRate, timestamp, info.
        Returns the number of actually inserted rows (excludes ignored duplicates).
        """
        if not records:
            return 0

        data = [
            (
                r["symbol"],
                r["timestamp"],
                str(r["fundingRate"]),
                r.get("info", {}).get("fundingIntervalHours", 8),
            )
            for r in records
        ]

        cursor = await self._database.db.executemany(
            "INSERT OR IGNORE INTO funding_rate_history "
            "(symbol, timestamp_ms, funding_rate, interval_hours) "
            "VALUES (?, ?, ?, ?)",
            data,
        )
        await self._database.db.commit()

        inserted = cursor.rowcount
        logger.debug(
            "inserted_funding_rates",
            total=len(records),
            inserted=inserted,
        )
        return inserted

    async def insert_ohlcv_candles(self, symbol: str, candles: list[list]) -> int:
        """Insert OHLCV candle records, ignoring duplicates via INSERT OR IGNORE.

        Accepts ccxt-format lists: [timestamp_ms, open, high, low, close, volume].
        Returns the number of actually inserted rows.
        """
        if not candles:
            return 0

        data = [
            (
                symbol,
                candle[0],
                str(candle[1]),
                str(candle[2]),
                str(candle[3]),
                str(candle[4]),
                str(candle[5]),
            )
            for candle in candles
        ]

        cursor = await self._database.db.executemany(
            "INSERT OR IGNORE INTO ohlcv_candles "
            "(symbol, timestamp_ms, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            data,
        )
        await self._database.db.commit()

        inserted = cursor.rowcount
        logger.debug(
            "inserted_ohlcv_candles",
            symbol=symbol,
            total=len(candles),
            inserted=inserted,
        )
        return inserted

    async def update_fetch_state(
        self,
        symbol: str,
        data_type: str,
        earliest_ms: int,
        latest_ms: int,
    ) -> None:
        """Update or insert fetch state for a symbol and data type.

        Tracks the earliest and latest timestamps fetched for resume capability.
        """
        now_ms = int(time.time() * 1000)
        await self._database.db.execute(
            "INSERT OR REPLACE INTO fetch_state "
            "(symbol, data_type, earliest_ms, latest_ms, last_fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (symbol, data_type, earliest_ms, latest_ms, now_ms),
        )
        await self._database.db.commit()

    async def update_tracked_pair(
        self,
        symbol: str,
        volume_24h: Decimal,
        is_active: bool = True,
    ) -> None:
        """Update or insert a tracked pair, preserving original added_at timestamp."""
        now_ms = int(time.time() * 1000)
        await self._database.db.execute(
            "INSERT OR REPLACE INTO tracked_pairs "
            "(symbol, added_at, last_volume_24h, is_active) "
            "VALUES (?, COALESCE((SELECT added_at FROM tracked_pairs WHERE symbol = ?), ?), ?, ?)",
            (symbol, symbol, now_ms, str(volume_24h), 1 if is_active else 0),
        )
        await self._database.db.commit()

    # ──────────────────────────────────────────────
    # Read methods
    # ──────────────────────────────────────────────

    async def get_fetch_state(self, symbol: str, data_type: str) -> dict | None:
        """Get fetch state for a symbol and data type.

        Returns dict with earliest_ms, latest_ms, last_fetched_at or None.
        """
        cursor = await self._database.db.execute(
            "SELECT earliest_ms, latest_ms, last_fetched_at "
            "FROM fetch_state WHERE symbol = ? AND data_type = ?",
            (symbol, data_type),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "earliest_ms": row[0],
            "latest_ms": row[1],
            "last_fetched_at": row[2],
        }

    async def get_funding_rates(
        self,
        symbol: str,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> list[HistoricalFundingRate]:
        """Query funding rates for a symbol within an optional time range.

        Returns list of HistoricalFundingRate ordered by timestamp_ms ASC.
        """
        conditions = ["symbol = ?"]
        params: list = [symbol]

        if since_ms is not None:
            conditions.append("timestamp_ms >= ?")
            params.append(since_ms)
        if until_ms is not None:
            conditions.append("timestamp_ms <= ?")
            params.append(until_ms)

        where = " AND ".join(conditions)
        cursor = await self._database.db.execute(
            f"SELECT symbol, timestamp_ms, funding_rate, interval_hours "
            f"FROM funding_rate_history WHERE {where} ORDER BY timestamp_ms ASC",
            params,
        )
        rows = await cursor.fetchall()
        return [
            HistoricalFundingRate(
                symbol=row[0],
                timestamp_ms=row[1],
                funding_rate=Decimal(row[2]),
                interval_hours=row[3],
            )
            for row in rows
        ]

    async def get_ohlcv_candles(
        self,
        symbol: str,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> list[OHLCVCandle]:
        """Query OHLCV candles for a symbol within an optional time range.

        Returns list of OHLCVCandle ordered by timestamp_ms ASC.
        """
        conditions = ["symbol = ?"]
        params: list = [symbol]

        if since_ms is not None:
            conditions.append("timestamp_ms >= ?")
            params.append(since_ms)
        if until_ms is not None:
            conditions.append("timestamp_ms <= ?")
            params.append(until_ms)

        where = " AND ".join(conditions)
        cursor = await self._database.db.execute(
            f"SELECT symbol, timestamp_ms, open, high, low, close, volume "
            f"FROM ohlcv_candles WHERE {where} ORDER BY timestamp_ms ASC",
            params,
        )
        rows = await cursor.fetchall()
        return [
            OHLCVCandle(
                symbol=row[0],
                timestamp_ms=row[1],
                open=Decimal(row[2]),
                high=Decimal(row[3]),
                low=Decimal(row[4]),
                close=Decimal(row[5]),
                volume=Decimal(row[6]),
            )
            for row in rows
        ]

    async def get_tracked_pairs(self, active_only: bool = True) -> list[dict]:
        """Get tracked pairs, optionally filtered to active only.

        Returns list of dicts with symbol, added_at, last_volume_24h, is_active.
        """
        query = "SELECT symbol, added_at, last_volume_24h, is_active FROM tracked_pairs"
        if active_only:
            query += " WHERE is_active = 1"

        cursor = await self._database.db.execute(query)
        rows = await cursor.fetchall()
        return [
            {
                "symbol": row[0],
                "added_at": row[1],
                "last_volume_24h": Decimal(row[2]) if row[2] else None,
                "is_active": bool(row[3]),
            }
            for row in rows
        ]

    async def get_data_status(self) -> dict:
        """Get aggregate data status for dashboard display.

        Returns dict with total_pairs, total_funding_records, total_ohlcv_records,
        earliest_date_ms, latest_date_ms, last_sync_ms.
        """
        db = self._database.db

        # Total active tracked pairs
        cursor = await db.execute(
            "SELECT COUNT(*) FROM tracked_pairs WHERE is_active = 1"
        )
        total_pairs = (await cursor.fetchone())[0]

        # Total funding records
        cursor = await db.execute("SELECT COUNT(*) FROM funding_rate_history")
        total_funding_records = (await cursor.fetchone())[0]

        # Total OHLCV records
        cursor = await db.execute("SELECT COUNT(*) FROM ohlcv_candles")
        total_ohlcv_records = (await cursor.fetchone())[0]

        # Earliest date across both tables
        cursor = await db.execute(
            "SELECT MIN(ts) FROM ("
            "  SELECT MIN(timestamp_ms) AS ts FROM funding_rate_history "
            "  UNION ALL "
            "  SELECT MIN(timestamp_ms) AS ts FROM ohlcv_candles"
            ")"
        )
        earliest_date_ms = (await cursor.fetchone())[0]

        # Latest date across both tables
        cursor = await db.execute(
            "SELECT MAX(ts) FROM ("
            "  SELECT MAX(timestamp_ms) AS ts FROM funding_rate_history "
            "  UNION ALL "
            "  SELECT MAX(timestamp_ms) AS ts FROM ohlcv_candles"
            ")"
        )
        latest_date_ms = (await cursor.fetchone())[0]

        # Last sync time
        cursor = await db.execute(
            "SELECT MAX(last_fetched_at) FROM fetch_state"
        )
        last_sync_ms = (await cursor.fetchone())[0]

        return {
            "total_pairs": total_pairs,
            "total_funding_records": total_funding_records,
            "total_ohlcv_records": total_ohlcv_records,
            "earliest_date_ms": earliest_date_ms,
            "latest_date_ms": latest_date_ms,
            "last_sync_ms": last_sync_ms,
        }
