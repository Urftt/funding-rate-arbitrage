"""Async SQLite database manager for historical data persistence.

Uses aiosqlite for non-blocking database operations with WAL mode
for concurrent read/write performance.
"""

import os
from typing import Self

import aiosqlite

from bot.logging import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS funding_rate_history (
    symbol TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    funding_rate TEXT NOT NULL,
    interval_hours INTEGER NOT NULL DEFAULT 8,
    PRIMARY KEY (symbol, timestamp_ms)
);

CREATE TABLE IF NOT EXISTS ohlcv_candles (
    symbol TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    open TEXT,
    high TEXT,
    low TEXT,
    close TEXT,
    volume TEXT,
    PRIMARY KEY (symbol, timestamp_ms)
);

CREATE TABLE IF NOT EXISTS fetch_state (
    symbol TEXT NOT NULL,
    data_type TEXT NOT NULL,
    earliest_ms INTEGER,
    latest_ms INTEGER,
    last_fetched_at INTEGER,
    PRIMARY KEY (symbol, data_type)
);

CREATE TABLE IF NOT EXISTS tracked_pairs (
    symbol TEXT PRIMARY KEY,
    added_at INTEGER NOT NULL,
    last_volume_24h TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);
"""

_CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_funding_symbol_ts
    ON funding_rate_history(symbol, timestamp_ms);

CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_ts
    ON ohlcv_candles(symbol, timestamp_ms);
"""


class HistoricalDatabase:
    """Async SQLite connection manager for historical data.

    Manages database lifecycle including schema creation, WAL mode
    configuration, and clean resource cleanup.

    Usage:
        # Context manager (recommended)
        async with HistoricalDatabase("/path/to/db") as db:
            await db.db.execute("SELECT ...")

        # Manual lifecycle
        db = HistoricalDatabase("/path/to/db")
        await db.connect()
        try:
            await db.db.execute("SELECT ...")
        finally:
            await db.close()
    """

    def __init__(self, db_path: str = "data/historical.db") -> None:
        self._db_path = db_path
        self._connection: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        """Access the raw aiosqlite connection.

        Raises RuntimeError if not connected.
        """
        if self._connection is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    async def connect(self) -> None:
        """Open database connection, configure pragmas, and create schema.

        Creates the parent directory if it does not exist.
        Sets WAL journal mode and NORMAL synchronous for performance.
        """
        # Ensure parent directory exists
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._connection = await aiosqlite.connect(self._db_path)

        # Performance pragmas
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA synchronous=NORMAL")

        await self._create_tables()
        await self._ensure_schema_version()

        logger.info("historical_db_connected", db_path=self._db_path)

    async def close(self) -> None:
        """Close the database connection if open."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.info("historical_db_closed", db_path=self._db_path)

    async def _create_tables(self) -> None:
        """Create all tables and indexes if they do not exist."""
        assert self._connection is not None
        await self._connection.executescript(_CREATE_TABLES_SQL)
        await self._connection.executescript(_CREATE_INDEXES_SQL)
        await self._connection.commit()

    async def _ensure_schema_version(self) -> None:
        """Insert schema version if not already set."""
        assert self._connection is not None
        cursor = await self._connection.execute(
            "SELECT version FROM schema_version LIMIT 1"
        )
        row = await cursor.fetchone()
        if row is None:
            await self._connection.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            await self._connection.commit()
            logger.info("schema_version_set", version=SCHEMA_VERSION)

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        """Async context manager exit."""
        await self.close()
