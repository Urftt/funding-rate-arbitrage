"""Dynamic position sizing with signal-conviction scaling and portfolio cap.

DynamicSizer maps a composite signal score to a USD budget, then delegates
to the existing PositionSizer for exchange constraint validation.

SIZE-01: Position size scales with signal confidence.
SIZE-02: Total portfolio exposure capped at configurable limit.
SIZE-03: Delegates to PositionSizer for qty_step, min_qty, min_notional.
"""

from decimal import Decimal

import structlog

from bot.config import DynamicSizingSettings
from bot.exchange.types import InstrumentInfo
from bot.position.sizing import PositionSizer

logger = structlog.get_logger(__name__)


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

        Formula:
        1. fraction = min_frac + (max_frac - min_frac) * signal_score
        2. raw_budget = max_position_size_usd * fraction
        3. remaining = max_portfolio_exposure - current_exposure
        4. Return min(raw_budget, remaining), or None if remaining <= 0

        Args:
            signal_score: Composite signal score in [0, 1] range.
            current_exposure: Sum of all open position notional values in USD.

        Returns:
            USD budget for the position, or None if portfolio cap reached.
        """
        # 1. Map score to allocation fraction (linear interpolation)
        fraction = (
            self._settings.min_allocation_fraction
            + (
                self._settings.max_allocation_fraction
                - self._settings.min_allocation_fraction
            )
            * signal_score
        )

        # 2. Raw budget from per-pair max
        raw_budget = self._max_position_size_usd * fraction

        # 3. Portfolio exposure cap
        remaining = self._settings.max_portfolio_exposure - current_exposure
        if remaining <= Decimal("0"):
            logger.info(
                "portfolio_cap_reached",
                current_exposure=str(current_exposure),
                max_exposure=str(self._settings.max_portfolio_exposure),
            )
            return None

        # 4. Effective budget is the smaller of raw and remaining
        effective_budget = min(raw_budget, remaining)

        logger.debug(
            "signal_budget_computed",
            signal_score=str(signal_score),
            fraction=str(fraction),
            raw_budget=str(raw_budget),
            remaining=str(remaining),
            effective_budget=str(effective_budget),
        )

        return effective_budget

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
        budget = self.compute_signal_budget(signal_score, current_exposure)
        if budget is None:
            return None

        # Cap available balance by the signal-adjusted budget
        effective_balance = min(available_balance, budget)

        # Delegate to PositionSizer for exchange constraint validation (SIZE-03)
        return self._sizer.calculate_matching_quantity(
            price=price,
            available_balance=effective_balance,
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )
