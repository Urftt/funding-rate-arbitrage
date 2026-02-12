"""Historical data persistence layer.

Provides data models, SQLite database management, and pair selection
for funding rate and OHLCV historical data.
"""

from bot.data.database import HistoricalDatabase
from bot.data.models import HistoricalFundingRate, OHLCVCandle
from bot.data.pair_selector import select_top_pairs

__all__ = [
    "HistoricalDatabase",
    "HistoricalFundingRate",
    "OHLCVCandle",
    "select_top_pairs",
]
