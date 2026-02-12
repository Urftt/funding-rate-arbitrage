"""Data models for the backtest engine.

Defines configuration, result, and metric dataclasses for single backtest runs
and parameter sweeps. All monetary values use Decimal exclusively.

CRITICAL: All monetary values use Decimal. Never use float for prices, quantities, or fees.
"""

from dataclasses import dataclass, replace
from decimal import Decimal

from bot.config import SignalSettings


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run.

    Holds all parameters needed: symbol, date range, strategy mode,
    thresholds, and composite signal weights.
    """

    # Required fields
    symbol: str  # e.g., "BTC/USDT:USDT"
    start_ms: int  # start timestamp in milliseconds
    end_ms: int  # end timestamp in milliseconds

    # Strategy selection
    strategy_mode: str = "simple"  # "simple" or "composite"
    initial_capital: Decimal = Decimal("10000")

    # Simple strategy params
    min_funding_rate: Decimal = Decimal("0.0003")
    exit_funding_rate: Decimal = Decimal("0.0001")

    # Composite strategy params
    entry_threshold: Decimal = Decimal("0.5")
    exit_threshold: Decimal = Decimal("0.3")
    weight_rate_level: Decimal = Decimal("0.35")
    weight_trend: Decimal = Decimal("0.25")
    weight_persistence: Decimal = Decimal("0.25")
    weight_basis: Decimal = Decimal("0.15")

    # Signal params
    trend_ema_span: int = 6
    persistence_threshold: Decimal = Decimal("0.0003")
    persistence_max_periods: int = 30

    def with_overrides(self, **kwargs: object) -> "BacktestConfig":
        """Return a new BacktestConfig with specified fields overridden.

        Args:
            **kwargs: Fields to override.

        Returns:
            New BacktestConfig with overridden values.
        """
        return replace(self, **kwargs)

    def to_signal_settings(self) -> SignalSettings:
        """Construct a SignalSettings from the composite params.

        Maps backtest config weights and thresholds to the SignalSettings
        used by SignalEngine.

        Returns:
            SignalSettings configured from this backtest config.
        """
        return SignalSettings(
            trend_ema_span=self.trend_ema_span,
            persistence_threshold=self.persistence_threshold,
            persistence_max_periods=self.persistence_max_periods,
            weight_rate_level=self.weight_rate_level,
            weight_trend=self.weight_trend,
            weight_persistence=self.weight_persistence,
            weight_basis=self.weight_basis,
            entry_threshold=self.entry_threshold,
            exit_threshold=self.exit_threshold,
        )

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output.

        Converts all Decimal values to str for JSON compatibility.

        Returns:
            Dict with all fields, Decimals as strings.
        """
        return {
            "symbol": self.symbol,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "strategy_mode": self.strategy_mode,
            "initial_capital": str(self.initial_capital),
            "min_funding_rate": str(self.min_funding_rate),
            "exit_funding_rate": str(self.exit_funding_rate),
            "entry_threshold": str(self.entry_threshold),
            "exit_threshold": str(self.exit_threshold),
            "weight_rate_level": str(self.weight_rate_level),
            "weight_trend": str(self.weight_trend),
            "weight_persistence": str(self.weight_persistence),
            "weight_basis": str(self.weight_basis),
            "trend_ema_span": self.trend_ema_span,
            "persistence_threshold": str(self.persistence_threshold),
            "persistence_max_periods": self.persistence_max_periods,
        }


@dataclass
class EquityPoint:
    """A single point on the equity curve during a backtest.

    Attributes:
        timestamp_ms: Timestamp in milliseconds.
        equity: Net equity (initial capital + cumulative P&L) at this point.
    """

    timestamp_ms: int
    equity: Decimal


@dataclass
class BacktestMetrics:
    """Aggregate metrics from a completed backtest run.

    All monetary values use Decimal. Ratios that may not be calculable
    (e.g., Sharpe with insufficient data) are None.
    """

    total_trades: int
    winning_trades: int
    net_pnl: Decimal
    total_fees: Decimal
    total_funding: Decimal
    sharpe_ratio: Decimal | None
    max_drawdown: Decimal | None
    win_rate: Decimal | None
    duration_days: int


@dataclass
class BacktestResult:
    """Complete result of a single backtest run.

    Contains the config used, equity curve, and computed metrics.
    """

    config: BacktestConfig
    equity_curve: list[EquityPoint]
    metrics: BacktestMetrics

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output.

        Returns:
            Dict with config, equity_curve, and metrics sub-dicts.
        """
        return {
            "config": self.config.to_dict(),
            "equity_curve": [
                {"timestamp_ms": ep.timestamp_ms, "equity": str(ep.equity)}
                for ep in self.equity_curve
            ],
            "metrics": {
                "total_trades": self.metrics.total_trades,
                "winning_trades": self.metrics.winning_trades,
                "net_pnl": str(self.metrics.net_pnl),
                "total_fees": str(self.metrics.total_fees),
                "total_funding": str(self.metrics.total_funding),
                "sharpe_ratio": str(self.metrics.sharpe_ratio) if self.metrics.sharpe_ratio is not None else None,
                "max_drawdown": str(self.metrics.max_drawdown) if self.metrics.max_drawdown is not None else None,
                "win_rate": str(self.metrics.win_rate) if self.metrics.win_rate is not None else None,
                "duration_days": self.metrics.duration_days,
            },
        }


@dataclass
class SweepResult:
    """Result of a parameter sweep across multiple backtest configurations.

    Attributes:
        param_grid: The parameter grid that was swept (param_name -> list of values).
        results: List of (param_combination_dict, BacktestResult) pairs.
    """

    param_grid: dict[str, list]
    results: list[tuple[dict, BacktestResult]]

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output.

        Returns:
            Dict with param_grid and results list.
        """
        return {
            "param_grid": {
                k: [str(v) if isinstance(v, Decimal) else v for v in vals]
                for k, vals in self.param_grid.items()
            },
            "results": [
                {
                    "params": {
                        k: str(v) if isinstance(v, Decimal) else v
                        for k, v in params.items()
                    },
                    "result": result.to_dict(),
                }
                for params, result in self.results
            ],
        }
