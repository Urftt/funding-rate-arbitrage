"""Historical data access layer (Postgres-backed).

Provides data models, an asyncpg-based connection manager, pair selection,
and a typed read/write store for funding rate and OHLCV historical data.
The bot reads from the shared ``crypto`` Postgres instance populated by the
standalone sync scripts at ``scripts/bybit_postgres_sync/``.
"""

from bot.data.database import HistoricalDatabase, build_dsn_from_env
from bot.data.models import HistoricalFundingRate, OHLCVCandle
from bot.data.pair_selector import select_top_pairs
from bot.data.store import HistoricalDataStore

__all__ = [
    "HistoricalDatabase",
    "HistoricalDataStore",
    "HistoricalFundingRate",
    "OHLCVCandle",
    "build_dsn_from_env",
    "select_top_pairs",
]
