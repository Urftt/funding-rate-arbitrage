"""Dynamic position sizing with signal-conviction scaling and portfolio cap.

DynamicSizer maps a composite signal score to a USD budget, then delegates
to the existing PositionSizer for exchange constraint validation.

SIZE-01: Position size scales with signal confidence.
SIZE-02: Total portfolio exposure capped at configurable limit.
SIZE-03: Delegates to PositionSizer for qty_step, min_qty, min_notional.
"""

from decimal import Decimal

from bot.config import DynamicSizingSettings
from bot.exchange.types import InstrumentInfo
from bot.position.sizing import PositionSizer


class DynamicSizer:
    """Signal-conviction-based position sizer with portfolio exposure cap.

    Wraps the existing PositionSizer, computing a signal-scaled USD budget
    before delegating to PositionSizer for exchange constraint validation.

    Args:
        position_sizer: Existing PositionSizer for exchange constraint validation.
        settings: Dynamic sizing configuration (allocation fractions, portfolio cap).
        max_position_size_usd: Per-pair maximum position size in USD (from TradingSettings).
    """

    def __init__(
        self,
        position_sizer: PositionSizer,
        settings: DynamicSizingSettings,
        max_position_size_usd: Decimal,
    ) -> None:
        self._sizer = position_sizer
        self._settings = settings
        self._max_position_size_usd = max_position_size_usd

    def compute_signal_budget(
        self,
        signal_score: Decimal,
        current_exposure: Decimal,
    ) -> Decimal | None:
        """Compute USD budget for a new position based on signal score.

        Args:
            signal_score: Composite signal score in [0, 1] range.
            current_exposure: Sum of all open position notional values in USD.

        Returns:
            USD budget for the position, or None if portfolio cap reached.
        """
        raise NotImplementedError

    def calculate_matching_quantity(
        self,
        signal_score: Decimal,
        current_exposure: Decimal,
        price: Decimal,
        available_balance: Decimal,
        spot_instrument: InstrumentInfo,
        perp_instrument: InstrumentInfo,
    ) -> Decimal | None:
        """Compute budget then delegate to PositionSizer for exchange constraints.

        Args:
            signal_score: Composite signal score in [0, 1].
            current_exposure: Current total portfolio exposure in USD.
            price: Current asset price.
            available_balance: Available balance in quote currency.
            spot_instrument: Spot instrument constraints.
            perp_instrument: Perp instrument constraints.

        Returns:
            Valid quantity for both legs, or None if constraints not met.
        """
        raise NotImplementedError
