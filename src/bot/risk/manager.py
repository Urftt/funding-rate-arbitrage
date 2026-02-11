"""Pre-trade risk checks.

Phase 1: Basic position size validation only.
Phase 2: Will add comprehensive risk management (RISK-01 through RISK-05)
including drawdown limits, exposure tracking, and correlation checks.
"""

from decimal import Decimal

from bot.config import TradingSettings
from bot.logging import get_logger

logger = get_logger(__name__)


class RiskManager:
    """Pre-trade risk manager enforcing position size limits.

    Phase 1 provides a simple max-position-size check. Phase 2 will
    expand this with drawdown protection, exposure limits, and more.

    Args:
        settings: Trading settings containing max_position_size_usd.
    """

    def __init__(self, settings: TradingSettings) -> None:
        self._settings = settings

    def check_can_open(
        self, position_size_usd: Decimal
    ) -> tuple[bool, str]:
        """Check if a new position of the given size can be opened.

        Args:
            position_size_usd: Proposed position size in USD.

        Returns:
            Tuple of (allowed, reason). If allowed is True, reason is "".
            If allowed is False, reason explains why.
        """
        if position_size_usd <= Decimal("0"):
            return False, "Position size must be positive"

        if position_size_usd > self._settings.max_position_size_usd:
            return False, (
                f"Position size {position_size_usd} exceeds max "
                f"{self._settings.max_position_size_usd}"
            )

        return True, ""
