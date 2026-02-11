"""TDD tests for performance analytics (DASH-07).

Tests cover normal operation, edge cases, and insufficient-data guards
for: sharpe_ratio, max_drawdown, win_rate, win_rate_by_pair.
"""

from decimal import Decimal, ROUND_HALF_UP

import pytest

from bot.pnl.tracker import FundingPayment, PositionPnL
from bot.analytics.metrics import (
    max_drawdown,
    sharpe_ratio,
    win_rate,
    win_rate_by_pair,
)


# ---------------------------------------------------------------------------
# Helpers to build test positions
# ---------------------------------------------------------------------------


def _make_position(
    position_id: str,
    funding_amounts: list[Decimal],
    entry_fee: Decimal = Decimal("0"),
    exit_fee: Decimal = Decimal("0"),
    closed_at: float | None = 1.0,
    perp_symbol: str = "BTC/USDT:USDT",
) -> PositionPnL:
    """Build a PositionPnL with specified funding payments and fees."""
    payments = [
        FundingPayment(
            amount=amt,
            rate=Decimal("0.0001"),
            mark_price=Decimal("50000"),
            timestamp=float(i),
        )
        for i, amt in enumerate(funding_amounts)
    ]
    return PositionPnL(
        position_id=position_id,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        funding_payments=payments,
        spot_entry_price=Decimal("50000"),
        perp_entry_price=Decimal("50000"),
        quantity=Decimal("1"),
        opened_at=0.0,
        closed_at=closed_at,
        perp_symbol=perp_symbol,
    )


def _position_with_net_return(
    net_return: Decimal,
    position_id: str = "pos",
    closed_at: float = 1.0,
    perp_symbol: str = "BTC/USDT:USDT",
) -> PositionPnL:
    """Build a position whose net return (funding - fees) equals net_return.

    Sets funding_payments to [net_return] and fees to 0 for simplicity.
    """
    return _make_position(
        position_id=position_id,
        funding_amounts=[net_return],
        entry_fee=Decimal("0"),
        exit_fee=Decimal("0"),
        closed_at=closed_at,
        perp_symbol=perp_symbol,
    )


# ===========================================================================
# sharpe_ratio tests
# ===========================================================================


