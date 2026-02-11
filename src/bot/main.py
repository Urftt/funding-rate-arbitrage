"""Entry point for the funding rate arbitrage bot.

Wires all components together and starts the orchestrator.
Handles SIGINT/SIGTERM for graceful shutdown and SIGUSR1 for emergency stop.

Component wiring order:
1. AppSettings (configuration)
2. Logging setup
3. ExchangeClient (BybitClient or public-only)
4. TickerService (shared price cache)
5. FundingMonitor (REST polling for funding rates)
6. FeeCalculator (fee computation)
7. PositionSizer (position size calculation)
8. DeltaValidator (delta neutrality validation)
9. Executor (PaperExecutor or LiveExecutor based on mode)
10. PositionManager (position lifecycle)
11. PnLTracker (P&L and funding tracking)
12. OpportunityRanker (net yield scoring)
13. RiskManager (pre-trade and runtime risk)
14. Orchestrator (autonomous trading loop)
15. EmergencyController (emergency stop with retry)
16. Signal handlers (SIGINT/SIGTERM graceful, SIGUSR1 emergency)
"""

import asyncio
import signal

from bot.config import AppSettings
from bot.exchange.bybit_client import BybitClient
from bot.logging import get_logger, setup_logging
from bot.market_data.funding_monitor import FundingMonitor
from bot.market_data.opportunity_ranker import OpportunityRanker
from bot.market_data.ticker_service import TickerService
from bot.orchestrator import Orchestrator
from bot.pnl.fee_calculator import FeeCalculator
from bot.pnl.tracker import PnLTracker
from bot.position.delta_validator import DeltaValidator
from bot.position.manager import PositionManager
from bot.position.sizing import PositionSizer
from bot.risk.emergency import EmergencyController
from bot.risk.manager import RiskManager


async def run() -> None:
    """Run the funding rate arbitrage bot with full component wiring."""
    # 1. Load settings
    settings = AppSettings()

    # 2. Setup logging
    setup_logging(settings.log_level)
    logger = get_logger("bot.main")

    # 3. Create exchange client
    exchange_client = BybitClient(settings.exchange)

    # Log warning if no API keys in paper mode (public endpoints still work)
    if settings.trading.mode == "paper":
        api_key = settings.exchange.api_key.get_secret_value()
        if not api_key:
            logger.warning(
                "no_api_keys_configured",
                mode="paper",
                note="Public endpoints (market data) will work. "
                "Private endpoints (balance, orders) will fail.",
            )

    # 4. Create shared ticker service
    ticker_service = TickerService()

    # 5. Create funding monitor
    funding_monitor = FundingMonitor(exchange_client, ticker_service)

    # 6. Create fee calculator
    fee_calculator = FeeCalculator(settings.fees)

    # 7. Create position sizer
    position_sizer = PositionSizer(settings.trading)

    # 8. Create delta validator
    delta_validator = DeltaValidator(settings.trading)

    # 9. Create executor based on mode
    if settings.trading.mode == "paper":
        from bot.execution.paper_executor import PaperExecutor

        executor = PaperExecutor(ticker_service, settings.fees)
    else:
        from bot.execution.live_executor import LiveExecutor

        executor = LiveExecutor(exchange_client)

    # 10. Create position manager
    position_manager = PositionManager(
        executor=executor,
        position_sizer=position_sizer,
        fee_calculator=fee_calculator,
        delta_validator=delta_validator,
        ticker_service=ticker_service,
        settings=settings.trading,
    )

    # 11. Create P&L tracker
    pnl_tracker = PnLTracker(fee_calculator, ticker_service, settings.fees)

    # 12. Create opportunity ranker
    ranker = OpportunityRanker(settings.fees)

    # 13. Create risk manager
    # In paper mode, provide paper margin simulation; in live mode, use exchange client
    risk_manager = RiskManager(
        settings=settings.risk,
        exchange_client=exchange_client if settings.trading.mode == "live" else None,
    )

    # 14. Create orchestrator
    orchestrator = Orchestrator(
        settings=settings,
        exchange_client=exchange_client,
        funding_monitor=funding_monitor,
        ticker_service=ticker_service,
        position_manager=position_manager,
        pnl_tracker=pnl_tracker,
        delta_validator=delta_validator,
        fee_calculator=fee_calculator,
        risk_manager=risk_manager,
        ranker=ranker,
        emergency_controller=None,  # Set after orchestrator created (circular ref)
    )

    # 15. Create emergency controller (needs orchestrator.stop as callback)
    emergency_controller = EmergencyController(
        position_manager=position_manager,
        pnl_tracker=pnl_tracker,
        stop_callback=orchestrator.stop,
    )
    orchestrator.set_emergency_controller(emergency_controller)

    # 16. Handle signals
    loop = asyncio.get_running_loop()

    def _graceful_handler() -> None:
        logger.info("graceful_shutdown_signal")
        asyncio.create_task(orchestrator.stop())

    def _emergency_handler() -> None:
        logger.critical("emergency_stop_signal_received")
        asyncio.create_task(emergency_controller.trigger("user_signal_SIGUSR1"))

    # SIGINT/SIGTERM = graceful (stop bot, close positions cleanly)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _graceful_handler)

    # SIGUSR1 = emergency stop (close all immediately)
    loop.add_signal_handler(signal.SIGUSR1, _emergency_handler)

    # Log startup info
    logger.info(
        "funding_rate_arbitrage_starting",
        mode=settings.trading.mode,
        max_positions=settings.risk.max_simultaneous_positions,
        max_position_size=str(settings.risk.max_position_size_per_pair),
        exit_rate=str(settings.risk.exit_funding_rate),
    )

    # 17. Connect to exchange and start
    try:
        await exchange_client.connect()
        await orchestrator.start()
    finally:
        await exchange_client.close()
        logger.info("funding_rate_arbitrage_stopped")


def main() -> None:
    """Synchronous entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
