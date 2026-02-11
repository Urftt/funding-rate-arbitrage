"""Main bot orchestrator -- wires all components and runs the main loop.

Integrates funding rate monitoring, position management, P&L tracking,
and delta validation into a single state machine.

Phase 1: Monitors funding rates, logs opportunities, simulates funding
settlement every 8h, and provides manual open/close convenience methods.
Phase 2 adds autonomous trading logic.

PAPR-02: Works identically with PaperExecutor and LiveExecutor --
the orchestrator delegates to PositionManager which uses the swappable
Executor ABC. No branching on executor type.
"""

import asyncio
import time

from decimal import Decimal

from bot.config import AppSettings
from bot.exchange.client import ExchangeClient
from bot.logging import get_logger
from bot.market_data.funding_monitor import FundingMonitor
from bot.market_data.ticker_service import TickerService
from bot.models import Position
from bot.pnl.fee_calculator import FeeCalculator
from bot.pnl.tracker import PnLTracker
from bot.position.delta_validator import DeltaValidator
from bot.position.manager import PositionManager

logger = get_logger(__name__)

# Funding settlement interval: 8 hours in seconds
_FUNDING_SETTLEMENT_INTERVAL = 8 * 60 * 60  # 28800 seconds


class Orchestrator:
    """Main bot loop integrating all components.

    Monitors funding rates, tracks position P&L, simulates funding
    settlement, and provides convenience methods for manual position
    management in Phase 1.

    NOTE: Phase 1 orchestrator is deliberately simple -- it monitors
    and logs. It does NOT auto-open positions. Phase 2 adds autonomous
    trading logic.

    Args:
        settings: Application-wide settings.
        exchange_client: Exchange API client.
        funding_monitor: Funding rate polling service.
        ticker_service: Shared price cache.
        position_manager: Position lifecycle manager.
        pnl_tracker: P&L and funding tracker.
        delta_validator: Delta neutrality checker.
        fee_calculator: Fee computation service.
    """

    def __init__(
        self,
        settings: AppSettings,
        exchange_client: ExchangeClient,
        funding_monitor: FundingMonitor,
        ticker_service: TickerService,
        position_manager: PositionManager,
        pnl_tracker: PnLTracker,
        delta_validator: DeltaValidator,
        fee_calculator: FeeCalculator,
    ) -> None:
        self._settings = settings
        self._exchange_client = exchange_client
        self._funding_monitor = funding_monitor
        self._ticker_service = ticker_service
        self._position_manager = position_manager
        self._pnl_tracker = pnl_tracker
        self._delta_validator = delta_validator
        self._fee_calculator = fee_calculator
        self._running = False
        self._last_funding_check: float = 0.0

    async def start(self) -> None:
        """Start the orchestrator: begin funding monitor, then run main loop.

        Starts the FundingMonitor background task and enters the main
        monitoring loop. Handles graceful shutdown via stop().
        """
        logger.info(
            "orchestrator_starting",
            mode=self._settings.trading.mode,
        )
        await self._funding_monitor.start()
        self._running = True
        self._last_funding_check = time.time()

        try:
            await self._run_loop()
        finally:
            await self._funding_monitor.stop()
            logger.info("orchestrator_stopped")

    async def stop(self) -> None:
        """Signal the orchestrator to stop gracefully."""
        logger.info("orchestrator_stopping")
        self._running = False

    async def _run_loop(self) -> None:
        """Main monitoring loop.

        Each iteration:
        1. Read profitable funding pairs from monitor
        2. Log current opportunities
        3. Check existing positions and log P&L status
        4. Simulate funding settlement if 8h has passed
        5. Sleep before next iteration
        """
        while self._running:
            try:
                # 1. Read profitable pairs from funding monitor cache
                profitable_pairs = self._funding_monitor.get_profitable_pairs(
                    self._settings.trading.min_funding_rate
                )

                # 2. Log current opportunities
                if profitable_pairs:
                    logger.info(
                        "profitable_pairs_found",
                        count=len(profitable_pairs),
                        top_pair=profitable_pairs[0].symbol,
                        top_rate=str(profitable_pairs[0].rate),
                    )

                # 3. Check existing positions for delta validity and log P&L
                for position in self._position_manager.get_open_positions():
                    pnl = self._pnl_tracker.get_total_pnl(position.id)
                    logger.info(
                        "position_status",
                        position_id=position.id,
                        symbol=position.perp_symbol,
                        net_pnl=str(pnl["net_pnl"]),
                        funding_collected=str(pnl["total_funding"]),
                    )

                # 4. Simulate funding settlement if 8h has passed
                self._check_funding_settlement()

                # 5. Sleep before next iteration
                scan_interval = getattr(
                    self._settings.trading, "scan_interval", None
                ) or 60
                await asyncio.sleep(scan_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("orchestrator_error", error=str(e), exc_info=True)
                await asyncio.sleep(10)

    def _check_funding_settlement(self) -> None:
        """Check if 8 hours have elapsed and trigger funding settlement.

        Looks at elapsed time since last settlement and triggers
        pnl_tracker.simulate_funding_settlement for all open positions
        if the interval has passed.
        """
        now = time.time()
        elapsed = now - self._last_funding_check

        if elapsed >= _FUNDING_SETTLEMENT_INTERVAL:
            open_positions = self._position_manager.get_open_positions()
            if open_positions:
                # Build funding rates dict from monitor cache
                all_rates = self._funding_monitor.get_all_funding_rates()
                funding_rates = {fr.symbol: fr for fr in all_rates}

                self._pnl_tracker.simulate_funding_settlement(
                    open_positions, funding_rates
                )

                logger.info(
                    "funding_settlement_triggered",
                    positions=len(open_positions),
                    elapsed_hours=round(elapsed / 3600, 2),
                )

            self._last_funding_check = now

    async def open_position(
        self,
        spot_symbol: str,
        perp_symbol: str,
        available_balance: Decimal | None = None,
    ) -> Position:
        """Convenience method: open a delta-neutral position.

        Wraps position_manager.open_position with balance fetch and
        instrument lookup.

        Args:
            spot_symbol: Spot trading pair (e.g., "BTC/USDT").
            perp_symbol: Perp trading pair (e.g., "BTC/USDT:USDT").
            available_balance: Available balance. If None, fetches from exchange.

        Returns:
            The opened Position.
        """
        if available_balance is None:
            balance_data = await self._exchange_client.fetch_balance()
            usdt_balance = balance_data.get("USDT", {})
            free = usdt_balance.get("free", 0) if isinstance(usdt_balance, dict) else 0
            available_balance = Decimal(str(free))

        spot_instrument = await self._exchange_client.get_instrument_info(spot_symbol)
        perp_instrument = await self._exchange_client.get_instrument_info(perp_symbol)

        position = await self._position_manager.open_position(
            spot_symbol=spot_symbol,
            perp_symbol=perp_symbol,
            available_balance=available_balance,
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )

        # Record P&L tracking
        self._pnl_tracker.record_open(position, position.entry_fee_total)

        logger.info(
            "position_opened_via_orchestrator",
            position_id=position.id,
            spot_symbol=spot_symbol,
            perp_symbol=perp_symbol,
        )

        return position

    async def close_position(self, position_id: str) -> None:
        """Convenience method: close a delta-neutral position.

        Wraps position_manager.close_position and records P&L.

        Args:
            position_id: ID of the position to close.
        """
        spot_result, perp_result = await self._position_manager.close_position(
            position_id
        )

        exit_fee = spot_result.fee + perp_result.fee

        self._pnl_tracker.record_close(
            position_id=position_id,
            spot_exit_price=spot_result.filled_price,
            perp_exit_price=perp_result.filled_price,
            exit_fee=exit_fee,
        )

        logger.info(
            "position_closed_via_orchestrator",
            position_id=position_id,
            exit_fee=str(exit_fee),
        )

    def get_status(self) -> dict:
        """Return current orchestrator status.

        Returns:
            Dict with: running, open_positions_count, mode, portfolio_summary.
        """
        portfolio = self._pnl_tracker.get_portfolio_summary()

        return {
            "running": self._running,
            "open_positions_count": len(
                self._position_manager.get_open_positions()
            ),
            "mode": self._settings.trading.mode,
            "portfolio_summary": portfolio,
        }
