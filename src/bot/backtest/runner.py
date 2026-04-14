"""High-level entry points for running backtests.

Provides run_backtest() for single backtest execution, run_comparison() for
v1.0 vs v1.1 side-by-side comparison (BKTS-05), and run_backtest_cli() for
convenient CLI usage with date strings.

All functions handle empty data gracefully by returning BacktestResult with
zero metrics and a warning log message.

The historical data now lives in Postgres (shared ``crypto`` DB). Callers
may pass a pre-opened :class:`HistoricalDatabase` to reuse a single pool; if
none is provided, one is constructed from POSTGRES_* env vars.
"""

import time
from datetime import datetime, timezone
from decimal import Decimal

from bot.backtest.engine import BacktestEngine
from bot.backtest.models import BacktestConfig, BacktestResult, MultiPairResult
from bot.config import BacktestSettings, FeeSettings
from bot.data.database import HistoricalDatabase
from bot.data.store import HistoricalDataStore
from bot.logging import get_logger

logger = get_logger(__name__)


async def run_backtest(
    config: BacktestConfig,
    database: HistoricalDatabase | None = None,
    fee_settings: FeeSettings | None = None,
    backtest_settings: BacktestSettings | None = None,
) -> BacktestResult:
    """Run a single backtest with the given configuration.

    If ``database`` is provided, reuses its asyncpg pool. Otherwise opens a
    short-lived :class:`HistoricalDatabase` for the duration of the run.
    """
    if fee_settings is None:
        fee_settings = FeeSettings()
    if backtest_settings is None:
        backtest_settings = BacktestSettings()

    start_time = time.monotonic()

    logger.info(
        "run_backtest_starting",
        symbol=config.symbol,
        strategy_mode=config.strategy_mode,
        start_ms=config.start_ms,
        end_ms=config.end_ms,
    )

    async def _run(db: HistoricalDatabase) -> BacktestResult:
        data_store = HistoricalDataStore(db)
        engine = BacktestEngine(
            config=config,
            data_store=data_store,
            fee_settings=fee_settings,
            backtest_settings=backtest_settings,
        )
        return await engine.run()

    if database is not None:
        result = await _run(database)
    else:
        async with HistoricalDatabase() as db:
            result = await _run(db)

    elapsed = time.monotonic() - start_time

    logger.info(
        "run_backtest_complete",
        symbol=config.symbol,
        strategy_mode=config.strategy_mode,
        total_trades=result.metrics.total_trades,
        net_pnl=str(result.metrics.net_pnl),
        equity_points=len(result.equity_curve),
        elapsed_seconds=round(elapsed, 2),
    )

    return result


async def run_comparison(
    config_simple: BacktestConfig,
    config_composite: BacktestConfig,
    database: HistoricalDatabase | None = None,
    fee_settings: FeeSettings | None = None,
    backtest_settings: BacktestSettings | None = None,
) -> tuple[BacktestResult, BacktestResult]:
    """Run simple vs composite backtests side by side, sharing a DB pool."""
    if fee_settings is None:
        fee_settings = FeeSettings()
    if backtest_settings is None:
        backtest_settings = BacktestSettings()

    if config_simple.strategy_mode != "simple":
        logger.warning(
            "comparison_config_mismatch",
            expected="simple",
            got=config_simple.strategy_mode,
        )
    if config_composite.strategy_mode != "composite":
        logger.warning(
            "comparison_config_mismatch",
            expected="composite",
            got=config_composite.strategy_mode,
        )
    if config_simple.symbol != config_composite.symbol:
        logger.warning(
            "comparison_symbol_mismatch",
            simple_symbol=config_simple.symbol,
            composite_symbol=config_composite.symbol,
        )
    if (
        config_simple.start_ms != config_composite.start_ms
        or config_simple.end_ms != config_composite.end_ms
    ):
        logger.warning(
            "comparison_date_range_mismatch",
            simple_range=f"{config_simple.start_ms}-{config_simple.end_ms}",
            composite_range=f"{config_composite.start_ms}-{config_composite.end_ms}",
        )

    logger.info(
        "run_comparison_starting",
        symbol=config_simple.symbol,
        start_ms=config_simple.start_ms,
        end_ms=config_simple.end_ms,
    )

    start_time = time.monotonic()

    async def _run_both(db: HistoricalDatabase) -> tuple[BacktestResult, BacktestResult]:
        data_store = HistoricalDataStore(db)
        simple_engine = BacktestEngine(
            config=config_simple,
            data_store=data_store,
            fee_settings=fee_settings,
            backtest_settings=backtest_settings,
        )
        simple_result = await simple_engine.run()

        composite_engine = BacktestEngine(
            config=config_composite,
            data_store=data_store,
            fee_settings=fee_settings,
            backtest_settings=backtest_settings,
        )
        composite_result = await composite_engine.run()
        return simple_result, composite_result

    if database is not None:
        simple_result, composite_result = await _run_both(database)
    else:
        async with HistoricalDatabase() as db:
            simple_result, composite_result = await _run_both(db)

    elapsed = time.monotonic() - start_time

    logger.info(
        "run_comparison_complete",
        simple_trades=simple_result.metrics.total_trades,
        simple_pnl=str(simple_result.metrics.net_pnl),
        composite_trades=composite_result.metrics.total_trades,
        composite_pnl=str(composite_result.metrics.net_pnl),
        elapsed_seconds=round(elapsed, 2),
    )

    return simple_result, composite_result


