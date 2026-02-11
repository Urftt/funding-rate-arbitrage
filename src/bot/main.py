"""Entry point for the funding rate arbitrage bot.

Wires all components together, optionally embeds the FastAPI dashboard,
and starts the orchestrator.  When the dashboard is enabled (default),
the bot and dashboard share a single asyncio event loop via uvicorn's
programmatic API and FastAPI's lifespan context manager.

Handles SIGINT/SIGTERM for graceful shutdown and SIGUSR1 for emergency stop.

Component wiring order (in _build_components):
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
"""

import asyncio
import signal
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI

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


async def _build_components(settings: AppSettings) -> dict[str, Any]:
    """Build all bot components from settings.

    Creates the full dependency graph: exchange client, market data services,
    execution layer, position management, P&L tracking, risk management,
    orchestrator, and emergency controller.

    Note: Does NOT call exchange_client.connect() -- that happens in the
    lifespan (dashboard mode) or run() (non-dashboard mode).

    Args:
        settings: Application-wide settings.

    Returns:
        Dict mapping component names to instances.
    """
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

    return {
        "exchange_client": exchange_client,
        "ticker_service": ticker_service,
        "funding_monitor": funding_monitor,
        "fee_calculator": fee_calculator,
        "position_sizer": position_sizer,
        "delta_validator": delta_validator,
        "executor": executor,
        "position_manager": position_manager,
        "pnl_tracker": pnl_tracker,
        "ranker": ranker,
        "risk_manager": risk_manager,
        "orchestrator": orchestrator,
        "emergency_controller": emergency_controller,
    }


def _setup_signal_handlers(
    orchestrator: Orchestrator, emergency_controller: EmergencyController
) -> None:
    """Register OS signal handlers for graceful and emergency shutdown.

    SIGINT/SIGTERM trigger graceful stop (close positions, then exit).
    SIGUSR1 triggers emergency stop (close all immediately).

    Must be called after the asyncio event loop is running.

    Args:
        orchestrator: The orchestrator to stop gracefully.
        emergency_controller: The emergency controller for SIGUSR1.
    """
    logger = get_logger("bot.main")
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage bot component lifecycle within the FastAPI application.

    On startup: stores components on app.state, connects to exchange,
    starts orchestrator as background task, starts dashboard update loop.

    On shutdown: cancels update loop, stops orchestrator, cancels bot task,
    disconnects from exchange.
    """
    from bot.dashboard.update_loop import dashboard_update_loop

    logger = get_logger("bot.main")
    settings = app.state.settings
    components = app.state.components

    # Store all components on app.state for route handler access
    app.state.orchestrator = components["orchestrator"]
    app.state.position_manager = components["position_manager"]
    app.state.pnl_tracker = components["pnl_tracker"]
    app.state.funding_monitor = components["funding_monitor"]
    app.state.risk_manager = components["risk_manager"]
    app.state.ticker_service = components["ticker_service"]
    app.state.exchange_client = components["exchange_client"]
    app.state.emergency_controller = components["emergency_controller"]
    app.state.update_interval = settings.dashboard.update_interval

    # Set up signal handlers now that the event loop is running
    _setup_signal_handlers(
        components["orchestrator"], components["emergency_controller"]
    )

    # Connect to exchange
    await components["exchange_client"].connect()

    # Start orchestrator as background task
    bot_task = asyncio.create_task(components["orchestrator"].start())

    # Start dashboard update loop as background task
    update_task = asyncio.create_task(dashboard_update_loop(app))

    logger.info("lifespan_started", mode=settings.trading.mode)

    yield

    # Shutdown: cancel update loop
    update_task.cancel()
    try:
        await update_task
    except asyncio.CancelledError:
        pass

    # Stop orchestrator gracefully
    await components["orchestrator"].stop()

    # Cancel the bot task
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

    # Disconnect from exchange
    await components["exchange_client"].close()

    logger.info("funding_rate_arbitrage_stopped")


async def run() -> None:
    """Run the funding rate arbitrage bot.

    When dashboard is enabled (DASHBOARD_ENABLED=true, the default):
    - Creates the FastAPI dashboard app with lifespan
    - Runs both bot and dashboard in a single asyncio event loop via uvicorn
    - Lifespan manages all component startup/shutdown

    When dashboard is disabled (DASHBOARD_ENABLED=false):
    - Runs the bot directly without a web server (original behavior)
    - Signal handlers and exchange connection managed in this function
    """
    # 1. Load settings
    settings = AppSettings()

    # 2. Setup logging
    setup_logging(settings.log_level)
    logger = get_logger("bot.main")

    # 3-15. Build all components
    components = await _build_components(settings)

    if settings.dashboard.enabled:
        from bot.dashboard.app import create_dashboard_app

        app = create_dashboard_app(lifespan=lifespan)
        app.state.settings = settings
        app.state.components = components

        logger.info(
            "starting_with_dashboard",
            host=settings.dashboard.host,
            port=settings.dashboard.port,
            mode=settings.trading.mode,
        )

        config = uvicorn.Config(
            app,
            host=settings.dashboard.host,
            port=settings.dashboard.port,
            log_level="warning",  # Suppress uvicorn access logs
        )
        server = uvicorn.Server(config)
        await server.serve()
    else:
        # Dashboard disabled: run bot directly (original behavior)
        _setup_signal_handlers(
            components["orchestrator"], components["emergency_controller"]
        )

        logger.info(
            "starting_without_dashboard",
            mode=settings.trading.mode,
            max_positions=settings.risk.max_simultaneous_positions,
            max_position_size=str(settings.risk.max_position_size_per_pair),
            exit_rate=str(settings.risk.exit_funding_rate),
        )

        try:
            await components["exchange_client"].connect()
            await components["orchestrator"].start()
        finally:
            await components["exchange_client"].close()
            logger.info("funding_rate_arbitrage_stopped")


def main() -> None:
    """Synchronous entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
