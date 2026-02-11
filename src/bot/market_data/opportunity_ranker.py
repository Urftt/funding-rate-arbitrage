"""Opportunity ranking engine for funding rate arbitrage pairs.

Scores and ranks perpetual funding rate opportunities by net yield after
amortized round-trip trading fees. Filters by minimum rate, volume, and
spot pair availability.

Core formula:
  round_trip_fee_pct = (spot_taker + perp_taker) * 2
  amortized_fee = round_trip_fee_pct / min_holding_periods
  net_yield_per_period = funding_rate - amortized_fee
  periods_per_year = 8760 / interval_hours
  annualized_yield = net_yield_per_period * periods_per_year
"""

from decimal import Decimal

from bot.config import FeeSettings
from bot.models import FundingRateData, OpportunityScore

_HOURS_PER_YEAR = Decimal("8760")  # 365 * 24


class OpportunityRanker:
    """Ranks funding rate opportunities by net yield after fees.

    Args:
        fee_settings: Fee rate configuration for round-trip cost calculation.
    """

    def __init__(self, fee_settings: FeeSettings) -> None:
        self._fee_settings = fee_settings

    def rank_opportunities(
        self,
        funding_rates: list[FundingRateData],
        markets: dict,
        min_rate: Decimal,
        min_volume_24h: Decimal = Decimal("1000000"),
        min_holding_periods: int = 3,
    ) -> list[OpportunityScore]:
        """Score and rank funding rate pairs by net yield.

        For each FundingRateData:
        1. Filter by min_rate, min_volume_24h, and spot availability
        2. Compute net yield after amortized round-trip fees
        3. Sort by annualized_yield descending

        Args:
            funding_rates: List of funding rate snapshots for perpetual pairs.
            markets: ccxt-style markets dict for spot symbol derivation.
            min_rate: Minimum funding rate threshold (pairs below are excluded).
            min_volume_24h: Minimum 24h volume in USD (default $1M).
            min_holding_periods: Number of funding periods over which to
                amortize round-trip fees (default 3).

        Returns:
            List of OpportunityScore sorted by annualized_yield descending.
        """
        round_trip_fee_pct = (
            self._fee_settings.spot_taker + self._fee_settings.perp_taker
        ) * 2
        amortized_fee = round_trip_fee_pct / Decimal(str(min_holding_periods))

        scores: list[OpportunityScore] = []

        for fr in funding_rates:
            # Filter: minimum rate
            if fr.rate < min_rate:
                continue

            # Filter: minimum volume
            if fr.volume_24h < min_volume_24h:
                continue

            # Filter: spot symbol availability
            spot_symbol = self._derive_spot_symbol(fr.symbol, markets)
            if spot_symbol is None:
                continue

            # Compute net yield
            net_yield_per_period = fr.rate - amortized_fee
            periods_per_year = _HOURS_PER_YEAR / Decimal(str(fr.interval_hours))
            annualized_yield = net_yield_per_period * periods_per_year
            passes_filters = net_yield_per_period > 0

            scores.append(
                OpportunityScore(
                    spot_symbol=spot_symbol,
                    perp_symbol=fr.symbol,
                    funding_rate=fr.rate,
                    funding_interval_hours=fr.interval_hours,
                    volume_24h=fr.volume_24h,
                    net_yield_per_period=net_yield_per_period,
                    annualized_yield=annualized_yield,
                    passes_filters=passes_filters,
                )
            )

        scores.sort(key=lambda s: s.annualized_yield, reverse=True)
        return scores

    @staticmethod
    def _derive_spot_symbol(
        perp_symbol: str, markets: dict
    ) -> str | None:
        """Derive the spot symbol from a perpetual symbol using markets dict.

        Looks up the perp in markets to get base/quote, constructs the
        spot symbol as "BASE/QUOTE", and verifies it exists as an active
        spot market.

        Args:
            perp_symbol: Perpetual symbol (e.g., "BTC/USDT:USDT").
            markets: ccxt-style markets dict.

        Returns:
            Spot symbol string if valid active spot market exists, None otherwise.
        """
        perp_market = markets.get(perp_symbol)
        if perp_market is None:
            return None

        base = perp_market.get("base")
        quote = perp_market.get("quote")
        if not base or not quote:
            return None

        spot_symbol = f"{base}/{quote}"
        spot_market = markets.get(spot_symbol)
        if spot_market is None:
            return None

        if not spot_market.get("spot", False):
            return None
        if not spot_market.get("active", False):
            return None

        return spot_symbol
