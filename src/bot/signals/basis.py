"""Basis spread computation for funding rate arbitrage signals.

The basis spread measures the premium/discount of the perpetual contract
relative to spot price. A positive basis (perp > spot) is consistent with
positive funding rates -- longs pay shorts.

CRITICAL: All values use Decimal. Never use float for prices or spreads.
"""

from decimal import Decimal


def compute_basis_spread(spot_price: Decimal, perp_price: Decimal) -> Decimal:
    """Compute the basis spread between perpetual and spot prices.

    Formula: (perp_price - spot_price) / spot_price

    Args:
        spot_price: The spot (or index) price.
        perp_price: The perpetual contract price.

    Returns:
        Basis spread as a Decimal. Positive means perp trades at a premium.
        Returns Decimal("0") if spot_price is zero or negative.
    """
    if spot_price <= Decimal("0"):
        return Decimal("0")
    return (perp_price - spot_price) / spot_price


def normalize_basis_score(
    basis_spread: Decimal, cap: Decimal = Decimal("0.01")
) -> Decimal:
    """Normalize basis spread to a 0-1 score for composite signal use.

    Uses absolute value because both positive and negative basis are
    informative -- magnitude matters for signal strength. The cap prevents
    extreme basis values from dominating the composite score.

    Formula: min(abs(basis_spread) / cap, Decimal("1"))

    Args:
        basis_spread: Raw basis spread from compute_basis_spread.
        cap: Maximum basis spread that maps to score 1.0. Default 1% (0.01).

    Returns:
        Normalized score in [0, 1] range.
    """
    if cap <= Decimal("0"):
        return Decimal("0")
    return min(abs(basis_spread) / cap, Decimal("1"))