async def run_multi_pair(
    symbols: list[str],
    base_config: BacktestConfig,
    database: HistoricalDatabase | None = None,
    fee_settings: FeeSettings | None = None,
    backtest_settings: BacktestSettings | None = None,
) -> MultiPairResult:
    """Run the same backtest config across multiple pairs sequentially."""
    if fee_settings is None:
        fee_settings = FeeSettings()
    if backtest_settings is None:
        backtest_settings = BacktestSettings()

    logger.info("run_multi_pair_starting", symbols=symbols, total=len(symbols))
    start_time = time.monotonic()
    results = []

    async def _run_all(db: HistoricalDatabase) -> None:
        for symbol in symbols:
            try:
                config = base_config.with_overrides(symbol=symbol)
                result = await run_backtest(config, db, fee_settings, backtest_settings)
                compact = BacktestResult(
                    config=result.config,
                    equity_curve=[],
                    trades=[],
                    trade_stats=result.trade_stats,
                    metrics=result.metrics,
                )
                results.append((symbol, compact, None))
            except Exception as e:
                logger.warning("multi_pair_single_error", symbol=symbol, error=str(e))
                results.append((symbol, None, str(e)))

    if database is not None:
        await _run_all(database)
    else:
        async with HistoricalDatabase() as db:
            await _run_all(db)

    elapsed = time.monotonic() - start_time
    logger.info("run_multi_pair_complete", total=len(symbols), elapsed_seconds=round(elapsed, 2))
    return MultiPairResult(symbols=symbols, base_config=base_config, results=results)


async def run_backtest_cli(
    symbol: str,
    start_date: str,
    end_date: str,
    strategy_mode: str = "simple",
    initial_capital: Decimal = Decimal("10000"),
    **kwargs: object,
) -> BacktestResult:
    """Convenience entry point for CLI usage with date strings."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError as e:
        raise ValueError(
            f"Invalid date format. Expected YYYY-MM-DD. Error: {e}"
        ) from e

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    if end_ms <= start_ms:
        raise ValueError(
            f"End date ({end_date}) must be after start date ({start_date})"
        )

    if "/" not in symbol or ":" not in symbol:
        logger.warning(
            "unusual_symbol_format",
            symbol=symbol,
            note="Expected format like BTC/USDT:USDT",
        )

    config_kwargs = {
        "symbol": symbol,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "strategy_mode": strategy_mode,
        "initial_capital": initial_capital,
    }
    for key, value in kwargs.items():
        if hasattr(BacktestConfig, key):
            config_kwargs[key] = value

    config = BacktestConfig(**config_kwargs)

    result = await run_backtest(config)

    m = result.metrics
    logger.info(
        "backtest_cli_summary",
        symbol=symbol,
        strategy_mode=strategy_mode,
        date_range=f"{start_date} to {end_date}",
        initial_capital=str(initial_capital),
        net_pnl=str(m.net_pnl),
        total_trades=m.total_trades,
        winning_trades=m.winning_trades,
        win_rate=str(m.win_rate) if m.win_rate is not None else "N/A",
        sharpe_ratio=str(m.sharpe_ratio) if m.sharpe_ratio is not None else "N/A",
        max_drawdown=str(m.max_drawdown) if m.max_drawdown is not None else "N/A",
        total_fees=str(m.total_fees),
        total_funding=str(m.total_funding),
        duration_days=m.duration_days,
    )

    return result
