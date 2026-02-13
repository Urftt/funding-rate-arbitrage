"""Data models for the backtest engine.

Defines configuration, result, and metric dataclasses for single backtest runs
and parameter sweeps. Includes per-trade detail (BacktestTrade), aggregate
trade statistics (TradeStats), and P&L histogram binning (compute_pnl_histogram).

All monetary values use Decimal exclusively.

CRITICAL: All monetary values use Decimal. Never use float for prices, quantities, or fees.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from bot.config import SignalSettings

if TYPE_CHECKING:
    from bot.pnl.tracker import PositionPnL


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
    min_funding_rate: Decimal = Decimal("0.0001")
    exit_funding_rate: Decimal = Decimal("0.00005")

    # Composite strategy params
    entry_threshold: Decimal = Decimal("0.35")
    exit_threshold: Decimal = Decimal("0.2")
    weight_rate_level: Decimal = Decimal("0.35")
    weight_trend: Decimal = Decimal("0.25")
    weight_persistence: Decimal = Decimal("0.25")
    weight_basis: Decimal = Decimal("0.15")

    # Signal params
    trend_ema_span: int = 6
    persistence_threshold: Decimal = Decimal("0.0003")
    persistence_max_periods: int = 30

    # Dynamic sizing params (Phase 7)
    sizing_enabled: bool = False
    sizing_min_allocation_fraction: Decimal = Decimal("0.3")
    sizing_max_allocation_fraction: Decimal = Decimal("1.0")
    sizing_max_portfolio_exposure: Decimal = Decimal("5000")

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

    def to_sizing_settings(self) -> "DynamicSizingSettings":
        """Construct a DynamicSizingSettings from the sizing params.

        Maps backtest config sizing fields to the DynamicSizingSettings
        used by DynamicSizer.

        Returns:
            DynamicSizingSettings configured from this backtest config.
        """
        from bot.config import DynamicSizingSettings

        return DynamicSizingSettings(
            enabled=self.sizing_enabled,
            min_allocation_fraction=self.sizing_min_allocation_fraction,
            max_allocation_fraction=self.sizing_max_allocation_fraction,
            max_portfolio_exposure=self.sizing_max_portfolio_exposure,
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
            "sizing_enabled": self.sizing_enabled,
            "sizing_min_allocation_fraction": str(self.sizing_min_allocation_fraction),
            "sizing_max_allocation_fraction": str(self.sizing_max_allocation_fraction),
            "sizing_max_portfolio_exposure": str(self.sizing_max_portfolio_exposure),
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
class BacktestTrade:
    """Per-trade detail extracted from a closed PositionPnL.

    Contains entry/exit times and prices, funding collected, fees paid,
    net P&L, holding period, and win/loss flag. All monetary values are
    Decimal.

    Attributes:
        trade_number: Sequential trade number (1-based).
        symbol: Perp symbol (e.g., "BTC/USDT:USDT").
        entry_time_ms: Entry timestamp in milliseconds.
        exit_time_ms: Exit timestamp in milliseconds.
        entry_price: Perp entry price.
        exit_price: Perp exit price.
        quantity: Position quantity.
        funding_collected: Sum of all funding payments.
        entry_fee: Entry fee for both legs.
        exit_fee: Exit fee for both legs.
        total_fees: entry_fee + exit_fee.
        net_pnl: funding_collected - total_fees.
        holding_periods: Number of funding payment periods held.
        is_win: True if net_pnl > 0.
    """

    trade_number: int
    symbol: str
    entry_time_ms: int
    exit_time_ms: int
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    funding_collected: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    total_fees: Decimal
    net_pnl: Decimal
    holding_periods: int
    is_win: bool

    @staticmethod
    def from_position_pnl(pnl: PositionPnL, trade_number: int) -> BacktestTrade:
        """Extract a BacktestTrade from a closed PositionPnL.

        Args:
            pnl: A closed PositionPnL with funding payments and fees.
            trade_number: Sequential trade number (1-based).

        Returns:
            BacktestTrade with all fields computed from the PositionPnL.
        """
        funding = sum(
            (fp.amount for fp in pnl.funding_payments), Decimal("0")
        )
        total_fees = pnl.entry_fee + pnl.exit_fee
        net = funding - total_fees
        return BacktestTrade(
            trade_number=trade_number,
            symbol=pnl.perp_symbol,
            entry_time_ms=int(pnl.opened_at * 1000),
            exit_time_ms=int((pnl.closed_at or 0) * 1000),
            entry_price=pnl.perp_entry_price,
            exit_price=pnl.perp_exit_price,
            quantity=pnl.quantity,
            funding_collected=funding,
            entry_fee=pnl.entry_fee,
            exit_fee=pnl.exit_fee,
            total_fees=total_fees,
            net_pnl=net,
            holding_periods=len(pnl.funding_payments),
            is_win=net > Decimal("0"),
        )

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output.

        Returns:
            Dict with all fields; Decimal values as strings.
        """
        return {
            "trade_number": self.trade_number,
            "symbol": self.symbol,
            "entry_time_ms": self.entry_time_ms,
            "exit_time_ms": self.exit_time_ms,
            "entry_price": str(self.entry_price),
            "exit_price": str(self.exit_price),
            "quantity": str(self.quantity),
            "funding_collected": str(self.funding_collected),
            "entry_fee": str(self.entry_fee),
            "exit_fee": str(self.exit_fee),
            "total_fees": str(self.total_fees),
            "net_pnl": str(self.net_pnl),
            "holding_periods": self.holding_periods,
            "is_win": self.is_win,
        }


