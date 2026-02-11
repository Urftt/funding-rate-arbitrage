"""Entry point for the funding rate arbitrage bot.

Wires all components together and starts the orchestrator.
Handles SIGINT/SIGTERM for graceful shutdown.

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
12. Orchestrator (main bot loop)
"""

import asyncio
import signal

from bot.config import AppSettings
from bot.exchange.bybit_client import BybitClient
from bot.logging import get_logger, setup_logging
from bot.market_data.funding_monitor import FundingMonitor
from bot.market_data.ticker_service import TickerService
from bot.orchestrator import Orchestrator
from bot.pnl.fee_calculator import FeeCalculator
from bot.pnl.tracker import PnLTracker
from bot.position.delta_validator import DeltaValidator
from bot.position.manager import PositionManager
from bot.position.sizing import PositionSizer


async def run() -> None:
    """Run the funding rate arbitrage bot with full component wiring."""
    # 1. Load settings
    settings = AppSettings()

    # 2. Setup logging
    setup_logging(settings.log_level)
    logger = get_logger("bot.main")
    logger.info(
        "funding_rate_arbitrage_starting",
        mode=settings.trading.mode,
    )

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

    # 12. Create orchestrator
    orchestrator = Orchestrator(
        settings=settings,
        exchange_client=exchange_client,
        funding_monitor=funding_monitor,
        ticker_service=ticker_service,
        position_manager=position_manager,
        pnl_tracker=pnl_tracker,
        delta_validator=delta_validator,
        fee_calculator=fee_calculator,
    )

    # 13. Handle SIGINT/SIGTERM for graceful shutdown
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("shutdown_signal_received")
        asyncio.create_task(orchestrator.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # 14. Connect to exchange and start
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
