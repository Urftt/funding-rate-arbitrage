"""Data models for historical funding rate and OHLCV candle data.

CRITICAL: All monetary values use Decimal. Never use float for prices, quantities, or rates.
See: .planning/phases/01-core-trading-engine/01-RESEARCH.md (Anti-Patterns)
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class HistoricalFundingRate:
    """A single historical funding rate record.

    Backed by ``bybit_funding_rates`` in Postgres (NUMERIC column). The
    ``timestamp_ms`` field is epoch-ms for API compatibility with downstream
    consumers; the store converts to/from TIMESTAMPTZ at the boundary.
    """

    symbol: str
    timestamp_ms: int
    funding_rate: Decimal
    interval_hours: int = 8


@dataclass
class OHLCVCandle:
    """A single OHLCV candle record.

    Backed by ``bybit_perp_klines`` or ``bybit_spot_klines`` in Postgres
    (DOUBLE PRECISION columns). All fields are surfaced as Decimal so
    downstream code never has to deal with floating-point arithmetic.
    """

    symbol: str
    timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
