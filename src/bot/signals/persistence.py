"""Funding rate persistence scoring (SGNL-02).

Quantifies how long a funding rate has stayed elevated above a threshold.
Walks backward from the most recent rate, counting consecutive periods,
and normalizes to a 0-1 score.

CRITICAL: All computations use Decimal. Never use float.
"""

from decimal import Decimal


def compute_persistence_score(
    funding_rates: list[Decimal],
    threshold: Decimal,
    max_periods: int = 30,
) -> Decimal:
    """Score how long the funding rate has stayed above threshold.

    Walks backward from the most recent rate, counting consecutive periods
    where ``rate >= threshold``. Breaks on the first rate below threshold.
    The count is normalized by ``max_periods`` and capped at Decimal("1").

    Args:
        funding_rates: Historical funding rates ordered oldest-first.
        threshold: Minimum rate to count as "elevated".
        max_periods: Maximum periods for normalization (score = count / max_periods).

    Returns:
        Decimal in [0, 1] representing persistence strength.
        Returns Decimal("0") if funding_rates is empty.
    """
    if not funding_rates:
        return Decimal("0")

    consecutive = 0
    for rate in reversed(funding_rates):
        if rate >= threshold:
            consecutive += 1
        else:
            break

    return min(Decimal(consecutive) / Decimal(max_periods), Decimal("1"))
