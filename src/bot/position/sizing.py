"""Position size calculation with exchange constraints.

All calculations use Decimal arithmetic exclusively -- no float conversions.
Uses round_to_step from exchange/types.py for qty_step rounding (always down).

Position sizing flow:
1. Determine raw quantity from min(max_position_size_usd, available_balance) / price
2. Round down to instrument's qty_step
3. Validate against min_qty and min_notional
4. Return None if constraints not met
"""

from decimal import Decimal

from bot.config import TradingSettings
from bot.exchange.types import InstrumentInfo, round_to_step


class PositionSizer:
    """Calculates position sizes respecting exchange constraints and config limits.

    All quantities are Decimal. Rounding is always DOWN to prevent exceeding
    balance or position limits.

    Args:
        settings: Trading settings containing max_position_size_usd.
    """

    def __init__(self, settings: TradingSettings) -> None:
        self._settings = settings

    def calculate_quantity(
        self,
        price: Decimal,
        available_balance: Decimal,
        instrument: InstrumentInfo,
    ) -> Decimal | None:
        """Calculate the maximum valid order quantity for a single instrument.

        Steps:
        1. max_by_config = max_position_size_usd / price
        2. max_by_balance = available_balance / price
        3. raw_qty = min(max_by_config, max_by_balance)
        4. rounded_qty = round_to_step(raw_qty, instrument.qty_step)
        5. If rounded_qty < min_qty: return None
        6. If rounded_qty * price < min_notional: return None
        7. Return rounded_qty

        Args:
            price: Current asset price in quote currency.
            available_balance: Available balance in quote currency.
            instrument: Exchange instrument constraints.

        Returns:
            Valid quantity rounded to step, or None if constraints not met.
        """
        max_by_config = self._settings.max_position_size_usd / price
        max_by_balance = available_balance / price
        raw_qty = min(max_by_config, max_by_balance)

        rounded_qty = round_to_step(raw_qty, instrument.qty_step)

        if rounded_qty < instrument.min_qty:
            return None

        notional = rounded_qty * price
        if notional < instrument.min_notional:
            return None

        return rounded_qty

    def calculate_matching_quantity(
        self,
        price: Decimal,
        available_balance: Decimal,
        spot_instrument: InstrumentInfo,
        perp_instrument: InstrumentInfo,
    ) -> Decimal | None:
        """Calculate a single quantity valid for both spot and perp legs.

        Uses the COARSER (larger) qty_step of the two instruments so the
        resulting quantity is valid on both. Also validates against both
        instruments' min_qty and min_notional.

        Args:
            price: Current asset price (assumed similar for spot and perp).
            available_balance: Available balance in quote currency.
            spot_instrument: Spot instrument constraints.
            perp_instrument: Perpetual instrument constraints.

        Returns:
            Valid quantity for both legs, or None if constraints not met.
        """
        coarser_step = max(spot_instrument.qty_step, perp_instrument.qty_step)
        higher_min_qty = max(spot_instrument.min_qty, perp_instrument.min_qty)
        higher_min_notional = max(
            spot_instrument.min_notional, perp_instrument.min_notional
        )

        max_by_config = self._settings.max_position_size_usd / price
        max_by_balance = available_balance / price
        raw_qty = min(max_by_config, max_by_balance)

        rounded_qty = round_to_step(raw_qty, coarser_step)

        if rounded_qty < higher_min_qty:
            return None

        notional = rounded_qty * price
        if notional < higher_min_notional:
            return None

        return rounded_qty

    def validate_matching_quantity(
        self,
        spot_qty: Decimal,
        perp_qty: Decimal,
        tolerance: Decimal = Decimal("0.02"),
    ) -> bool:
        """Validate that spot and perp fill quantities are close enough.

        After order fills, the actual filled quantities may differ slightly
        due to different qty_step values. This checks that the drift is
        within acceptable tolerance.

        Args:
            spot_qty: Filled spot quantity.
            perp_qty: Filled perp quantity.
            tolerance: Maximum allowed relative drift (default 2%).

        Returns:
            True if quantities are within tolerance.
        """
        if spot_qty == perp_qty:
            return True

        larger = max(spot_qty, perp_qty)
        if larger == Decimal("0"):
            return False

        drift = abs(spot_qty - perp_qty) / larger
        return drift <= tolerance