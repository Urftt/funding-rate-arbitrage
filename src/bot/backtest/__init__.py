"""Backtest engine package.

Provides components for running historical backtests of funding rate
arbitrage strategies using production-equivalent logic (Executor ABC swap).
"""

from bot.backtest.data_wrapper import BacktestDataStoreWrapper
from bot.backtest.executor import BacktestExecutor
from bot.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    EquityPoint,
    SweepResult,
)

__all__ = [
    "BacktestConfig",
    "BacktestDataStoreWrapper",
    "BacktestExecutor",
    "BacktestMetrics",
    "BacktestResult",
    "EquityPoint",
    "SweepResult",
]
