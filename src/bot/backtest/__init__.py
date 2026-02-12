"""Backtest engine package.

Provides components for running historical backtests of funding rate
arbitrage strategies using production-equivalent logic (Executor ABC swap).
Includes parameter sweep for grid search optimization (BKTS-03).
"""

from bot.backtest.data_wrapper import BacktestDataStoreWrapper
from bot.backtest.engine import BacktestEngine
from bot.backtest.executor import BacktestExecutor
from bot.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    EquityPoint,
    SweepResult,
)
from bot.backtest.runner import run_backtest, run_backtest_cli, run_comparison
from bot.backtest.sweep import ParameterSweep, format_sweep_summary

__all__ = [
    "BacktestConfig",
    "BacktestDataStoreWrapper",
    "BacktestEngine",
    "BacktestExecutor",
    "BacktestMetrics",
    "BacktestResult",
    "EquityPoint",
    "ParameterSweep",
    "SweepResult",
    "format_sweep_summary",
    "run_backtest",
    "run_backtest_cli",
    "run_comparison",
]
