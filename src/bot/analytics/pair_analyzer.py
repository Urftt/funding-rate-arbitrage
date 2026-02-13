"""Pair analysis service for historical funding rate statistics.

Computes per-pair statistics including fee-adjusted annualized yield,
average/median funding rates, standard deviation, and percentage of
positive funding periods. Used by the Pair Explorer dashboard feature.

Core formula (matches OpportunityRanker):
  round_trip_fee = (spot_taker + perp_taker) * 2
  amortized_fee = round_trip_fee / min_holding_periods
  net_yield_per_period = avg_rate - amortized_fee
  annualized_yield = net_yield_per_period * (8760 / interval_hours)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

import structlog

from bot.config import FeeSettings
from bot.data.models import HistoricalFundingRate
from bot.data.store import HistoricalDataStore

logger = structlog.get_logger(__name__)

MIN_RECORDS = 30  # ~10 days at 8h intervals
_HOURS_PER_YEAR = Decimal("8760")
_MIN_HOLDING_PERIODS = Decimal("3")
_ZERO = Decimal("0")


@dataclass
class PairStats:
    """Aggregate statistics for a single trading pair's funding history.

    All monetary/rate fields use Decimal for precision. The to_dict()
    method serializes Decimal values as strings for JSON transport.
    """

    symbol: str
    record_count: int
    avg_rate: Decimal
    median_rate: Decimal
    std_dev: Decimal
    pct_positive: Decimal
    net_yield_per_period: Decimal
    annualized_yield: Decimal
    has_sufficient_data: bool

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict with Decimal values as strings."""
        return {
            "symbol": self.symbol,
            "record_count": self.record_count,
            "avg_rate": str(self.avg_rate),
            "median_rate": str(self.median_rate),
            "std_dev": str(self.std_dev),
            "pct_positive": str(self.pct_positive),
            "net_yield_per_period": str(self.net_yield_per_period),
            "annualized_yield": str(self.annualized_yield),
            "has_sufficient_data": self.has_sufficient_data,
        }


@dataclass
class PairDetail:
    """Detailed pair data including time series for charting.

    Extends PairStats with the raw funding rate time series data
    for rendering charts in the Pair Explorer UI.
    """

    symbol: str
    stats: PairStats
    time_series: list[dict]

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        return {
            "symbol": self.symbol,
            "stats": self.stats.to_dict(),
            "time_series": self.time_series,
        }


