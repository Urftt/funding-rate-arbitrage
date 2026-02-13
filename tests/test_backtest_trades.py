"""TDD tests for BacktestTrade, TradeStats, and compute_pnl_histogram (TRPL-01/03/05).

Tests cover trade extraction from PositionPnL, aggregate trade statistics,
P&L histogram binning, and edge cases (empty, all-wins, all-same-value).
"""

from decimal import Decimal, ROUND_HALF_UP

import pytest

from bot.pnl.tracker import FundingPayment, PositionPnL
from bot.backtest.models import BacktestTrade, TradeStats, compute_pnl_histogram


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pnl(
    position_id: str = "pos-1",
    entry_fee: Decimal = Decimal("1"),
    exit_fee: Decimal = Decimal("0.5"),
    funding_amounts: list[Decimal] | None = None,
    opened_at: float = 1000.0,
    closed_at: float = 2000.0,
    perp_entry_price: Decimal = Decimal("50000"),
    perp_exit_price: Decimal = Decimal("50100"),
    quantity: Decimal = Decimal("0.1"),
    perp_symbol: str = "BTC/USDT:USDT",
) -> PositionPnL:
    """Build a PositionPnL with specified parameters."""
    if funding_amounts is None:
        funding_amounts = [Decimal("2"), Decimal("1.5"), Decimal("1.5")]
    payments = [
        FundingPayment(
            amount=amt,
            rate=Decimal("0.0001"),
            mark_price=Decimal("50000"),
            timestamp=opened_at + float(i) * 100,
        )
        for i, amt in enumerate(funding_amounts)
    ]
    return PositionPnL(
        position_id=position_id,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        funding_payments=payments,
        spot_entry_price=Decimal("50000"),
        perp_entry_price=perp_entry_price,
        perp_exit_price=perp_exit_price,
        quantity=quantity,
        opened_at=opened_at,
        closed_at=closed_at,
        perp_symbol=perp_symbol,
    )


def _make_trade(
    trade_number: int = 1,
    net_pnl: Decimal = Decimal("3.5"),
    holding_periods: int = 3,
    is_win: bool = True,
) -> BacktestTrade:
    """Build a BacktestTrade with specified net_pnl for stats testing."""
    funding = net_pnl + Decimal("1.5")  # total_fees = 1.5
    return BacktestTrade(
        trade_number=trade_number,
        symbol="BTC/USDT:USDT",
        entry_time_ms=1000000,
        exit_time_ms=2000000,
        entry_price=Decimal("50000"),
        exit_price=Decimal("50100"),
        quantity=Decimal("0.1"),
        funding_collected=funding,
        entry_fee=Decimal("1"),
        exit_fee=Decimal("0.5"),
        total_fees=Decimal("1.5"),
        net_pnl=net_pnl,
        holding_periods=holding_periods,
        is_win=is_win,
    )


# ===========================================================================
# BacktestTrade tests
# ===========================================================================


class TestBacktestTradeFromPositionPnL:
    """Tests for BacktestTrade.from_position_pnl()."""

    def test_backtest_trade_from_position_pnl(self) -> None:
        """Extract trade from PositionPnL with known values."""
        pnl = _make_pnl(
            entry_fee=Decimal("1"),
            exit_fee=Decimal("0.5"),
            funding_amounts=[Decimal("2"), Decimal("1.5"), Decimal("1.5")],
            opened_at=1000.0,
            closed_at=2000.0,
            perp_entry_price=Decimal("50000"),
            perp_exit_price=Decimal("50100"),
            quantity=Decimal("0.1"),
        )
        trade = BacktestTrade.from_position_pnl(pnl, 1)

        assert trade.trade_number == 1
        assert trade.symbol == "BTC/USDT:USDT"
        assert trade.entry_time_ms == 1000000  # 1000.0 * 1000
        assert trade.exit_time_ms == 2000000  # 2000.0 * 1000
        assert trade.entry_price == Decimal("50000")
        assert trade.exit_price == Decimal("50100")
        assert trade.quantity == Decimal("0.1")
        assert trade.funding_collected == Decimal("5")  # 2 + 1.5 + 1.5
        assert trade.entry_fee == Decimal("1")
        assert trade.exit_fee == Decimal("0.5")
        assert trade.total_fees == Decimal("1.5")
        assert trade.net_pnl == Decimal("3.5")  # 5 - 1.5
        assert trade.holding_periods == 3
        assert trade.is_win is True

    def test_backtest_trade_losing_trade(self) -> None:
        """PositionPnL where fees exceed funding -> losing trade."""
        pnl = _make_pnl(
            entry_fee=Decimal("3"),
            exit_fee=Decimal("3"),
            funding_amounts=[Decimal("2")],
        )
        trade = BacktestTrade.from_position_pnl(pnl, 1)

        assert trade.net_pnl == Decimal("-4")  # 2 - (3 + 3) = -4
        assert trade.is_win is False

    def test_backtest_trade_to_dict(self) -> None:
        """to_dict() serializes all Decimal values as strings."""
        pnl = _make_pnl()
        trade = BacktestTrade.from_position_pnl(pnl, 1)
        d = trade.to_dict()

        # All expected keys present
        assert "trade_number" in d
        assert "symbol" in d
        assert "entry_time_ms" in d
        assert "exit_time_ms" in d
        assert "entry_price" in d
        assert "exit_price" in d
        assert "quantity" in d
        assert "funding_collected" in d
        assert "entry_fee" in d
        assert "exit_fee" in d
        assert "total_fees" in d
        assert "net_pnl" in d
        assert "holding_periods" in d
        assert "is_win" in d

        # Decimal fields serialized as strings
        assert isinstance(d["entry_price"], str)
        assert isinstance(d["exit_price"], str)
        assert isinstance(d["quantity"], str)
        assert isinstance(d["funding_collected"], str)
        assert isinstance(d["entry_fee"], str)
        assert isinstance(d["exit_fee"], str)
        assert isinstance(d["total_fees"], str)
        assert isinstance(d["net_pnl"], str)

        # Non-Decimal fields are native types
        assert isinstance(d["trade_number"], int)
        assert isinstance(d["entry_time_ms"], int)
        assert isinstance(d["exit_time_ms"], int)
        assert isinstance(d["holding_periods"], int)
        assert isinstance(d["is_win"], bool)
        assert isinstance(d["symbol"], str)


