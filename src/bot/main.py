"""Entry point for the funding rate arbitrage bot.

Wires all components together, optionally embeds the FastAPI dashboard,
and starts the orchestrator.  When the dashboard is enabled (default),
the bot and dashboard share a single asyncio event loop via uvicorn's
programmatic API and FastAPI's lifespan context manager.

Handles SIGINT/SIGTERM for graceful shutdown and SIGUSR1 for emergency stop.

CLI backtest commands (independent of bot startup):
  python -m bot.main --backtest --symbol BTC/USDT:USDT --start 2025-01-01 --end 2025-06-01
  python -m bot.main --backtest --compare --symbol BTC/USDT:USDT --start 2025-01-01 --end 2025-06-01
  python -m bot.main --backtest --sweep --symbol BTC/USDT:USDT --start 2025-01-01 --end 2025-06-01

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

import argparse
import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from itertools import product as itertools_product
from typing import Any

import uvicorn
from fastapi import FastAPI

from bot.config import AppSettings
from bot.data.database import HistoricalDatabase
from bot.data.fetcher import HistoricalDataFetcher
from bot.data.store import HistoricalDataStore
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
from bot.analytics.pair_analyzer import PairAnalyzer
from bot.data.market_cap import MarketCapService
from bot.position.dynamic_sizer import DynamicSizer
from bot.signals.engine import SignalEngine


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

    # 14. Create orchestrator (historical data components wired below)
    # 14.5. Create historical data components (optional v1.1 feature)
    historical_db = None
    data_store = None
    data_fetcher = None
    if settings.historical.enabled:
        historical_db = HistoricalDatabase(settings.historical.db_path)
        data_store = HistoricalDataStore(historical_db)
        data_fetcher = HistoricalDataFetcher(
            exchange=exchange_client,
            store=data_store,
            settings=settings.historical,
        )

    # 14.6. Create signal engine (optional v1.1 composite signals)
    signal_engine = None
    if settings.trading.strategy_mode == "composite":
        signal_engine = SignalEngine(
            signal_settings=settings.signal,
            data_store=data_store,
            ticker_service=ticker_service,
            funding_monitor=funding_monitor,
        )

    # 14.7. Create dynamic sizer (optional v1.1 signal-conviction sizing)
    dynamic_sizer = None
    if settings.sizing.enabled and settings.trading.strategy_mode == "composite":
        dynamic_sizer = DynamicSizer(
            position_sizer=position_sizer,
            settings=settings.sizing,
            max_position_size_usd=settings.trading.max_position_size_usd,
        )

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
        data_fetcher=data_fetcher,
        data_store=data_store,
        historical_settings=settings.historical if settings.historical.enabled else None,
        signal_engine=signal_engine,
        signal_settings=settings.signal if signal_engine else None,
        dynamic_sizer=dynamic_sizer,
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
        "historical_db": historical_db,
        "data_store": data_store,
        "data_fetcher": data_fetcher,
        "signal_engine": signal_engine,
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

    # Store data_store on app.state for dashboard access (may be None)
    app.state.data_store = components.get("data_store")

    # Wire pair analyzer for pair explorer (Phase 8)
    if components.get("data_store") is not None:
        app.state.pair_analyzer = PairAnalyzer(
            data_store=components["data_store"],
            fee_settings=settings.fees,
        )

    # Wire market cap service for tier classification (Phase 10)
    import os
    app.state.market_cap_service = MarketCapService(
        api_key=os.environ.get("COINGECKO_API_KEY"),
    )

    # Set up SIGUSR1 for emergency stop only.
    # SIGINT/SIGTERM are handled by uvicorn -> lifespan cleanup stops orchestrator.
    loop = asyncio.get_running_loop()
    logger_sig = get_logger("bot.main")

    def _emergency_handler() -> None:
        logger_sig.critical("emergency_stop_signal_received")
        asyncio.create_task(components["emergency_controller"].trigger("user_signal_SIGUSR1"))

    loop.add_signal_handler(signal.SIGUSR1, _emergency_handler)

    # Connect to exchange
    await components["exchange_client"].connect()

    # Connect historical database if enabled
    if components.get("historical_db"):
        await components["historical_db"].connect()

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

    # Close historical database if connected
    if components.get("historical_db"):
        await components["historical_db"].close()

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
            # Connect historical database if enabled
            if components.get("historical_db"):
                await components["historical_db"].connect()
            await components["orchestrator"].start()
        finally:
            # Close historical database if connected
            if components.get("historical_db"):
                await components["historical_db"].close()
            await components["exchange_client"].close()
            logger.info("funding_rate_arbitrage_stopped")


# ---------------------------------------------------------------------------
# Backtest CLI
# ---------------------------------------------------------------------------


def _build_backtest_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for backtest CLI commands.

    Returns:
        ArgumentParser configured with all backtest options.
    """
    parser = argparse.ArgumentParser(
        prog="python -m bot.main",
        description="Funding rate arbitrage bot -- backtest mode",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run in backtest mode (does not start the live bot)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTC/USDT:USDT",
        help="Perpetual symbol (default: BTC/USDT:USDT)",
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start date as YYYY-MM-DD (required for --backtest)",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date as YYYY-MM-DD (required for --backtest)",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="simple",
        choices=["simple", "composite"],
        help="Strategy mode (default: simple)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run v1.0 (simple) vs v1.1 (composite) comparison",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run parameter sweep instead of single backtest",
    )
    parser.add_argument(
        "--min-rate",
        type=str,
        default=None,
        help="Override min_funding_rate (e.g., 0.0003)",
    )
    parser.add_argument(
        "--entry-threshold",
        type=str,
        default=None,
        help="Override entry_threshold for composite mode (e.g., 0.5)",
    )
    parser.add_argument(
        "--exit-threshold",
        type=str,
        default=None,
        help="Override exit_threshold (e.g., 0.3)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/historical.db",
        help="Path to historical database (default: data/historical.db)",
    )
    parser.add_argument(
        "--initial-capital",
        type=str,
        default="10000",
        help="Initial capital in USDT (default: 10000)",
    )
    return parser


