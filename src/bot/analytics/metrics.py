"""Performance analytics calculations (DASH-07).

Pure Decimal analytics: sharpe_ratio, max_drawdown, win_rate, win_rate_by_pair.
All functions accept list[PositionPnL] and use Decimal precision.
No external dependencies (no pandas, numpy, quantstats).
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from bot.pnl.tracker import PositionPnL


def _net_return(position: PositionPnL) -> Decimal:
    """Compute net return for a closed position: funding - fees.

    Args:
        position: A closed PositionPnL with funding payments and fees.

    Returns:
        Net return as Decimal (positive = profit, negative = loss).
    """
    total_funding = sum(
        (fp.amount for fp in position.funding_payments),
        Decimal("0"),
    )
    return total_funding - position.entry_fee - position.exit_fee


def sharpe_ratio(
    positions: list[PositionPnL],
    risk_free_rate: Decimal = Decimal("0"),
    annualization_factor: int = 1095,
) -> Decimal | None:
    """Compute annualized Sharpe ratio from closed position returns.

    Sharpe = ((mean_return - risk_free) / sample_std_dev) * sqrt(annualization)

    Args:
        positions: List of closed PositionPnL records.
        risk_free_rate: Risk-free rate per period (default 0).
        annualization_factor: Periods per year. Default 1095 = 3 funding/day * 365.

    Returns:
        Sharpe ratio as Decimal, or None if < 2 positions or zero std dev.
    """
    if len(positions) < 2:
        return None

    returns = [_net_return(p) for p in positions]
    n = Decimal(len(returns))

    mean = sum(returns, Decimal("0")) / n

    # Sample standard deviation (N-1 denominator)
    variance = sum((r - mean) ** 2 for r in returns) / (n - Decimal("1"))
    std_dev = variance.sqrt()

    if std_dev == Decimal("0"):
        return None

    annualization_sqrt = Decimal(annualization_factor).sqrt()
    return ((mean - risk_free_rate) / std_dev) * annualization_sqrt


def max_drawdown(positions: list[PositionPnL]) -> Decimal | None:
    """Compute max peak-to-trough drawdown in cumulative P&L.

    Sorts positions by closed_at timestamp, computes running cumulative
    P&L, and finds the largest peak-to-trough decline.

    Args:
        positions: List of closed PositionPnL records.

    Returns:
        Max drawdown as positive Decimal, or None if no positions.
    """
    if not positions:
        return None

    # Sort by closed_at timestamp
    sorted_positions = sorted(positions, key=lambda p: p.closed_at or 0.0)

    cumulative = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")

    for pos in sorted_positions:
        cumulative += _net_return(pos)
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return max_dd


def win_rate(positions: list[PositionPnL]) -> Decimal | None:
    """Compute overall win rate from closed positions.

    A win is a position where net return > 0 (funding - fees > 0).

    Args:
        positions: List of closed PositionPnL records.

    Returns:
        Win rate as Decimal rounded to 3 places, or None if no positions.
    """
    if not positions:
        return None

    wins = sum(1 for p in positions if _net_return(p) > Decimal("0"))
    rate = Decimal(wins) / Decimal(len(positions))
    return rate.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def win_rate_by_pair(positions: list[PositionPnL]) -> dict[str, Decimal]:
    """Compute win rate grouped by perp_symbol.

    Args:
        positions: List of closed PositionPnL records.

    Returns:
        Dict mapping perp_symbol to win rate (Decimal, 3 decimal places).
        Empty dict if no positions.
    """
    if not positions:
        return {}

    grouped: dict[str, list[PositionPnL]] = defaultdict(list)
    for pos in positions:
        grouped[pos.perp_symbol].append(pos)

    result: dict[str, Decimal] = {}
    for symbol, group in grouped.items():
        rate = win_rate(group)
        if rate is not None:
            result[symbol] = rate

    return result
