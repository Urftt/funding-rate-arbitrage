"""Async Postgres connection manager backed by asyncpg.

The bot treats Postgres as a read-mostly analytics substrate. The shared
``crypto`` database is populated by the standalone sync scripts in
``scripts/bybit_postgres_sync/`` -- this module NEVER drops, truncates, or
alters any of the ``bybit_*`` tables. It only creates the bot-owned
``bot_tracked_pairs`` table on first connect (``CREATE TABLE IF NOT EXISTS``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Self

import asyncpg
from dotenv import load_dotenv

from bot.logging import get_logger

# Load .env once at import time so env-var DSN construction works for CLI
# tools (backtest, ad-hoc scripts) that don't go through AppSettings.
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")

logger = get_logger(__name__)


# Bot-owned table: distinct from any shared bybit_* tables.
_CREATE_BOT_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS bot_tracked_pairs (
    symbol          TEXT PRIMARY KEY,
    added_at        TIMESTAMPTZ NOT NULL,
    last_volume_24h NUMERIC,
    is_active       BOOLEAN NOT NULL DEFAULT true
);
"""


def _connect_kwargs_from_env() -> dict:
    """Build asyncpg connect kwargs from POSTGRES_* env vars.

    Using discrete kwargs (not a DSN URL) avoids percent-encoding issues
    with passwords containing ``%`` / ``@`` / ``#``.
    """
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(
            "POSTGRES_PASSWORD env var is required. "
            "Set it in .env or export it before starting the bot."
        )
    return {
        "host": os.environ.get("POSTGRES_HOST", "192.168.1.53"),
        "port": int(os.environ.get("POSTGRES_PORT", "5432")),
        "user": os.environ.get("POSTGRES_USER", "luc"),
        "database": os.environ.get("POSTGRES_DB", "crypto"),
        "password": password,
    }


def build_dsn_from_env() -> str:
    """Back-compat helper -- constructs a DSN URL. Prefer env-kwargs."""
    from urllib.parse import quote
    k = _connect_kwargs_from_env()
    return (
        f"postgresql://{quote(k['user'])}:{quote(k['password'])}"
        f"@{k['host']}:{k['port']}/{quote(k['database'])}"
    )


class HistoricalDatabase:
    """Async Postgres pool manager for historical data reads (and bot-owned writes).

    Thin wrapper around ``asyncpg.Pool``. The pool is created on :meth:`connect`
    and closed on :meth:`close`. The bot creates its own ``bot_tracked_pairs``
    table if it does not exist, but never touches the shared ``bybit_*`` schema.

    Usage::

        async with HistoricalDatabase() as database:
            async with database.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")

        # Or manual:
        database = HistoricalDatabase()
        await database.connect()
        try:
            ...
        finally:
            await database.close()
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        min_size: int = 2,
        max_size: int = 10,
    ) -> None:
        # Prefer discrete connect kwargs (avoids URL-encoding headaches); fall
        # back to a caller-supplied DSN string if provided.
        self._dsn = dsn
        if dsn is None:
            self._connect_kwargs = _connect_kwargs_from_env()
        else:
            self._connect_kwargs = None
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        """Access the underlying asyncpg Pool.

        Raises RuntimeError if the pool has not been initialized.
        """
        if self._pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool

    # Back-compat alias; some older callers used ``.db``.
    @property
    def db(self) -> asyncpg.Pool:
        return self.pool

    async def connect(self) -> None:
        """Create the asyncpg pool and ensure the bot-owned tables exist."""
        if self._connect_kwargs is not None:
            self._pool = await asyncpg.create_pool(
                min_size=self._min_size,
                max_size=self._max_size,
                **self._connect_kwargs,
            )
        else:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
            )
        # Create bot-owned tables only (never touch shared bybit_* tables).
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_BOT_TABLES_SQL)

        # Don't log the DSN (contains password). Log the connection target.
        logger.info(
            "postgres_pool_connected",
            host=os.environ.get("POSTGRES_HOST", "192.168.1.53"),
            database=os.environ.get("POSTGRES_DB", "crypto"),
            min_size=self._min_size,
            max_size=self._max_size,
        )

    async def close(self) -> None:
        """Close the asyncpg pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("postgres_pool_closed")

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        await self.close()
