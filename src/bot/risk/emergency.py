"""Emergency stop controller with concurrent position close and retry logic.

RISK-03: User-triggered or margin-triggered emergency stop that closes all
open positions concurrently using asyncio.gather. Failed closes are retried
up to max_retries times with linear backoff.

Positions that remain open after all retries are logged at CRITICAL level
with full details (symbol, quantity) so the user can manually close them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from bot.logging import get_logger

if TYPE_CHECKING:
    from bot.models import Position
    from bot.pnl.tracker import PnLTracker
    from bot.position.manager import PositionManager

logger = get_logger(__name__)


class EmergencyController:
    """Emergency stop: close all positions immediately with retry logic.

    RISK-03: Closes all open positions concurrently via asyncio.gather.
    Each position gets up to max_retries attempts with linear backoff.
    Invokes stop_callback after closing (or attempting to close) all positions.

    Args:
        position_manager: For closing positions.
        pnl_tracker: For recording P&L on close.
        stop_callback: Async callable to stop the orchestrator.
        max_retries: Maximum retry attempts per position (default 3).
    """

    def __init__(
        self,
        position_manager: PositionManager,
        pnl_tracker: PnLTracker,
        stop_callback: Callable[[], Awaitable[None]],
        max_retries: int = 3,
    ) -> None:
        self._position_manager = position_manager
        self._pnl_tracker = pnl_tracker
        self._stop_callback = stop_callback
        self._max_retries = max_retries
        self._triggered: bool = False

    async def trigger(self, reason: str) -> tuple[list[str], list[str]]:
        """Trigger emergency stop: close all positions and halt the bot.

        If already triggered, logs a warning and returns early.

        Args:
            reason: Human-readable reason for the emergency stop.

        Returns:
            Tuple of (closed_ids, failed_ids) listing position IDs that
            were successfully closed and those that failed all retries.
        """
        if self._triggered:
            logger.warning("emergency_stop_already_triggered")
            return [], []

        self._triggered = True
        logger.critical("emergency_stop_triggered", reason=reason)

        positions = self._position_manager.get_open_positions()

        if not positions:
            logger.info("emergency_stop_no_positions")
            await self._stop_callback()
            return [], []

        # Create one close task per position, run concurrently
        tasks = [self._close_with_retry(pos) for pos in positions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        closed_ids: list[str] = []
        failed_ids: list[str] = []

        for position, result in zip(positions, results):
            if isinstance(result, Exception):
                failed_ids.append(position.id)
                logger.critical(
                    "emergency_close_failed_all_retries",
                    position_id=position.id,
                    perp_symbol=position.perp_symbol,
                    quantity=str(position.quantity),
                    error=str(result),
                )
            else:
                closed_ids.append(result)

        await self._stop_callback()

        logger.info(
            "emergency_stop_complete",
            closed=len(closed_ids),
            failed=len(failed_ids),
        )

        return closed_ids, failed_ids

    async def _close_with_retry(self, position: Position) -> str:
        """Close a single position with retry logic.

        Attempts to close the position up to max_retries times. On failure,
        waits with linear backoff before retrying.

        Args:
            position: The position to close.

        Returns:
            The position ID on success.

        Raises:
            Exception: The last exception if all retries are exhausted.
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                spot_result, perp_result = (
                    await self._position_manager.close_position(position.id)
                )

                # Record P&L from close results
                exit_fee = spot_result.fee + perp_result.fee
                self._pnl_tracker.record_close(
                    position_id=position.id,
                    spot_exit_price=spot_result.filled_price,
                    perp_exit_price=perp_result.filled_price,
                    exit_fee=exit_fee,
                )

                logger.info(
                    "emergency_position_closed",
                    position_id=position.id,
                    attempt=attempt + 1,
                )
                return position.id

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "emergency_close_retry",
                    position_id=position.id,
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    error=str(exc),
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))

        raise last_error  # type: ignore[misc]

    @property
    def triggered(self) -> bool:
        """Whether the emergency stop has been triggered."""
        return self._triggered

    def reset(self) -> None:
        """Reset the triggered flag (for testing / recovery)."""
        self._triggered = False
