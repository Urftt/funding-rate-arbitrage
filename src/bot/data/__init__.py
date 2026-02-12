"""Historical data persistence layer.

Provides data models, SQLite database management, pair selection,
typed read/write store, and paginated fetch pipeline for funding rate
and OHLCV historical data.
"""

from bot.data.database import HistoricalDatabase
from bot.data.fetcher import HistoricalDataFetcher
from bot.data.models import HistoricalFundingRate, OHLCVCandle
from bot.data.pair_selector import select_top_pairs
from bot.data.store import HistoricalDataStore

__all__ = [
    "HistoricalDatabase",
    "HistoricalDataFetcher",
    "HistoricalDataStore",
    "HistoricalFundingRate",
    "OHLCVCandle",
    "select_top_pairs",
]