# ===========================================================================
# TradeStats tests
# ===========================================================================


class TestTradeStats:
    """Tests for TradeStats.from_trades()."""

    def test_trade_stats_from_trades(self) -> None:
        """5 trades (3 wins, 2 losses) -> correct aggregate stats."""
        trades = [
            _make_trade(1, net_pnl=Decimal("10"), is_win=True, holding_periods=3),
            _make_trade(2, net_pnl=Decimal("5"), is_win=True, holding_periods=2),
            _make_trade(3, net_pnl=Decimal("15"), is_win=True, holding_periods=4),
            _make_trade(4, net_pnl=Decimal("-3"), is_win=False, holding_periods=1),
            _make_trade(5, net_pnl=Decimal("-7"), is_win=False, holding_periods=2),
        ]
        stats = TradeStats.from_trades(trades)

        assert stats.total_trades == 5
        assert stats.winning_trades == 3
        assert stats.losing_trades == 2
        assert stats.win_rate == Decimal("0.600")  # 3/5 = 0.6
        assert stats.avg_win == Decimal("10")  # (10 + 5 + 15) / 3 = 10
        assert stats.avg_loss == Decimal("5")  # abs((-3 + -7) / 2) = 5
        assert stats.best_trade == Decimal("15")
        assert stats.worst_trade == Decimal("-7")
        # avg holding periods: (3+2+4+1+2)/5 = 12/5 = 2.4
        assert stats.avg_holding_periods == Decimal("2.4")

    def test_trade_stats_empty_trades(self) -> None:
        """Empty trade list -> all None/zero."""
        stats = TradeStats.from_trades([])

        assert stats.total_trades == 0
        assert stats.winning_trades == 0
        assert stats.losing_trades == 0
        assert stats.win_rate is None
        assert stats.avg_win is None
        assert stats.avg_loss is None
        assert stats.best_trade is None
        assert stats.worst_trade is None
        assert stats.avg_holding_periods is None

    def test_trade_stats_all_wins(self) -> None:
        """All winning trades -> avg_loss is None."""
        trades = [
            _make_trade(1, net_pnl=Decimal("10"), is_win=True, holding_periods=3),
            _make_trade(2, net_pnl=Decimal("5"), is_win=True, holding_periods=2),
        ]
        stats = TradeStats.from_trades(trades)

        assert stats.total_trades == 2
        assert stats.winning_trades == 2
        assert stats.losing_trades == 0
        assert stats.win_rate == Decimal("1.000")
        assert stats.avg_win == Decimal("7.5")  # (10 + 5) / 2
        assert stats.avg_loss is None
        assert stats.best_trade == Decimal("10")
        assert stats.worst_trade == Decimal("5")

    def test_trade_stats_to_dict(self) -> None:
        """Verify Decimal serialization and None handling in to_dict()."""
        trades = [
            _make_trade(1, net_pnl=Decimal("10"), is_win=True),
            _make_trade(2, net_pnl=Decimal("-5"), is_win=False),
        ]
        stats = TradeStats.from_trades(trades)
        d = stats.to_dict()

        assert isinstance(d["total_trades"], int)
        assert isinstance(d["winning_trades"], int)
        assert isinstance(d["losing_trades"], int)
        assert isinstance(d["win_rate"], str)
        assert isinstance(d["avg_win"], str)
        assert isinstance(d["avg_loss"], str)
        assert isinstance(d["best_trade"], str)
        assert isinstance(d["worst_trade"], str)

        # Test None handling with empty trades
        empty_stats = TradeStats.from_trades([])
        d_empty = empty_stats.to_dict()
        assert d_empty["win_rate"] is None
        assert d_empty["avg_win"] is None
        assert d_empty["avg_loss"] is None


# ===========================================================================
# compute_pnl_histogram tests
# ===========================================================================


class TestComputePnlHistogram:
    """Tests for compute_pnl_histogram()."""

    def test_compute_pnl_histogram_basic(self) -> None:
        """10 trades with P&Ls ranging -5 to +5 -> valid histogram."""
        trades = [
            _make_trade(i, net_pnl=Decimal(str(i - 5))) for i in range(10)
        ]
        result = compute_pnl_histogram(trades)

        assert "bins" in result
        assert "counts" in result
        assert len(result["bins"]) > 0
        assert len(result["counts"]) > 0
        assert len(result["bins"]) == len(result["counts"])
        assert sum(result["counts"]) == len(trades)

    def test_compute_pnl_histogram_empty(self) -> None:
        """Empty trades -> empty bins and counts."""
        result = compute_pnl_histogram([])
        assert result == {"bins": [], "counts": []}

    def test_compute_pnl_histogram_same_value(self) -> None:
        """All trades have same net_pnl -> single bin with count=len(trades)."""
        trades = [_make_trade(i, net_pnl=Decimal("5")) for i in range(5)]
        result = compute_pnl_histogram(trades)

        assert len(result["bins"]) == 1
        assert result["counts"] == [5]
