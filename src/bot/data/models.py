"""Data models for historical funding rate and OHLCV candle data.

CRITICAL: All monetary values use Decimal. Never use float for prices, quantities, or rates.
See: .planning/phases/01-core-trading-engine/01-RESEARCH.md (Anti-Patterns)
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class HistoricalFundingRate:
    """A single historical funding rate record.

    Stored in SQLite with funding_rate as TEXT to preserve Decimal precision.
    """

    symbol: str
    timestamp_ms: int
    funding_rate: Decimal
    interval_hours: int = 8


@dataclass
class OHLCVCandle:
    """A single OHLCV candle record.

    All price and volume fields use Decimal for precision.
    Stored in SQLite as TEXT to preserve Decimal precision.
    """

    symbol: str
    timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