def _format_single_result(
    result: Any,
    symbol: str,
    start_date: str,
    end_date: str,
    strategy: str,
) -> str:
    """Format a single backtest result for console output.

    Args:
        result: The BacktestResult to format.
        symbol: Symbol used in the backtest.
        start_date: Start date string.
        end_date: End date string.
        strategy: Strategy mode used.

    Returns:
        Formatted string for console output.
    """
    m = result.metrics
    lines = [
        "",
        "=== Backtest Results ===",
        f"Symbol:       {symbol}",
        f"Period:       {start_date} to {end_date} ({m.duration_days} days)",
        f"Strategy:     {strategy}",
        f"Net P&L:      ${m.net_pnl:.2f}",
        f"Total Trades: {m.total_trades}",
    ]
    if m.win_rate is not None:
        lines.append(f"Win Rate:     {m.win_rate * 100:.1f}%")
    else:
        lines.append("Win Rate:     N/A")
    if m.sharpe_ratio is not None:
        lines.append(f"Sharpe Ratio: {m.sharpe_ratio:.2f}")
    else:
        lines.append("Sharpe Ratio: N/A")
    if m.max_drawdown is not None:
        lines.append(f"Max Drawdown: ${m.max_drawdown:.2f}")
    else:
        lines.append("Max Drawdown: N/A")
    lines.append(f"Total Fees:   ${m.total_fees:.2f}")
    lines.append(f"Total Funding: ${m.total_funding:.2f}")
    lines.append("")
    return "\n".join(lines)


def _format_decimal(
    value: Decimal | None,
    prefix: str = "$",
    is_pct: bool = False,
) -> str:
    """Format a Decimal value for display.

    Args:
        value: Value to format, or None.
        prefix: Prefix string (e.g., "$").
        is_pct: If True, format as percentage.

    Returns:
        Formatted string.
    """
    if value is None:
        return "N/A"
    if is_pct:
        return f"{value * 100:.1f}%"
    return f"{prefix}{value:.2f}"


