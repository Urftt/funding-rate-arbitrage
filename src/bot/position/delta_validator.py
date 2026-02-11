"""Delta neutrality validation for spot+perp positions.

RISK-04: Detects drift between spot and perp quantities and reports
tolerance violations. Used by PositionManager after opening positions
and by monitoring loops to check ongoing delta neutrality.
"""

import time
from decimal import Decimal

from bot.config import TradingSettings
from bot.logging import get_logger
from bot.models import DeltaStatus, Position

logger = get_logger(__name__)


class DeltaValidator:
    """Validates that spot and perp quantities stay within drift tolerance.

    Args:
        settings: Trading settings containing delta_drift_tolerance.
    """

    def __init__(self, settings: TradingSettings) -> None:
        self._settings = settings

    def validate(
        self,
        spot_qty: Decimal,
        perp_qty: Decimal,
        position_id: str = "",
    ) -> DeltaStatus:
        """Check if spot and perp quantities are within drift tolerance.

        Drift is calculated as:
            drift_pct = abs(spot_qty - perp_qty) / max(spot_qty, perp_qty)

        If both quantities are zero, drift is zero (within tolerance).

        Args:
            spot_qty: Spot leg quantity.
            perp_qty: Perp leg quantity.
            position_id: Optional position ID for tracking.

        Returns:
            DeltaStatus with drift calculation and tolerance check.
        """
        max_qty = max(spot_qty, perp_qty)

        if max_qty > Decimal("0"):
            drift_pct = abs(spot_qty - perp_qty) / max_qty
        else:
            drift_pct = Decimal("0")

        is_within_tolerance = drift_pct <= self._settings.delta_drift_tolerance

        status = DeltaStatus(
            position_id=position_id,
            spot_qty=spot_qty,
            perp_qty=perp_qty,
            drift_pct=drift_pct,
            is_within_tolerance=is_within_tolerance,
            checked_at=time.time(),
        )

        if not is_within_tolerance:
            logger.warning(
                "delta_drift_exceeded",
                position_id=position_id,
                drift_pct=str(drift_pct),
                tolerance=str(self._settings.delta_drift_tolerance),
                spot_qty=str(spot_qty),
                perp_qty=str(perp_qty),
            )

        return status

    def validate_position(
        self,
        position: Position,
        current_spot_qty: Decimal,
        current_perp_qty: Decimal,
    ) -> DeltaStatus:
        """Validate delta neutrality for an existing position.

        Convenience wrapper around validate() that uses the position's ID.

        Args:
            position: The position to validate.
            current_spot_qty: Current spot leg quantity.
            current_perp_qty: Current perp leg quantity.

        Returns:
            DeltaStatus with position ID populated.
        """
        return self.validate(
            spot_qty=current_spot_qty,
            perp_qty=current_perp_qty,
            position_id=position.id,
        )