class TestSharpeRatio:
    """Tests for sharpe_ratio(positions, risk_free_rate, annualization_factor)."""

    def test_known_values(self) -> None:
        """3 positions with returns [10, 5, 15] -> verifiable Sharpe."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", closed_at=1.0),
            _position_with_net_return(Decimal("5"), "p2", closed_at=2.0),
            _position_with_net_return(Decimal("15"), "p3", closed_at=3.0),
        ]
        result = sharpe_ratio(positions, risk_free_rate=Decimal("0"), annualization_factor=1)
        assert result is not None

        # Mean = 10, std = 5 (sample), sharpe = (10-0)/5 * sqrt(1) = 2.0
        assert result == Decimal("2")

    def test_annualization(self) -> None:
        """Annualization factor scales the result by sqrt(factor)."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", closed_at=1.0),
            _position_with_net_return(Decimal("5"), "p2", closed_at=2.0),
            _position_with_net_return(Decimal("15"), "p3", closed_at=3.0),
        ]
        result = sharpe_ratio(positions, risk_free_rate=Decimal("0"), annualization_factor=4)
        assert result is not None
        # (10/5) * sqrt(4) = 2 * 2 = 4
        assert result == Decimal("4")

    def test_with_risk_free_rate(self) -> None:
        """Risk-free rate is subtracted from mean."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", closed_at=1.0),
            _position_with_net_return(Decimal("5"), "p2", closed_at=2.0),
            _position_with_net_return(Decimal("15"), "p3", closed_at=3.0),
        ]
        result = sharpe_ratio(positions, risk_free_rate=Decimal("5"), annualization_factor=1)
        assert result is not None
        # (10 - 5) / 5 * 1 = 1.0
        assert result == Decimal("1")

    def test_empty_list_returns_none(self) -> None:
        """No positions -> None."""
        assert sharpe_ratio([]) is None

    def test_single_position_returns_none(self) -> None:
        """Fewer than 2 positions -> None (can't compute sample std dev)."""
        positions = [_position_with_net_return(Decimal("10"), "p1")]
        assert sharpe_ratio(positions) is None

    def test_identical_returns_returns_none(self) -> None:
        """All same returns -> std dev = 0 -> None."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", closed_at=1.0),
            _position_with_net_return(Decimal("10"), "p2", closed_at=2.0),
            _position_with_net_return(Decimal("10"), "p3", closed_at=3.0),
        ]
        assert sharpe_ratio(positions) is None

    def test_with_fees(self) -> None:
        """Net return accounts for entry and exit fees."""
        # funding=20, entry_fee=3, exit_fee=2 -> net=15
        # funding=15, entry_fee=3, exit_fee=2 -> net=10
        # funding=25, entry_fee=3, exit_fee=2 -> net=20
        positions = [
            _make_position("p1", [Decimal("20")], Decimal("3"), Decimal("2"), closed_at=1.0),
            _make_position("p2", [Decimal("15")], Decimal("3"), Decimal("2"), closed_at=2.0),
            _make_position("p3", [Decimal("25")], Decimal("3"), Decimal("2"), closed_at=3.0),
        ]
        result = sharpe_ratio(positions, risk_free_rate=Decimal("0"), annualization_factor=1)
        assert result is not None
        # Returns: [15, 10, 20], mean=15, std=5, sharpe=3.0
        assert result == Decimal("3")


# ===========================================================================
# max_drawdown tests
# ===========================================================================


class TestMaxDrawdown:
    """Tests for max_drawdown(positions)."""

    def test_basic_drawdown(self) -> None:
        """Sequence: +10, -5, +3 -> cumulative [10, 5, 8] -> drawdown = 5."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", closed_at=1.0),
            _position_with_net_return(Decimal("-5"), "p2", closed_at=2.0),
            _position_with_net_return(Decimal("3"), "p3", closed_at=3.0),
        ]
        result = max_drawdown(positions)
        assert result == Decimal("5")

    def test_all_profitable(self) -> None:
        """All positive returns -> no drawdown -> Decimal('0')."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", closed_at=1.0),
            _position_with_net_return(Decimal("5"), "p2", closed_at=2.0),
            _position_with_net_return(Decimal("3"), "p3", closed_at=3.0),
        ]
        result = max_drawdown(positions)
        assert result == Decimal("0")

    def test_empty_returns_none(self) -> None:
        """No positions -> None."""
        assert max_drawdown([]) is None

    def test_single_loss(self) -> None:
        """Single losing position -> drawdown equals the loss."""
        positions = [
            _position_with_net_return(Decimal("-7"), "p1", closed_at=1.0),
        ]
        result = max_drawdown(positions)
        assert result == Decimal("7")

    def test_single_profit(self) -> None:
        """Single profitable position -> drawdown is 0."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", closed_at=1.0),
        ]
        result = max_drawdown(positions)
        assert result == Decimal("0")

    def test_sorted_by_closed_at(self) -> None:
        """Positions should be sorted by closed_at before computing drawdown.

        Out of order: p2 closed first (+10), p1 closed second (-5).
        Cumulative: [10, 5] -> drawdown = 5.
        """
        positions = [
            _position_with_net_return(Decimal("-5"), "p1", closed_at=2.0),
            _position_with_net_return(Decimal("10"), "p2", closed_at=1.0),
        ]
        result = max_drawdown(positions)
        assert result == Decimal("5")

    def test_deeper_trough_later(self) -> None:
        """Multiple drawdowns -- picks the deepest one.

        Returns: +10, -3, +8, -12 -> cumulative [10, 7, 15, 3]
        Peak 10, trough 7 -> dd=3; Peak 15, trough 3 -> dd=12. Max=12.
        """
        positions = [
            _position_with_net_return(Decimal("10"), "p1", closed_at=1.0),
            _position_with_net_return(Decimal("-3"), "p2", closed_at=2.0),
            _position_with_net_return(Decimal("8"), "p3", closed_at=3.0),
            _position_with_net_return(Decimal("-12"), "p4", closed_at=4.0),
        ]
        result = max_drawdown(positions)
        assert result == Decimal("12")

    def test_with_fees(self) -> None:
        """Drawdown accounts for fees in net return."""
        # funding=10, entry_fee=2, exit_fee=1 -> net=7
        # funding=0, entry_fee=2, exit_fee=1 -> net=-3
        positions = [
            _make_position("p1", [Decimal("10")], Decimal("2"), Decimal("1"), closed_at=1.0),
            _make_position("p2", [Decimal("0")], Decimal("2"), Decimal("1"), closed_at=2.0),
        ]
        result = max_drawdown(positions)
        # Cumulative: [7, 4] -> peak=7, trough=4, dd=3
        assert result == Decimal("3")


