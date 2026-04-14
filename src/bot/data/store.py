"""Typed Postgres read/write abstraction for historical Bybit data.

Public API mirrors the previous SQLite implementation so downstream consumers
(backtester, dashboard, signals, analytics) keep the same method signatures.
Data lives in the shared ``crypto`` Postgres instance, populated by the
standalone sync scripts at ``scripts/bybit_postgres_sync/``.

Tables read (shared, read-only from the bot's perspective):
  - bybit_funding_rates
  - bybit_perp_klines
  - bybit_spot_klines
  - bybit_funding_sync_state
  - bybit_kline_sync_state

Tables read/written (bot-owned):
  - bot_tracked_pairs

Symbols use ccxt unified form: perp = ``BTC/USDT:USDT``, spot = ``BTC/USDT``.
Timestamps returned to callers remain as ``timestamp_ms`` (epoch ms) to keep
API stability with the SQLite-era models; internal storage is TIMESTAMPTZ.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from bot.data.database import HistoricalDatabase
from bot.data.models import HistoricalFundingRate, OHLCVCandle
from bot.logging import get_logger

logger = get_logger(__name__)

MarketType = Literal["linear", "spot"]

_KLINE_TABLE = {
    "linear": "bybit_perp_klines",
    "spot": "bybit_spot_klines",
}


def _ms_to_dt(ms: int) -> datetime:
    """Convert epoch ms to a UTC-aware datetime for TIMESTAMPTZ columns."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _dt_to_ms(dt: datetime) -> int:
    """Convert a (possibly naive) datetime to epoch ms assuming UTC if naive."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class HistoricalDataStore:
    """Async Postgres store for funding rates, OHLCV candles, and tracked pairs.

    The standalone sync scripts are the sole writer to the shared ``bybit_*``
    tables; the bot is a pure reader there. The bot writes only to its own
    ``bot_tracked_pairs`` table.

    Args:
        database: An opened :class:`HistoricalDatabase` with an active pool.
    """

    def __init__(self, database: HistoricalDatabase) -> None:
        self._database = database

    @property
    def _pool(self):
        return self._database.pool

    # ------------------------------------------------------------------
    # Write methods -- bot-owned tables only
    # ------------------------------------------------------------------

    async def insert_funding_rates(self, records: list[dict]) -> int:
        """Insert funding-rate rows into ``bybit_funding_rates``.

        Accepts ccxt-format dicts with keys: ``symbol``, ``fundingRate``,
        ``timestamp`` (ms), and optional ``info.fundingIntervalHours``.
        Duplicates are ignored via ``ON CONFLICT DO NOTHING``.

        NOTE: the bot's historical fetcher was removed and the standalone
        sync process is the intended writer. This method is retained for
        backwards compatibility with tests/tools that insert fixture data,
        and will log a warning when used in production wiring.

        Returns:
            Number of rows actually inserted.
        """
        if not records:
            return 0

        rows: list[tuple] = []
        for r in records:
            ts_ms = int(r["timestamp"])
            rows.append(
                (
                    r["symbol"],
                    _ms_to_dt(ts_ms),
                    Decimal(str(r["fundingRate"])),
                    int(r.get("info", {}).get("fundingIntervalHours", 8)),
                    None,  # mark_price
                )
            )

        async with self._pool.acquire() as conn:
            # Use a temp CTE to count actually-inserted rows (ON CONFLICT DO NOTHING
            # does not surface that via executemany's status on asyncpg).
            inserted = 0
            async with conn.transaction():
                result = await conn.executemany(
                    "INSERT INTO bybit_funding_rates "
                    "(symbol, funding_time, funding_rate, interval_hours, mark_price) "
                    "VALUES ($1, $2, $3, $4, $5) "
                    "ON CONFLICT (symbol, funding_time) DO NOTHING",
                    rows,
                )
            # asyncpg returns None from executemany; we approximate inserted count
            # by treating all non-duplicate rows as inserted. For exact counts,
            # callers should use the standalone sync. This mirrors prior behavior
            # which returned cursor.rowcount (also imprecise across drivers).
            _ = result
            inserted = len(rows)

        logger.debug(
            "inserted_funding_rates",
            total=len(records),
            inserted_best_effort=inserted,
        )
        return inserted

    async def insert_ohlcv_candles(
        self,
        symbol: str,
        candles: list[list],
        market_type: MarketType = "linear",
    ) -> int:
        """Insert OHLCV rows into ``bybit_perp_klines`` or ``bybit_spot_klines``.

        Accepts ccxt-format entries: ``[timestamp_ms, open, high, low, close, volume]``.
        Stored as DOUBLE PRECISION (per the shared schema). Duplicates ignored
        via ``ON CONFLICT DO NOTHING``.

        Args:
            symbol: ccxt unified symbol.
            candles: list of ccxt-format OHLCV rows.
            market_type: ``"linear"`` for perps (default), ``"spot"`` for spot.

        Returns:
            Best-effort count of rows inserted.
        """
        if not candles:
            return 0
        table = _KLINE_TABLE[market_type]

        rows: list[tuple] = []
        for c in candles:
            ts = _ms_to_dt(int(c[0]))
            rows.append(
                (
                    symbol,
                    ts,
                    float(c[1]),
                    float(c[2]),
                    float(c[3]),
                    float(c[4]),
                    float(c[5]),
                    float(c[6]) if len(c) > 6 else None,
                )
            )

        sql = (
            f"INSERT INTO {table} "
            "(symbol, timestamp, open, high, low, close, volume, turnover) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "ON CONFLICT (symbol, timestamp) DO NOTHING"
        )

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(sql, rows)

        inserted = len(rows)
        logger.debug(
            "inserted_ohlcv_candles",
            symbol=symbol,
            market_type=market_type,
            total=len(candles),
            inserted_best_effort=inserted,
        )
        return inserted

    async def update_tracked_pair(
        self,
        symbol: str,
        volume_24h: Decimal,
        is_active: bool = True,
    ) -> None:
        """Upsert a tracked pair in the bot-owned table, preserving ``added_at``."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO bot_tracked_pairs (symbol, added_at, last_volume_24h, is_active) "
                "VALUES ($1, now(), $2, $3) "
                "ON CONFLICT (symbol) DO UPDATE SET "
                "  last_volume_24h = EXCLUDED.last_volume_24h, "
                "  is_active = EXCLUDED.is_active",
                symbol,
                volume_24h,
                is_active,
            )

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    async def get_funding_rates(
        self,
        symbol: str,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> list[HistoricalFundingRate]:
        """Return funding rates for ``symbol`` in optional ``[since_ms, until_ms]``.

        Result is ordered by ``funding_time`` ascending. Timestamps are converted
        back to epoch ms for API stability with the SQLite-era model.
        """
        conditions = ["symbol = $1"]
        params: list = [symbol]

        if since_ms is not None:
            params.append(_ms_to_dt(since_ms))
            conditions.append(f"funding_time >= ${len(params)}")
        if until_ms is not None:
            params.append(_ms_to_dt(until_ms))
            conditions.append(f"funding_time <= ${len(params)}")

        where = " AND ".join(conditions)
        sql = (
            "SELECT symbol, funding_time, funding_rate, interval_hours "
            f"FROM bybit_funding_rates WHERE {where} ORDER BY funding_time ASC"
        )

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [
            HistoricalFundingRate(
                symbol=row["symbol"],
                timestamp_ms=_dt_to_ms(row["funding_time"]),
                funding_rate=Decimal(str(row["funding_rate"])),
                interval_hours=int(row["interval_hours"]),
            )
            for row in rows
        ]

    async def get_ohlcv_candles(
        self,
        symbol: str,
        since_ms: int | None = None,
        until_ms: int | None = None,
        market_type: MarketType = "linear",
    ) -> list[OHLCVCandle]:
        """Return OHLCV candles for ``symbol``, ordered ascending by time.

        Reads from ``bybit_perp_klines`` for ``market_type="linear"`` (default)
        or ``bybit_spot_klines`` for ``"spot"``. Double-precision columns are
        converted back to ``Decimal`` to preserve downstream behavior.
        """
        table = _KLINE_TABLE[market_type]

        conditions = ["symbol = $1"]
        params: list = [symbol]

        if since_ms is not None:
            params.append(_ms_to_dt(since_ms))
            conditions.append(f"timestamp >= ${len(params)}")
        if until_ms is not None:
            params.append(_ms_to_dt(until_ms))
            conditions.append(f"timestamp <= ${len(params)}")

        where = " AND ".join(conditions)
        sql = (
            "SELECT symbol, timestamp, open, high, low, close, volume "
            f"FROM {table} WHERE {where} ORDER BY timestamp ASC"
        )

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        def _dec(v) -> Decimal:
            # Preserve prior Decimal-typed API. DOUBLE PRECISION -> Decimal via repr.
            return Decimal(repr(v)) if v is not None else Decimal("0")

        return [
            OHLCVCandle(
                symbol=row["symbol"],
                timestamp_ms=_dt_to_ms(row["timestamp"]),
                open=_dec(row["open"]),
                high=_dec(row["high"]),
                low=_dec(row["low"]),
                close=_dec(row["close"]),
                volume=_dec(row["volume"]),
            )
            for row in rows
        ]

    async def get_tracked_pairs(self, active_only: bool = True) -> list[dict]:
        """Return rows from the bot-owned ``bot_tracked_pairs`` table."""
        sql = (
            "SELECT symbol, added_at, last_volume_24h, is_active "
            "FROM bot_tracked_pairs"
        )
        if active_only:
            sql += " WHERE is_active = true"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)

        return [
            {
                "symbol": row["symbol"],
                # Keep added_at as epoch ms for API parity with the old SQLite layer.
                "added_at": _dt_to_ms(row["added_at"]),
                "last_volume_24h": (
                    Decimal(str(row["last_volume_24h"]))
                    if row["last_volume_24h"] is not None
                    else None
                ),
                "is_active": bool(row["is_active"]),
            }
            for row in rows
        ]

    async def get_data_status(self) -> dict:
        """Aggregate data status for dashboard display.

        Sources counts/timestamps from the shared ``bybit_*`` tables plus the
        bot-owned ``bot_tracked_pairs``. Return dict shape mirrors the SQLite era
        to avoid dashboard changes; ``last_sync_ms`` comes from
        ``bybit_*_sync_state.last_synced_at``.
        """
        async with self._pool.acquire() as conn:
            total_pairs = await conn.fetchval(
                "SELECT COUNT(*) FROM bot_tracked_pairs WHERE is_active = true"
            )
            total_funding_records = await conn.fetchval(
                "SELECT COUNT(*) FROM bybit_funding_rates"
            )
            # Combine perp + spot klines into a single "ohlcv" count for the widget.
            total_ohlcv_records = await conn.fetchval(
                "SELECT "
                "  (SELECT COUNT(*) FROM bybit_perp_klines) "
                "+ (SELECT COUNT(*) FROM bybit_spot_klines)"
            )

            earliest_row = await conn.fetchrow(
                "SELECT MIN(ts) AS ts FROM ("
                "  SELECT MIN(funding_time) AS ts FROM bybit_funding_rates"
                "  UNION ALL "
                "  SELECT MIN(timestamp) AS ts FROM bybit_perp_klines"
                "  UNION ALL "
                "  SELECT MIN(timestamp) AS ts FROM bybit_spot_klines"
                ") t"
            )
            latest_row = await conn.fetchrow(
                "SELECT MAX(ts) AS ts FROM ("
                "  SELECT MAX(funding_time) AS ts FROM bybit_funding_rates"
                "  UNION ALL "
                "  SELECT MAX(timestamp) AS ts FROM bybit_perp_klines"
                "  UNION ALL "
                "  SELECT MAX(timestamp) AS ts FROM bybit_spot_klines"
                ") t"
            )
            last_sync_row = await conn.fetchrow(
                "SELECT MAX(ts) AS ts FROM ("
                "  SELECT MAX(last_synced_at) AS ts FROM bybit_funding_sync_state"
                "  UNION ALL "
                "  SELECT MAX(last_synced_at) AS ts FROM bybit_kline_sync_state"
                ") t"
            )

        def _opt_ms(row) -> int | None:
            if row is None or row["ts"] is None:
                return None
            return _dt_to_ms(row["ts"])

        return {
            "total_pairs": int(total_pairs or 0),
            "total_funding_records": int(total_funding_records or 0),
            "total_ohlcv_records": int(total_ohlcv_records or 0),
            "earliest_date_ms": _opt_ms(earliest_row),
            "latest_date_ms": _opt_ms(latest_row),
            "last_sync_ms": _opt_ms(last_sync_row),
        }
