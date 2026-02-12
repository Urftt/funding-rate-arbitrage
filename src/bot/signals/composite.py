"""Composite signal aggregation for multi-dimensional opportunity scoring (SGNL-03).

Combines individual sub-signal scores (rate level, trend, persistence, basis)
into a single weighted composite score. The composite score is used by the
SignalEngine to rank opportunities and make entry/exit decisions.

CRITICAL: All computations use Decimal. Never use float for signal scores.
"""

from decimal import Decimal


def normalize_rate_level(
    funding_rate: Decimal, cap: Decimal = Decimal("0.003")
) -> Decimal:
    """Normalize a funding rate to the 0-1 range for composite scoring.

    Uses absolute value so both positive and negative rates produce a score,
    though in practice our long-spot/short-perp strategy only scores
    positive rates.

    The cap prevents extreme rates from dominating the composite score.
    Rates at or above the cap (default 0.3% per period) receive the
    maximum score of 1.0.

    Formula: min(abs(funding_rate) / cap, 1)

    Args:
        funding_rate: The raw funding rate (per period).
        cap: Maximum rate that maps to score 1.0. Default 0.3% (0.003).

    Returns:
        Normalized score in [0, 1] range.
    """
    return min(abs(funding_rate) / cap, Decimal("1"))


def compute_composite_score(
    rate_level: Decimal,
    trend_score: Decimal,
    persistence: Decimal,
    basis_score: Decimal,
    weights: dict[str, Decimal],
) -> Decimal:
    """Compute a weighted composite score from sub-signal scores.

    Weighted linear combination of sub-signals. All inputs are expected
    to be in the 0-1 range. Output will be in 0-1 if weights sum to 1.0.

    Formula:
        score = weights["rate_level"] * rate_level
              + weights["trend"] * trend_score
              + weights["persistence"] * persistence
              + weights["basis"] * basis_score

    Args:
        rate_level: Normalized funding rate score (0-1).
        trend_score: Trend direction score (0-1).
        persistence: Persistence score (0-1).
        basis_score: Normalized basis spread score (0-1).
        weights: Dict with keys "rate_level", "trend", "persistence", "basis".

    Returns:
        Composite score quantized to 6 decimal places.
    """
    score = (
        weights["rate_level"] * rate_level
        + weights["trend"] * trend_score
        + weights["persistence"] * persistence
        + weights["basis"] * basis_score
    )
    return score.quantize(Decimal("0.000001"))