def _compute_stats(
    symbol: str,
    rates: list[HistoricalFundingRate],
    fee_settings: FeeSettings,
) -> PairStats:
    """Compute aggregate statistics from a list of funding rate records.

    Uses the same fee-adjusted yield formula as OpportunityRanker:
      round_trip_fee = (spot_taker + perp_taker) * 2
      amortized_fee = round_trip_fee / 3
      net_yield = avg_rate - amortized_fee
      annualized = net_yield * (8760 / interval_hours)

    Args:
        symbol: Trading pair symbol.
        rates: List of historical funding rate records.
        fee_settings: Fee configuration for yield calculation.

    Returns:
        PairStats with computed statistics.
    """
    if len(rates) == 0:
        return PairStats(
            symbol=symbol,
            record_count=0,
            avg_rate=_ZERO,
            median_rate=_ZERO,
            std_dev=_ZERO,
            pct_positive=_ZERO,
            net_yield_per_period=_ZERO,
            annualized_yield=_ZERO,
            has_sufficient_data=False,
        )

    values = [r.funding_rate for r in rates]
    n = len(values)
    n_dec = Decimal(n)

    # Average
    avg_rate = sum(values, _ZERO) / n_dec

    # Median
    sorted_values = sorted(values)
    if n % 2 == 1:
        median_rate = sorted_values[n // 2]
    else:
        mid = n // 2
        median_rate = (sorted_values[mid - 1] + sorted_values[mid]) / Decimal("2")

    # Sample standard deviation (N-1 denominator)
    if n < 2:
        std_dev = _ZERO
    else:
        variance = sum((v - avg_rate) ** 2 for v in values) / (n_dec - Decimal("1"))
        std_dev = variance.sqrt()

    # Percentage positive
    positive_count = sum(1 for v in values if v > _ZERO)
    pct_positive = Decimal(positive_count) / n_dec

    # Fee-adjusted yield (matches OpportunityRanker formula)
    round_trip_fee = (fee_settings.spot_taker + fee_settings.perp_taker) * 2
    amortized_fee = round_trip_fee / _MIN_HOLDING_PERIODS
    net_yield_per_period = avg_rate - amortized_fee

    # Determine dominant interval_hours from the rates
    interval_counts = Counter(r.interval_hours for r in rates)
    dominant_interval = interval_counts.most_common(1)[0][0]
    annualized_yield = net_yield_per_period * (
        _HOURS_PER_YEAR / Decimal(str(dominant_interval))
    )

    has_sufficient_data = n >= MIN_RECORDS

    return PairStats(
        symbol=symbol,
        record_count=n,
        avg_rate=avg_rate,
        median_rate=median_rate,
        std_dev=std_dev,
        pct_positive=pct_positive,
        net_yield_per_period=net_yield_per_period,
        annualized_yield=annualized_yield,
        has_sufficient_data=has_sufficient_data,
    )


class PairAnalyzer:
    """Service for computing per-pair historical funding rate statistics.

    Wraps HistoricalDataStore queries with statistical computation and
    fee-adjusted yield calculation. Used by the Pair Explorer API endpoints.

    Args:
        data_store: Historical data store for funding rate queries.
        fee_settings: Fee configuration for yield calculation.
    """

    def __init__(self, data_store: HistoricalDataStore, fee_settings: FeeSettings) -> None:
        self._store = data_store
        self._fee_settings = fee_settings

    async def get_pair_ranking(
        self,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> list[PairStats]:
        """Get all tracked pairs ranked by annualized yield descending.

        Pairs with insufficient data (< MIN_RECORDS) are sorted to the bottom.

        Args:
            since_ms: Optional start timestamp filter (milliseconds).
            until_ms: Optional end timestamp filter (milliseconds).

        Returns:
            List of PairStats sorted by annualized yield descending,
            with insufficient-data pairs at the end.
        """
        pairs = await self._store.get_tracked_pairs(active_only=True)
        stats_list: list[PairStats] = []

        for pair in pairs:
            symbol = pair["symbol"]
            rates = await self._store.get_funding_rates(symbol, since_ms, until_ms)
            stats = _compute_stats(symbol, rates, self._fee_settings)
            stats_list.append(stats)

        # Sort: sufficient data first (by yield desc), then insufficient (by yield desc)
        stats_list.sort(
            key=lambda s: (s.has_sufficient_data, s.annualized_yield),
            reverse=True,
        )

        logger.debug(
            "pair_ranking_computed",
            total_pairs=len(stats_list),
            sufficient_data=sum(1 for s in stats_list if s.has_sufficient_data),
        )

        return stats_list

    async def get_pair_stats(
        self,
        symbol: str,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> PairDetail:
        """Get detailed statistics and time series for a single pair.

        Args:
            symbol: Trading pair symbol (e.g., "BTC/USDT:USDT").
            since_ms: Optional start timestamp filter (milliseconds).
            until_ms: Optional end timestamp filter (milliseconds).

        Returns:
            PairDetail with stats and time series data.
        """
        rates = await self._store.get_funding_rates(symbol, since_ms, until_ms)
        stats = _compute_stats(symbol, rates, self._fee_settings)

        time_series = [
            {
                "timestamp_ms": r.timestamp_ms,
                "funding_rate": str(r.funding_rate),
                "interval_hours": r.interval_hours,
            }
            for r in rates
        ]

        logger.debug(
            "pair_stats_computed",
            symbol=symbol,
            record_count=stats.record_count,
            annualized_yield=str(stats.annualized_yield),
        )

        return PairDetail(
            symbol=symbol,
            stats=stats,
            time_series=time_series,
        )

    async def get_rate_distribution(
        self,
        symbol: str,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> dict:
        """Get funding rate distribution data for histogram and box plot rendering.

        Returns server-side histogram bins (for individual pair histogram) and
        raw rate values as strings (for the boxplot plugin which auto-computes
        quartiles).

        Args:
            symbol: Trading pair symbol.
            since_ms: Optional start timestamp filter.
            until_ms: Optional end timestamp filter.

        Returns:
            Dict with "bins", "counts", and "raw_rates" keys.
        """
        rates = await self._store.get_funding_rates(symbol, since_ms, until_ms)
        values = [r.funding_rate for r in rates]

        if not values:
            return {"bins": [], "counts": [], "raw_rates": []}

        # Server-side histogram binning with percentage labels
        min_val, max_val = min(values), max(values)

        if min_val == max_val:
            label = f"{float(min_val) * 100:.4f}%"
            return {"bins": [label], "counts": [len(values)], "raw_rates": [str(v) for v in values]}

        bin_count = min(20, max(5, len(values) // 20))
        bin_width = (max_val - min_val) / Decimal(str(bin_count))

        bins = []
        counts = []
        for i in range(bin_count):
            lower = min_val + bin_width * Decimal(str(i))
            label = f"{float(lower) * 100:.4f}%"
            upper = lower + bin_width
            count = sum(
                1 for v in values
                if (lower <= v < upper) or (i == bin_count - 1 and v == max_val)
            )
            bins.append(label)
            counts.append(count)

        raw_rates = [str(v) for v in values]

        return {"bins": bins, "counts": counts, "raw_rates": raw_rates}

    async def get_multi_rate_distribution(
        self,
        symbols: list[str],
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> dict[str, list[str]]:
        """Get raw funding rate arrays for multiple pairs (for box plot chart).

        Args:
            symbols: List of trading pair symbols.
            since_ms: Optional start timestamp filter.
            until_ms: Optional end timestamp filter.

        Returns:
            Dict mapping symbol to list of rate value strings.
        """
        result = {}
        for symbol in symbols:
            rates = await self._store.get_funding_rates(symbol, since_ms, until_ms)
            result[symbol] = [str(r.funding_rate) for r in rates]
        return result
