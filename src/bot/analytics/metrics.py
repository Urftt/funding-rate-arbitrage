"""Performance analytics calculations (DASH-07).

Pure Decimal analytics: sharpe_ratio, max_drawdown, win_rate, win_rate_by_pair.
All functions accept list[PositionPnL] and use Decimal precision.

Stub module -- implementation pending (TDD RED phase).
"""

from decimal import Decimal

from bot.pnl.tracker import PositionPnL


def sharpe_ratio(
    positions: list[PositionPnL],
    risk_free_rate: Decimal = Decimal("0"),
    annualization_factor: int = 1095,
) -> Decimal | None:
    """Compute annualized Sharpe ratio from closed position returns."""
    raise NotImplementedError


def max_drawdown(positions: list[PositionPnL]) -> Decimal | None:
    """Compute max peak-to-trough drawdown in cumulative P&L."""
    raise NotImplementedError


def win_rate(positions: list[PositionPnL]) -> Decimal | None:
    """Compute overall win rate from closed positions."""
    raise NotImplementedError


def win_rate_by_pair(positions: list[PositionPnL]) -> dict[str, Decimal]:
    """Compute win rate grouped by perp_symbol."""
    raise NotImplementedError
