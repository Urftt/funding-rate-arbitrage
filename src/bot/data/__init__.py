"""Historical data persistence layer.

Provides data models, SQLite database management, pair selection,
and typed read/write store for funding rate and OHLCV historical data.
"""

from bot.data.database import HistoricalDatabase
from bot.data.models import HistoricalFundingRate, OHLCVCandle
from bot.data.pair_selector import select_top_pairs
from bot.data.store import HistoricalDataStore

__all__ = [
    "HistoricalDatabase",
    "HistoricalDataStore",
    "HistoricalFundingRate",
    "OHLCVCandle",
    "select_top_pairs",
]
