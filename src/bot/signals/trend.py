"""Funding rate trend detection using EMA analysis (SGNL-01).

Computes Exponential Moving Average over historical funding rates and classifies
the trend direction as RISING, FALLING, or STABLE. Uses Decimal arithmetic
with quantize to prevent precision explosion.

CRITICAL: All computations use Decimal. Never use float.
"""

from decimal import Decimal

from bot.signals.models import TrendDirection

#: Precision limit for EMA intermediate results (12 decimal places).
#: Prevents Decimal division from producing arbitrarily long representations.
_EMA_QUANTIZE = Decimal("0.000000000001")


def compute_ema(values: list[Decimal], span: int) -> list[Decimal]:
    """Compute Exponential Moving Average over a list of Decimal values.

    Uses the standard recursive formula:
        alpha = 2 / (span + 1)
        EMA_t = alpha * value_t + (1 - alpha) * EMA_{t-1}

    First EMA value = first input value (standard initialization).
    Each intermediate result is quantized to 12 decimal places to prevent
    Decimal precision explosion (see research Pitfall #1).

    Args:
        values: Ordered list of Decimal values (oldest first).
        span: Number of periods for EMA smoothing.

    Returns:
        List of EMA values, same length as input. Empty list if input is empty.
    """
    if not values:
        return []

    alpha = Decimal("2") / (Decimal(span) + Decimal("1"))
    one_minus_alpha = Decimal("1") - alpha

    ema = [values[0].quantize(_EMA_QUANTIZE)]
    for v in values[1:]:
        next_ema = (alpha * v + one_minus_alpha * ema[-1]).quantize(_EMA_QUANTIZE)
        ema.append(next_ema)

    return ema


def classify_trend(
    funding_rates: list[Decimal],
    span: int = 6,
    stable_threshold: Decimal = Decimal("0.00005"),
) -> TrendDirection:
    """Classify funding rate trend from historical data.

    Computes EMA over funding_rates, then compares the most recent EMA value
    against the EMA from ``span`` periods earlier. If the difference exceeds
    ``stable_threshold``, the trend is classified as RISING or FALLING.

    Graceful degradation: returns STABLE when insufficient data (< span+1 records),
    per research Pitfall #2.

    Args:
        funding_rates: Historical funding rates ordered oldest-first.
        span: EMA span and lookback distance for trend comparison.
        stable_threshold: Minimum absolute EMA difference to classify as non-stable.

    Returns:
        TrendDirection indicating the funding rate trend.
    """
    if len(funding_rates) < span + 1:
        return TrendDirection.STABLE

    ema = compute_ema(funding_rates, span)
    diff = ema[-1] - ema[-span]

    if diff > stable_threshold:
        return TrendDirection.RISING
    elif diff < -stable_threshold:
        return TrendDirection.FALLING
    return TrendDirection.STABLE
