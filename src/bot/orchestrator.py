"""Main bot orchestrator -- wires all components and runs the main loop.

Integrates funding rate monitoring, position management, P&L tracking,
delta validation, opportunity ranking, risk management, and emergency
stop into a single autonomous trading loop.

Phase 1: Monitors funding rates, logs opportunities, simulates funding
settlement every 8h, and provides manual open/close convenience methods.

Phase 2: Autonomous scan-rank-decide-execute cycle. Each iteration:
  1. SCAN: Get all funding rates from monitor cache
  2. RANK: Score each pair by net yield after fees
  3. DECIDE & EXECUTE: Close unprofitable, open profitable
  4. MONITOR: Check margin ratio
  5. LOG: Position status

PAPR-02: Works identically with PaperExecutor and LiveExecutor --
the orchestrator delegates to PositionManager which uses the swappable
Executor ABC. No branching on executor type.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import TYPE_CHECKING

from bot.config import AppSettings, HistoricalDataSettings, RuntimeConfig
from bot.exchange.client import ExchangeClient
from bot.logging import get_logger
from bot.market_data.funding_monitor import FundingMonitor
from bot.market_data.opportunity_ranker import OpportunityRanker
from bot.market_data.ticker_service import TickerService
from bot.models import OpportunityScore, Position
from bot.pnl.fee_calculator import FeeCalculator
from bot.pnl.tracker import PnLTracker
from bot.position.delta_validator import DeltaValidator
from bot.position.manager import PositionManager
from bot.risk.emergency import EmergencyController
from bot.risk.manager import RiskManager

if TYPE_CHECKING:
    from bot.data.fetcher import HistoricalDataFetcher
    from bot.data.store import HistoricalDataStore

from bot.data.pair_selector import select_top_pairs

logger = get_logger(__name__)

# Funding settlement interval: 8 hours in seconds
_FUNDING_SETTLEMENT_INTERVAL = 8 * 60 * 60  # 28800 seconds


class Orchestrator:
    """Main bot loop integrating all components.

    Phase 2: Autonomous scan-rank-decide-execute cycle with risk
    management and emergency stop. Each iteration scans funding rates,
    ranks opportunities by net yield, opens profitable positions within
    risk limits, closes unprofitable ones, and monitors margin ratio.

    Args:
        settings: Application-wide settings.
        exchange_client: Exchange API client.
        funding_monitor: Funding rate polling service.
        ticker_service: Shared price cache.
        position_manager: Position lifecycle manager.
        pnl_tracker: P&L and funding tracker.
        delta_validator: Delta neutrality checker.
        fee_calculator: Fee computation service.
        risk_manager: Pre-trade and runtime risk engine.
        ranker: Opportunity ranking engine.
        emergency_controller: Emergency stop controller.
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
        risk_manager: RiskManager,
        ranker: OpportunityRanker,
        emergency_controller: EmergencyController | None = None,
        data_fetcher: HistoricalDataFetcher | None = None,
        data_store: HistoricalDataStore | None = None,
        historical_settings: HistoricalDataSettings | None = None,
    ) -> None:
        self._settings = settings
        self._exchange_client = exchange_client
        self._funding_monitor = funding_monitor
        self._ticker_service = ticker_service
        self._position_manager = position_manager
        self._pnl_tracker = pnl_tracker
        self._delta_validator = delta_validator
        self._fee_calculator = fee_calculator
        self._risk_manager = risk_manager
        self._ranker = ranker
        self._emergency_controller = emergency_controller
        self._data_fetcher = data_fetcher
        self._data_store = data_store
        self._historical_settings = historical_settings
        self._running = False
        self._last_funding_check: float = 0.0
        self._cycle_lock = asyncio.Lock()
        self._runtime_config: RuntimeConfig | None = None
        self._data_fetch_progress: dict | None = None

    async def start(self) -> None:
        """Start the orchestrator: begin funding monitor, then run main loop.

        Starts the FundingMonitor background task, ensures historical data
        is ready (blocks until complete if enabled), then enters the main
        autonomous trading loop. Handles graceful shutdown via stop().
        """
        logger.info(
            "orchestrator_starting",
            mode=self._settings.trading.mode,
        )
        await self._funding_monitor.start()

        # Block on historical data fetch before entering trading loop
        await self._ensure_historical_data()

        self._running = True
        self._last_funding_check = time.time()

        try:
            await self._run_loop()
        finally:
            await self._funding_monitor.stop()
            logger.info("orchestrator_stopped")

    async def stop(self) -> None:
        """Signal the orchestrator to stop gracefully.

        Closes all open positions before stopping to ensure clean shutdown.
        """
        logger.info("orchestrator_stopping_gracefully")
        self._running = False
        # Close all positions gracefully on shutdown
        for position in self._position_manager.get_open_positions():
            try:
                await self.close_position(position.id)
            except Exception as e:
                logger.error(
                    "graceful_close_failed",
                    position_id=position.id,
                    error=str(e),
                )

    async def _run_loop(self) -> None:
        """Main autonomous trading loop.

        Each iteration runs the autonomous cycle under a lock to prevent
        overlapping cycles, then checks funding settlement and sleeps.
        """
        while self._running:
            try:
                async with self._cycle_lock:
                    await self._autonomous_cycle()
                self._check_funding_settlement()
                await asyncio.sleep(self._settings.trading.scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("orchestrator_cycle_error", error=str(e), exc_info=True)
                await asyncio.sleep(10)

    async def _ensure_historical_data(self) -> None:
        """Fetch all missing historical data on startup (v1.1 optional feature).

        Guards on data_fetcher being set (None = feature disabled).
        Selects top pairs by volume from current funding rates and delegates
        to the fetcher's ensure_data_ready() which blocks until complete.
        """
        if self._data_fetcher is None:
            return

        # Wait for funding monitor to complete its first poll (up to 30s)
        all_rates = self._funding_monitor.get_all_funding_rates()
        if not all_rates:
            logger.info("waiting_for_funding_rates", note="Waiting for first funding poll before historical fetch")
            for _ in range(60):
                await asyncio.sleep(0.5)
                all_rates = self._funding_monitor.get_all_funding_rates()
                if all_rates:
                    break
        if not all_rates:
            logger.warning(
                "no_funding_rates_for_historical_data",
                note="Funding monitor did not return rates after 30s, skipping initial historical fetch",
            )
            return

        count = (
            self._historical_settings.top_pairs_count
            if self._historical_settings
            else 20
        )
        top_pairs = select_top_pairs(all_rates, count=count)

        # Update tracked pairs in store
        if self._data_store is not None:
            for symbol in top_pairs:
                # Find the volume for this symbol from funding rates
                fr_match = next(
                    (fr for fr in all_rates if fr.symbol == symbol), None
                )
                volume = fr_match.volume_24h if fr_match else Decimal("0")
                await self._data_store.update_tracked_pair(symbol, volume)

        # Progress callback for dashboard live progress
        async def _progress_cb(symbol: str, current: int, total: int) -> None:
            self._data_fetch_progress = {
                "current_symbol": symbol,
                "current_index": current,
                "total": total,
                "status": "fetching",
            }

        self._data_fetch_progress = {"status": "starting", "total": len(top_pairs)}
        await self._data_fetcher.ensure_data_ready(top_pairs, progress_callback=_progress_cb)
        self._data_fetch_progress = {"status": "complete"}

        logger.info("historical_data_ready", pairs=len(top_pairs))

    async def _autonomous_cycle(self) -> None:
        """One iteration of the autonomous trading loop.

        Implements the scan-rank-decide-execute pattern:
        0. APPLY: Runtime config overrides (if set by dashboard)
        0.5. UPDATE: Historical data incremental update (if enabled)
        1. SCAN: Get all funding rates from monitor cache
        2. RANK: Score each pair by net yield after fees
        3. DECIDE & EXECUTE: Close unprofitable, open profitable
        4. MONITOR: Check margin ratio
        5. LOG: Position status
        """
        # 0. APPLY: Runtime config overrides from dashboard
        self._apply_runtime_config()

        # 0.5. UPDATE HISTORICAL DATA (if enabled)
        if self._data_fetcher is not None:
            try:
                all_rates_for_data = self._funding_monitor.get_all_funding_rates()
                if all_rates_for_data:
                    count = (
                        self._historical_settings.top_pairs_count
                        if self._historical_settings
                        else 20
                    )
                    top_pairs = select_top_pairs(all_rates_for_data, count=count)
                    await self._data_fetcher.incremental_update(top_pairs)
            except Exception as e:
                logger.warning(
                    "historical_data_update_failed",
                    error=str(e),
                    exc_info=True,
                )

        # 1. SCAN: Get all funding rates from monitor cache
        all_rates = self._funding_monitor.get_all_funding_rates()
        if not all_rates:
            logger.debug("no_funding_rates_available")
            return

        # 2. RANK: Score each pair by net yield after fees
        markets = self._exchange_client.get_markets()
        opportunities = self._ranker.rank_opportunities(
            funding_rates=all_rates,
            markets=markets,
            min_rate=self._settings.trading.min_funding_rate,
            min_volume_24h=self._settings.risk.min_volume_24h,
            min_holding_periods=self._settings.risk.min_holding_periods,
        )

        if opportunities:
            top = opportunities[0]
            logger.info(
                "opportunities_ranked",
                count=len(opportunities),
                top_pair=top.perp_symbol,
                top_annualized_yield=str(top.annualized_yield),
            )

        # 3. DECIDE & EXECUTE: Close unprofitable, open profitable
        await self._close_unprofitable_positions()
        await self._open_profitable_positions(opportunities)

        # 4. MONITOR: Check margin ratio
        await self._check_margin_ratio()

        # 5. LOG: Position status
        self._log_position_status()

    async def _close_unprofitable_positions(self) -> None:
        """Close positions where funding rate dropped below exit threshold (EXEC-02)."""
        for position in self._position_manager.get_open_positions():
            rate_data = self._funding_monitor.get_funding_rate(position.perp_symbol)
            if rate_data is None or rate_data.rate < self._settings.risk.exit_funding_rate:
                reason = (
                    "rate_unavailable"
                    if rate_data is None
                    else f"rate_below_exit_{rate_data.rate}"
                )
                logger.info(
                    "closing_unprofitable_position",
                    position_id=position.id,
                    perp_symbol=position.perp_symbol,
                    reason=reason,
                )
                try:
                    await self.close_position(position.id)
                except Exception as e:
                    logger.error(
                        "close_unprofitable_failed",
                        position_id=position.id,
                        error=str(e),
                    )

    async def _open_profitable_positions(
        self, opportunities: list[OpportunityScore]
    ) -> None:
        """Open positions on top-ranked pairs within risk limits (MKTD-02, MKTD-03)."""
        for opp in opportunities:
            if not opp.passes_filters:
                continue

            # Check risk limits
            can_open, reason = self._risk_manager.check_can_open(
                symbol=opp.perp_symbol,
                position_size_usd=self._settings.trading.max_position_size_usd,
                current_positions=self._position_manager.get_open_positions(),
            )
            if not can_open:
                logger.debug(
                    "risk_check_rejected",
                    symbol=opp.perp_symbol,
                    reason=reason,
                )
                continue

            # Open position
            try:
                await self.open_position(opp.spot_symbol, opp.perp_symbol)
                logger.info(
                    "autonomous_position_opened",
                    spot_symbol=opp.spot_symbol,
                    perp_symbol=opp.perp_symbol,
                    annualized_yield=str(opp.annualized_yield),
                )
            except Exception as e:
                logger.error(
                    "autonomous_open_failed",
                    symbol=opp.perp_symbol,
                    error=str(e),
                )

    async def _check_margin_ratio(self) -> None:
        """RISK-05: Check margin ratio and trigger alerts or emergency stop."""
        try:
            mm_rate, is_alert = await self._risk_manager.check_margin_ratio()
            if self._risk_manager.is_margin_critical(mm_rate):
                logger.critical(
                    "margin_critical_triggering_emergency",
                    mm_rate=str(mm_rate),
                )
                if self._emergency_controller is not None:
                    await self._emergency_controller.trigger(
                        f"margin_critical_{mm_rate}"
                    )
                return
            if is_alert:
                logger.warning(
                    "margin_alert",
                    mm_rate=str(mm_rate),
                    threshold=str(self._settings.risk.margin_alert_threshold),
                )
        except Exception as e:
            logger.error("margin_check_failed", error=str(e))

    def _log_position_status(self) -> None:
        """Log P&L status for all open positions."""
        for position in self._position_manager.get_open_positions():
            pnl = self._pnl_tracker.get_total_pnl(position.id)
            logger.info(
                "position_status",
                position_id=position.id,
                symbol=position.perp_symbol,
                net_pnl=str(pnl["net_pnl"]),
                funding_collected=str(pnl["total_funding"]),
            )

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
            Dict with: running, open_positions_count, mode, portfolio_summary,
            emergency_triggered.
        """
        portfolio = self._pnl_tracker.get_portfolio_summary()

        open_positions = self._position_manager.get_open_positions()

        return {
            "running": self._running,
            "open_positions_count": len(open_positions),
            "mode": self._settings.trading.mode,
            "portfolio_summary": portfolio,
            "emergency_triggered": (
                self._emergency_controller.triggered
                if self._emergency_controller is not None
                else False
            ),
        }

    async def get_data_status(self) -> dict | None:
        """Return data status for dashboard widget.

        Returns None if historical data feature is not enabled (data_store is None).
        """
        if self._data_store is None:
            return None
        return await self._data_store.get_data_status()

    @property
    def data_fetch_progress(self) -> dict | None:
        """Current data fetch progress for dashboard live updates."""
        return self._data_fetch_progress

    def set_emergency_controller(
        self, controller: EmergencyController
    ) -> None:
        """Set the emergency controller (resolves circular dependency).

        Args:
            controller: The EmergencyController instance.
        """
        self._emergency_controller = controller

    @property
    def is_running(self) -> bool:
        """Whether the orchestrator main loop is active."""
        return self._running

    @property
    def runtime_config(self) -> RuntimeConfig | None:
        """Current runtime config overlay, if set."""
        return self._runtime_config

    @runtime_config.setter
    def runtime_config(self, config: RuntimeConfig) -> None:
        self._runtime_config = config
        logger.info("runtime_config_updated", config=str(config))

    def _apply_runtime_config(self) -> None:
        """Apply runtime config overrides to settings if set.

        Called at the start of each autonomous cycle so dashboard changes
        take effect on the next iteration without restarting.
        """
        rc = self._runtime_config
        if rc is None:
            return
        if rc.min_funding_rate is not None:
            self._settings.trading.min_funding_rate = rc.min_funding_rate
        if rc.max_position_size_usd is not None:
            self._settings.trading.max_position_size_usd = rc.max_position_size_usd
        if rc.exit_funding_rate is not None:
            self._settings.risk.exit_funding_rate = rc.exit_funding_rate
        if rc.max_simultaneous_positions is not None:
            self._settings.risk.max_simultaneous_positions = rc.max_simultaneous_positions
        if rc.max_position_size_per_pair is not None:
            self._settings.risk.max_position_size_per_pair = rc.max_position_size_per_pair
        if rc.min_volume_24h is not None:
            self._settings.risk.min_volume_24h = rc.min_volume_24h
        if rc.scan_interval is not None:
            self._settings.trading.scan_interval = rc.scan_interval

    async def restart(self) -> None:
        """Restart the orchestrator (start the run loop after being stopped).

        Used by dashboard DASH-04 to start the bot after it has been stopped.
        Does NOT close positions on stop (that's graceful shutdown behavior).
        Restarts the funding monitor and main loop.
        """
        if self._running:
            logger.info("orchestrator_restart_already_running")
            return
        logger.info("orchestrator_restarting")
        await self._funding_monitor.start()
        self._running = True
        self._last_funding_check = time.time()
        # Run loop as a background task so caller doesn't block
        asyncio.create_task(self._run_loop_with_cleanup())

    async def _run_loop_with_cleanup(self) -> None:
        """Run loop wrapper that cleans up funding monitor on exit."""
        try:
            await self._run_loop()
        finally:
            await self._funding_monitor.stop()
            logger.info("orchestrator_stopped")
