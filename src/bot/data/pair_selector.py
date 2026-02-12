"""Pair selection for historical data tracking.

Selects the top N USDT linear perpetual pairs by 24-hour volume
from current funding rate data.
"""

from bot.models import FundingRateData


def select_top_pairs(
    funding_rates: list[FundingRateData], count: int = 20
) -> list[str]:
    """Select top pairs by volume for historical data tracking.

    Filters to USDT perpetuals only (symbol ending with ":USDT"),
    sorts by 24-hour volume descending, and returns the top `count` symbols.

    Args:
        funding_rates: List of current funding rate snapshots.
        count: Number of top pairs to select (default 20).

    Returns:
        List of symbol strings, e.g. ["BTC/USDT:USDT", "ETH/USDT:USDT", ...].
    """
    usdt_pairs = [fr for fr in funding_rates if fr.symbol.endswith(":USDT")]
    usdt_pairs.sort(key=lambda fr: fr.volume_24h, reverse=True)
    return [fr.symbol for fr in usdt_pairs[:count]]