def _format_comparison(
    simple_result: Any,
    composite_result: Any,
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Format a side-by-side comparison of simple vs composite strategy results.

    Args:
        simple_result: Result from simple strategy backtest.
        composite_result: Result from composite strategy backtest.
        symbol: Symbol used in the backtest.
        start_date: Start date string.
        end_date: End date string.

    Returns:
        Formatted comparison string for console output.
    """
    sm = simple_result.metrics
    cm = composite_result.metrics

    lines = [
        "",
        "=" * 60,
        "STRATEGY COMPARISON",
        "=" * 60,
        f"Symbol: {symbol}",
        f"Period: {start_date} to {end_date}",
        "",
        f"{'Metric':<20s} {'Simple (v1.0)':>18s} {'Composite (v1.1)':>18s}",
        "-" * 60,
        f"{'Net P&L':<20s} {_format_decimal(sm.net_pnl):>18s} {_format_decimal(cm.net_pnl):>18s}",
        f"{'Total Trades':<20s} {sm.total_trades:>18d} {cm.total_trades:>18d}",
        f"{'Win Rate':<20s} {_format_decimal(sm.win_rate, is_pct=True):>18s} {_format_decimal(cm.win_rate, is_pct=True):>18s}",
        f"{'Sharpe Ratio':<20s} {_format_decimal(sm.sharpe_ratio, prefix=''):>18s} {_format_decimal(cm.sharpe_ratio, prefix=''):>18s}",
        f"{'Max Drawdown':<20s} {_format_decimal(sm.max_drawdown):>18s} {_format_decimal(cm.max_drawdown):>18s}",
        f"{'Total Fees':<20s} {_format_decimal(sm.total_fees):>18s} {_format_decimal(cm.total_fees):>18s}",
        f"{'Total Funding':<20s} {_format_decimal(sm.total_funding):>18s} {_format_decimal(cm.total_funding):>18s}",
        "=" * 60,
        "",
    ]
    return "\n".join(lines)


async def _run_backtest_cli() -> None:
    """Parse CLI arguments and run the appropriate backtest command.

    Handles three modes:
    1. Single backtest: runs one backtest with the given parameters
    2. Comparison: runs simple vs composite side-by-side
    3. Parameter sweep: runs grid search over parameter combinations
    """
    from bot.backtest.models import BacktestConfig
    from bot.backtest.runner import run_backtest, run_comparison
    from bot.backtest.sweep import ParameterSweep, format_sweep_summary

    parser = _build_backtest_parser()
    args = parser.parse_args()

    if not args.backtest:
        return

    # Validate required arguments
    if not args.start or not args.end:
        parser.error("--start and --end are required for --backtest mode")

    # Parse dates to millisecond timestamps
    try:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError as e:
        parser.error(f"Invalid date format. Expected YYYY-MM-DD: {e}")
        return  # unreachable, but satisfies type checker

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    if end_ms <= start_ms:
        parser.error(f"End date ({args.end}) must be after start date ({args.start})")

    initial_capital = Decimal(args.initial_capital)

    # Build config overrides
    config_kwargs: dict[str, Any] = {}
    if args.min_rate is not None:
        config_kwargs["min_funding_rate"] = Decimal(args.min_rate)
    if args.entry_threshold is not None:
        config_kwargs["entry_threshold"] = Decimal(args.entry_threshold)
    if args.exit_threshold is not None:
        config_kwargs["exit_threshold"] = Decimal(args.exit_threshold)

    setup_logging("INFO")

    if args.compare:
        # --- Comparison mode ---
        config_simple = BacktestConfig(
            symbol=args.symbol,
            start_ms=start_ms,
            end_ms=end_ms,
            strategy_mode="simple",
            initial_capital=initial_capital,
            **config_kwargs,
        )
        config_composite = BacktestConfig(
            symbol=args.symbol,
            start_ms=start_ms,
            end_ms=end_ms,
            strategy_mode="composite",
            initial_capital=initial_capital,
            **config_kwargs,
        )
        simple_result, composite_result = await run_comparison(
            config_simple, config_composite, db_path=args.db_path
        )
        print(_format_comparison(
            simple_result, composite_result, args.symbol, args.start, args.end
        ))

    elif args.sweep:
        # --- Sweep mode ---
        base_config = BacktestConfig(
            symbol=args.symbol,
            start_ms=start_ms,
            end_ms=end_ms,
            strategy_mode=args.strategy,
            initial_capital=initial_capital,
            **config_kwargs,
        )
        param_grid = ParameterSweep.generate_default_grid(args.strategy)
        sweep = ParameterSweep(db_path=args.db_path)

        total_combos = len(list(itertools_product(*param_grid.values())))

        def _progress(current: int, total: int, params: dict, result: Any) -> None:
            pct = current * 100 // total
            print(
                f"  [{current}/{total}] ({pct}%) P&L: ${result.metrics.net_pnl:.2f}",
                flush=True,
            )

        print(f"\nRunning parameter sweep ({total_combos} combinations)...")
        sweep_result = await sweep.run(
            base_config, param_grid, progress_callback=_progress
        )
        print(format_sweep_summary(sweep_result))

    else:
        # --- Single backtest mode ---
        config = BacktestConfig(
            symbol=args.symbol,
            start_ms=start_ms,
            end_ms=end_ms,
            strategy_mode=args.strategy,
            initial_capital=initial_capital,
            **config_kwargs,
        )
        result = await run_backtest(config, db_path=args.db_path)
        print(
            _format_single_result(
                result, args.symbol, args.start, args.end, args.strategy
            )
        )


def main() -> None:
    """Synchronous entry point.

    Detects --backtest flag early and dispatches to the backtest CLI
    before any bot component initialization. Normal bot startup is
    completely unaffected when --backtest is not present.
    """
    if "--backtest" in sys.argv:
        try:
            asyncio.run(_run_backtest_cli())
        except KeyboardInterrupt:
            pass
        sys.exit(0)

    # Normal bot startup (unchanged)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
