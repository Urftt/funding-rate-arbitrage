"""Backtest engine package.

Provides components for running historical backtests of funding rate
arbitrage strategies using production-equivalent logic (Executor ABC swap).
"""

from bot.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    EquityPoint,
    SweepResult,
)

__all__ = [
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestResult",
    "EquityPoint",
    "SweepResult",
]