@dataclass
class TradeStats:
    """Aggregate statistics computed from a list of BacktestTrade.

    All optional fields are None when trades list is empty or when the
    specific statistic cannot be computed (e.g., avg_loss with no losses).

    Attributes:
        total_trades: Total number of round-trip trades.
        winning_trades: Number of trades with net_pnl > 0.
        losing_trades: Number of trades with net_pnl <= 0.
        win_rate: Fraction of winning trades (quantized to 0.001).
        avg_win: Mean P&L of winning trades.
        avg_loss: Mean absolute P&L of losing trades (positive number).
        best_trade: Highest net_pnl.
        worst_trade: Lowest net_pnl.
        avg_holding_periods: Mean holding periods across all trades.
    """

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal | None
    avg_win: Decimal | None
    avg_loss: Decimal | None
    best_trade: Decimal | None
    worst_trade: Decimal | None
    avg_holding_periods: Decimal | None

    @staticmethod
    def from_trades(trades: list[BacktestTrade]) -> TradeStats:
        """Compute aggregate statistics from a list of trades.

        Args:
            trades: List of BacktestTrade objects.

        Returns:
            TradeStats with computed values, or all-None for empty list.
        """
        if not trades:
            return TradeStats(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=None,
                avg_win=None,
                avg_loss=None,
                best_trade=None,
                worst_trade=None,
                avg_holding_periods=None,
            )

        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        n = Decimal(len(trades))

        wr = (Decimal(len(wins)) / n).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )

        avg_win = (
            sum((t.net_pnl for t in wins), Decimal("0")) / Decimal(len(wins))
            if wins
            else None
        )
        avg_loss = (
            abs(
                sum((t.net_pnl for t in losses), Decimal("0"))
                / Decimal(len(losses))
            )
            if losses
            else None
        )

        pnls = [t.net_pnl for t in trades]
        avg_hp = sum(
            (Decimal(t.holding_periods) for t in trades), Decimal("0")
        ) / n

        return TradeStats(
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=wr,
            avg_win=avg_win,
            avg_loss=avg_loss,
            best_trade=max(pnls),
            worst_trade=min(pnls),
            avg_holding_periods=avg_hp,
        )

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output.

        Returns:
            Dict with all fields; Decimal values as strings, None preserved.
        """
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": str(self.win_rate) if self.win_rate is not None else None,
            "avg_win": str(self.avg_win) if self.avg_win is not None else None,
            "avg_loss": str(self.avg_loss) if self.avg_loss is not None else None,
            "best_trade": str(self.best_trade) if self.best_trade is not None else None,
            "worst_trade": str(self.worst_trade) if self.worst_trade is not None else None,
            "avg_holding_periods": str(self.avg_holding_periods) if self.avg_holding_periods is not None else None,
        }


def compute_pnl_histogram(
    trades: list[BacktestTrade], bin_count: int = 10
) -> dict:
    """Compute histogram bins for trade P&L distribution.

    Server-side binning using Decimal arithmetic. Dynamic bin count
    adapts to trade count: min(10, max(3, len(trades) // 3)).

    Args:
        trades: List of BacktestTrade objects.
        bin_count: Maximum number of bins (default 10). Actual count
            may be lower for few trades.

    Returns:
        Dict with "bins" (list of label strings) and "counts" (list of ints).
        Empty dict values for empty trades list.
    """
    if not trades:
        return {"bins": [], "counts": []}

    pnls = [t.net_pnl for t in trades]
    min_pnl = min(pnls)
    max_pnl = max(pnls)

    # All same value -> single bin
    if min_pnl == max_pnl:
        return {"bins": [str(min_pnl)], "counts": [len(pnls)]}

    # Dynamic bin count
    actual_bins = min(bin_count, max(3, len(trades) // 3))

    bin_width = (max_pnl - min_pnl) / Decimal(str(actual_bins))
    bins: list[str] = []
    counts: list[int] = []

    for i in range(actual_bins):
        lower = min_pnl + bin_width * Decimal(str(i))
        upper = lower + bin_width
        label = f"${float(lower):.2f}"
        # Last bin includes the max value (closed interval on right)
        count = sum(
            1
            for p in pnls
            if (lower <= p < upper) or (i == actual_bins - 1 and p == max_pnl)
        )
        bins.append(label)
        counts.append(count)

    return {"bins": bins, "counts": counts}


@dataclass
class BacktestResult:
    """Complete result of a single backtest run.

    Contains the config used, equity curve, computed metrics, per-trade
    detail, and aggregate trade statistics.
    """

    config: BacktestConfig
    equity_curve: list[EquityPoint]
    metrics: BacktestMetrics
    trades: list[BacktestTrade] = field(default_factory=list)
    trade_stats: TradeStats | None = None

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output.

        Returns:
            Dict with config, equity_curve, metrics, trades, trade_stats,
            and pnl_histogram sub-dicts.
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
            "trades": [t.to_dict() for t in self.trades],
            "trade_stats": self.trade_stats.to_dict() if self.trade_stats else None,
            "pnl_histogram": compute_pnl_histogram(self.trades),
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


@dataclass
class MultiPairResult:
    """Results from running the same config across multiple pairs."""

    symbols: list[str]
    base_config: BacktestConfig
    results: list[tuple[str, BacktestResult | None, str | None]]
    # Each tuple: (symbol, result_or_None, error_or_None)

    @property
    def profitable_count(self) -> int:
        """Count of pairs with positive net P&L."""
        return sum(1 for _, r, e in self.results if r and r.metrics.net_pnl > Decimal("0"))

    @property
    def total_count(self) -> int:
        """Total number of pairs tested."""
        return len(self.results)

    @property
    def successful_count(self) -> int:
        """Count of pairs that completed without error."""
        return sum(1 for _, r, _ in self.results if r is not None)

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output.

        Returns:
            Dict with symbols, config, results array, and aggregate counts.
        """
        items = []
        for symbol, result, error in self.results:
            if error:
                items.append({"symbol": symbol, "error": error, "metrics": None})
            elif result:
                items.append({"symbol": symbol, "error": None, "metrics": result.to_dict()["metrics"]})
            else:
                items.append({"symbol": symbol, "error": "Unknown error", "metrics": None})
        return {
            "symbols": self.symbols,
            "config": self.base_config.to_dict(),
            "results": items,
            "profitable_count": self.profitable_count,
            "total_count": self.total_count,
            "successful_count": self.successful_count,
        }
