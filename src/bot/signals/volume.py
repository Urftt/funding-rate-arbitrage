"""Volume trend detection for funding rate arbitrage signals.

Compares recent vs prior period average OHLCV volume to detect declining
volume trends. This is a HARD FILTER: pairs with declining volume are
rejected regardless of composite score.

CRITICAL: All values use Decimal. Never use float for volumes.
"""

from decimal import Decimal

from bot.data.models import OHLCVCandle


def compute_volume_trend(
    candles: list[OHLCVCandle],
    lookback_days: int = 7,
    decline_ratio: Decimal = Decimal("0.7"),
) -> bool:
    """Detect whether volume is declining for a trading pair.

    Splits candles into two periods (recent and prior), each spanning
    ``lookback_days`` worth of 1h candles. Compares average volume of
    the recent period against the prior period.

    Args:
        candles: List of OHLCVCandle objects, assumed to be 1h candles
            sorted by timestamp ascending.
        lookback_days: Number of days per period. Default 7 days.
        decline_ratio: Threshold ratio. If recent_avg < decline_ratio * prior_avg,
            volume is considered declining. Default 0.7 (70%).

    Returns:
        True if volume is OK (not declining or insufficient data).
        False if volume is declining (recent < ratio * prior).
    """
    candles_per_period = lookback_days * 24

    # Need enough candles for both periods
    total_needed = candles_per_period * 2
    if len(candles) < total_needed:
        # Graceful degradation: don't reject pairs for lack of data
        return True

    # Split into prior and recent periods (candles sorted ascending by time)
    prior = candles[-total_needed : -candles_per_period]
    recent = candles[-candles_per_period:]

    # Compute average volume for each period
    prior_avg = sum(c.volume for c in prior) / len(prior)
    recent_avg = sum(c.volume for c in recent) / len(recent)

    # Avoid division by zero: if prior average is zero, no trend signal
    if prior_avg == Decimal("0"):
        return True

    # Volume OK if recent >= decline_ratio * prior
    return recent_avg >= decline_ratio * prior_avg
