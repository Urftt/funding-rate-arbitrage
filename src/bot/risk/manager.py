"""Pre-trade and runtime risk engine.

Phase 2: Comprehensive risk management implementing RISK-01 through RISK-05:
  - RISK-01: Per-pair position size limits
  - RISK-02: Max simultaneous positions
  - RISK-05: Margin ratio monitoring with alert/critical thresholds

Uses RiskSettings for all thresholds. Exchange client is optional for
paper mode, which uses simulate_paper_margin instead.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING

from bot.config import RiskSettings
from bot.logging import get_logger

if TYPE_CHECKING:
    from bot.exchange.client import ExchangeClient
    from bot.models import Position

logger = get_logger(__name__)


class RiskManager:
    """Pre-trade and runtime risk manager.

    Enforces per-pair size limits, max simultaneous positions, duplicate
    pair prevention, and margin ratio monitoring with alert/critical
    thresholds.

    Args:
        settings: Risk settings containing all thresholds.
        exchange_client: Live exchange client for margin monitoring.
            None in paper mode.
        paper_margin_fn: Callable returning simulated margin dict for
            paper mode. Used when exchange_client is None.
    """

    def __init__(
        self,
        settings: RiskSettings,
        exchange_client: ExchangeClient | None = None,
        paper_margin_fn: Callable[[], dict] | None = None,
    ) -> None:
        self._settings = settings
        self._exchange_client = exchange_client
        self._paper_margin_fn = paper_margin_fn

    def check_can_open(
        self,
        symbol: str,
        position_size_usd: Decimal,
        current_positions: list[Position],
    ) -> tuple[bool, str]:
        """Check if a new position can be opened.

        Validates against RISK-01 (per-pair size), RISK-02 (max positions),
        positive size, and duplicate pair prevention.

        Args:
            symbol: Perp symbol for the proposed position.
            position_size_usd: Proposed position size in USD.
            current_positions: List of currently open positions.

        Returns:
            Tuple of (allowed, reason). If allowed is True, reason is "".
        """
        if position_size_usd <= Decimal("0"):
            return False, "Position size must be positive"

        # RISK-01: Per-pair position size limit
        if position_size_usd > self._settings.max_position_size_per_pair:
            return False, (
                f"Exceeds max per-pair size: "
                f"{self._settings.max_position_size_per_pair}"
            )

        # RISK-02: Max simultaneous positions
        if len(current_positions) >= self._settings.max_simultaneous_positions:
            return False, (
                f"At max positions: "
                f"{self._settings.max_simultaneous_positions}"
            )

        # Duplicate pair prevention
        open_perp_symbols = {p.perp_symbol for p in current_positions}
        if symbol in open_perp_symbols:
            return False, f"Already have position in {symbol}"

        return True, ""

    async def check_margin_ratio(self) -> tuple[Decimal, bool]:
        """Check current maintenance margin ratio.

        RISK-05: Returns the current margin ratio and whether it exceeds
        the alert threshold.

        Uses exchange_client for live mode, paper_margin_fn for paper mode.

        Returns:
            Tuple of (mm_rate, is_alert) where is_alert is True when
            mm_rate >= margin_alert_threshold.
        """
        if self._exchange_client is not None:
            wallet_data = await self._exchange_client.fetch_wallet_balance_raw()
            mm_rate = Decimal(wallet_data.get("accountMMRate", "0"))
        elif self._paper_margin_fn is not None:
            paper_data = self._paper_margin_fn()
            mm_rate = Decimal(paper_data.get("accountMMRate", "0"))
        else:
            # No exchange client and no paper fn -- return safe defaults
            mm_rate = Decimal("0")

        is_alert = mm_rate >= self._settings.margin_alert_threshold

        if is_alert:
            logger.warning(
                "margin_alert",
                mm_rate=str(mm_rate),
                threshold=str(self._settings.margin_alert_threshold),
            )

        return mm_rate, is_alert

    def is_margin_critical(self, mm_rate: Decimal) -> bool:
        """Check if margin ratio has reached the critical threshold.

        Used by the orchestrator to trigger emergency stop.

        Args:
            mm_rate: Current maintenance margin rate.

        Returns:
            True if mm_rate >= margin_critical_threshold.
        """
        return mm_rate >= self._settings.margin_critical_threshold