# ===========================================================================
# win_rate tests
# ===========================================================================


class TestWinRate:
    """Tests for win_rate(positions)."""

    def test_two_wins_one_loss(self) -> None:
        """2 wins, 1 loss -> 0.667."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1"),
            _position_with_net_return(Decimal("-5"), "p2"),
            _position_with_net_return(Decimal("3"), "p3"),
        ]
        result = win_rate(positions)
        assert result == Decimal("0.667")

    def test_all_wins(self) -> None:
        """All positive returns -> 1.000."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1"),
            _position_with_net_return(Decimal("5"), "p2"),
        ]
        result = win_rate(positions)
        assert result == Decimal("1.000")

    def test_all_losses(self) -> None:
        """All negative returns -> 0.000."""
        positions = [
            _position_with_net_return(Decimal("-10"), "p1"),
            _position_with_net_return(Decimal("-5"), "p2"),
        ]
        result = win_rate(positions)
        assert result == Decimal("0.000")

    def test_empty_returns_none(self) -> None:
        """No positions -> None."""
        assert win_rate([]) is None

    def test_zero_return_is_not_a_win(self) -> None:
        """A position with exactly 0 net return is NOT a win (> 0 required)."""
        positions = [
            _position_with_net_return(Decimal("0"), "p1"),
            _position_with_net_return(Decimal("10"), "p2"),
        ]
        result = win_rate(positions)
        assert result == Decimal("0.500")

    def test_rounding(self) -> None:
        """1 win out of 3 -> 0.333 (ROUND_HALF_UP)."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1"),
            _position_with_net_return(Decimal("-5"), "p2"),
            _position_with_net_return(Decimal("-3"), "p3"),
        ]
        result = win_rate(positions)
        assert result == Decimal("0.333")


# ===========================================================================
# win_rate_by_pair tests
# ===========================================================================


class TestWinRateByPair:
    """Tests for win_rate_by_pair(positions)."""

    def test_multiple_pairs(self) -> None:
        """BTC: 2 wins, 1 loss; ETH: 1 win, 0 loss."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", perp_symbol="BTC/USDT:USDT"),
            _position_with_net_return(Decimal("-5"), "p2", perp_symbol="BTC/USDT:USDT"),
            _position_with_net_return(Decimal("3"), "p3", perp_symbol="BTC/USDT:USDT"),
            _position_with_net_return(Decimal("7"), "p4", perp_symbol="ETH/USDT:USDT"),
        ]
        result = win_rate_by_pair(positions)
        assert result["BTC/USDT:USDT"] == Decimal("0.667")
        assert result["ETH/USDT:USDT"] == Decimal("1.000")

    def test_empty_returns_empty_dict(self) -> None:
        """No positions -> empty dict."""
        assert win_rate_by_pair([]) == {}

    def test_single_pair(self) -> None:
        """All positions same pair."""
        positions = [
            _position_with_net_return(Decimal("10"), "p1", perp_symbol="SOL/USDT:USDT"),
            _position_with_net_return(Decimal("-5"), "p2", perp_symbol="SOL/USDT:USDT"),
        ]
        result = win_rate_by_pair(positions)
        assert len(result) == 1
        assert result["SOL/USDT:USDT"] == Decimal("0.500")
