"""Exchange-specific type definitions and utility functions.

All monetary values use Decimal. Never use float for prices, quantities, or fees.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class InstrumentInfo:
    """Trading constraints for an exchange instrument (spot or perpetual).

    Fetched from exchange instrument-info endpoints. Used by PositionSizer
    to validate and round quantities before order placement.
    """

    symbol: str
    min_qty: Decimal
    max_qty: Decimal
    qty_step: Decimal
    min_notional: Decimal = Decimal("0")
    tick_size: Decimal = Decimal("0.01")


def round_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round a value down to the nearest step increment.

    Uses integer division to ensure we always round DOWN (never up),
    which prevents exceeding available balance or position limits.

    Args:
        value: The raw quantity to round.
        step: The minimum increment (e.g., 0.001 for BTC).

    Returns:
        The value rounded down to the nearest step.
    """
    return (value // step) * step
