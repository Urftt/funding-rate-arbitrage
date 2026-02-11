"""Tests for the P&L tracker with funding fee simulation.

Tests verify:
- record_open initializes PositionPnL correctly
- record_funding_payment accumulates funding
- get_unrealized_pnl_with_prices calculates correctly when prices move
- get_total_pnl returns correct breakdown
- Net P&L positive when funding > fees (profitable scenario)
- Net P&L negative when funding < fees (unprofitable scenario)
- Portfolio summary aggregates multiple positions
- simulate_funding_settlement processes all open positions
"""

import time
from decimal import Decimal

import pytest

from bot.config import FeeSettings
from bot.market_data.ticker_service import TickerService
from bot.models import FundingRateData, Position, PositionSide
from bot.pnl.fee_calculator import FeeCalculator
from bot.pnl.tracker import PnLTracker


@pytest.fixture
def fee_settings() -> FeeSettings:
    """Standard fee settings for testing."""
    return FeeSettings()


@pytest.fixture
def fee_calculator(fee_settings: FeeSettings) -> FeeCalculator:
    """FeeCalculator with standard settings."""
    return FeeCalculator(fee_settings)


@pytest.fixture
def ticker_service() -> TickerService:
    """Empty TickerService for testing."""
    return TickerService()


@pytest.fixture
def tracker(
    fee_calculator: FeeCalculator,
    ticker_service: TickerService,
    fee_settings: FeeSettings,
) -> PnLTracker:
    """PnLTracker with standard dependencies."""
    return PnLTracker(fee_calculator, ticker_service, fee_settings)


@pytest.fixture
def sample_position() -> Position:
    """Sample delta-neutral position for testing."""
    return Position(
        id="pos_001",
        spot_symbol="BTC/USDT",
        perp_symbol="BTC/USDT:USDT",
        side=PositionSide.SHORT,
        quantity=Decimal("0.1"),
        spot_entry_price=Decimal("50000"),
        perp_entry_price=Decimal("50010"),
        spot_order_id="spot_order_1",
        perp_order_id="perp_order_1",
        opened_at=time.time(),
        entry_fee_total=Decimal("7.75"),  # 0.1 * 50000 * 0.001 + 0.1 * 50010 * 0.00055
    )


class TestRecordOpen:
    """Tests for record_open."""

    def test_initializes_position_pnl(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """record_open creates PositionPnL with correct fields."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        pnl = tracker.get_position_pnl("pos_001")
        assert pnl is not None
        assert pnl.position_id == "pos_001"
        assert pnl.entry_fee == Decimal("7.75")
        assert pnl.exit_fee == Decimal("0")
        assert pnl.funding_payments == []
        assert pnl.spot_entry_price == Decimal("50000")
        assert pnl.perp_entry_price == Decimal("50010")
        assert pnl.quantity == Decimal("0.1")
        assert pnl.closed_at is None

    def test_tracks_opened_at_timestamp(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """record_open stores the position's opened_at timestamp."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        pnl = tracker.get_position_pnl("pos_001")
        assert pnl is not None
        assert pnl.opened_at == sample_position.opened_at


class TestRecordFundingPayment:
    """Tests for record_funding_payment."""

    def test_accumulates_funding_payments(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Funding payments accumulate in the position's payment list."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        # Record two funding payments
        tracker.record_funding_payment(
            position_id="pos_001",
            funding_rate=Decimal("0.0005"),
            mark_price=Decimal("50000"),
            quantity=Decimal("0.1"),
        )
        tracker.record_funding_payment(
            position_id="pos_001",
            funding_rate=Decimal("0.0003"),
            mark_price=Decimal("50100"),
            quantity=Decimal("0.1"),
        )

        pnl = tracker.get_position_pnl("pos_001")
        assert pnl is not None
        assert len(pnl.funding_payments) == 2

    def test_positive_rate_generates_income_for_short(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Positive funding rate generates income for short perp position."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        tracker.record_funding_payment(
            position_id="pos_001",
            funding_rate=Decimal("0.0005"),  # Positive rate
            mark_price=Decimal("50000"),
            quantity=Decimal("0.1"),
        )

        pnl = tracker.get_position_pnl("pos_001")
        assert pnl is not None
        assert len(pnl.funding_payments) == 1
        # Payment = 0.1 * 50000 * 0.0005 = 2.5 (positive = income for short)
        assert pnl.funding_payments[0].amount == Decimal("2.5")
        assert pnl.funding_payments[0].amount > 0

    def test_negative_rate_generates_expense_for_short(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Negative funding rate generates expense for short perp position."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        tracker.record_funding_payment(
            position_id="pos_001",
            funding_rate=Decimal("-0.0003"),  # Negative rate
            mark_price=Decimal("50000"),
            quantity=Decimal("0.1"),
        )

        pnl = tracker.get_position_pnl("pos_001")
        assert pnl is not None
        # Payment = 0.1 * 50000 * (-0.0003) = -1.5 (negative = expense for short)
        assert pnl.funding_payments[0].amount == Decimal("-1.5")
        assert pnl.funding_payments[0].amount < 0


class TestGetUnrealizedPnL:
    """Tests for get_unrealized_pnl_with_prices."""

    @pytest.mark.asyncio
    async def test_zero_when_prices_unchanged(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Unrealized P&L is zero when prices haven't moved."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        unrealized = await tracker.get_unrealized_pnl_with_prices(
            "pos_001",
            current_spot_price=Decimal("50000"),
            current_perp_price=Decimal("50010"),
        )
        assert unrealized == Decimal("0")

    @pytest.mark.asyncio
    async def test_near_zero_for_parallel_price_move(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Unrealized P&L near zero when spot and perp move together (delta-neutral)."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        # Both prices move up by same amount
        unrealized = await tracker.get_unrealized_pnl_with_prices(
            "pos_001",
            current_spot_price=Decimal("51000"),
            current_perp_price=Decimal("51010"),
        )
        # Spot: (51000 - 50000) * 0.1 = +100
        # Perp: (50010 - 51010) * 0.1 = -100
        # Total = 0
        assert unrealized == Decimal("0")

    @pytest.mark.asyncio
    async def test_positive_when_basis_narrows(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Unrealized P&L positive when basis narrows (perp drops more than spot)."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        unrealized = await tracker.get_unrealized_pnl_with_prices(
            "pos_001",
            current_spot_price=Decimal("50000"),  # Spot unchanged
            current_perp_price=Decimal("49900"),  # Perp dropped
        )
        # Spot: (50000 - 50000) * 0.1 = 0
        # Perp: (50010 - 49900) * 0.1 = +11
        assert unrealized == Decimal("11.0")
        assert unrealized > 0


class TestGetTotalPnL:
    """Tests for get_total_pnl."""

    def test_returns_correct_breakdown(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """get_total_pnl returns correct P&L components."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        # Record some funding
        tracker.record_funding_payment(
            position_id="pos_001",
            funding_rate=Decimal("0.0005"),
            mark_price=Decimal("50000"),
            quantity=Decimal("0.1"),
        )

        result = tracker.get_total_pnl("pos_001", unrealized_pnl=Decimal("0"))

        assert result["unrealized_pnl"] == Decimal("0")
        assert result["total_funding"] == Decimal("2.5")  # 0.1 * 50000 * 0.0005
        assert result["total_fees"] == Decimal("7.75")  # entry only, no exit yet
        # net = 0 + 2.5 - 7.75 = -5.25
        assert result["net_pnl"] == Decimal("-5.25")

    def test_includes_exit_fee_when_closed(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Total fees include exit fee after position is closed."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))
        tracker.record_close(
            "pos_001",
            spot_exit_price=Decimal("50000"),
            perp_exit_price=Decimal("50000"),
            exit_fee=Decimal("7.50"),
        )

        result = tracker.get_total_pnl("pos_001")
        assert result["total_fees"] == Decimal("15.25")  # 7.75 + 7.50

    def test_net_pnl_positive_when_funding_exceeds_fees(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Net P&L is positive when funding income exceeds total fees."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        # Simulate many funding payments (profitable scenario)
        for _ in range(10):
            tracker.record_funding_payment(
                position_id="pos_001",
                funding_rate=Decimal("0.001"),  # High rate
                mark_price=Decimal("50000"),
                quantity=Decimal("0.1"),
            )

        # Total funding: 10 * (0.1 * 50000 * 0.001) = 10 * 5 = 50
        # Total fees: 7.75 (entry only)
        result = tracker.get_total_pnl("pos_001", unrealized_pnl=Decimal("0"))

        assert result["total_funding"] == Decimal("50")
        assert result["net_pnl"] > 0
        assert result["net_pnl"] == Decimal("42.25")  # 50 - 7.75

    def test_net_pnl_negative_when_fees_exceed_funding(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """Net P&L is negative when total fees exceed funding income."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        # Close with exit fee
        tracker.record_close(
            "pos_001",
            spot_exit_price=Decimal("50000"),
            perp_exit_price=Decimal("50000"),
            exit_fee=Decimal("7.50"),
        )

        # Only one small funding payment
        tracker.record_funding_payment(
            position_id="pos_001",
            funding_rate=Decimal("0.0001"),  # Low rate
            mark_price=Decimal("50000"),
            quantity=Decimal("0.1"),
        )

        # Total funding: 0.1 * 50000 * 0.0001 = 0.5
        # Total fees: 7.75 + 7.50 = 15.25
        result = tracker.get_total_pnl("pos_001", unrealized_pnl=Decimal("0"))

        assert result["total_funding"] == Decimal("0.5")
        assert result["total_fees"] == Decimal("15.25")
        assert result["net_pnl"] < 0
        assert result["net_pnl"] == Decimal("-14.75")  # 0.5 - 15.25


class TestSimulateFundingSettlement:
    """Tests for simulate_funding_settlement."""

    def test_records_payments_for_all_positions(
        self, tracker: PnLTracker
    ) -> None:
        """simulate_funding_settlement records payments for all open positions."""
        now = time.time()

        # Create two positions
        pos1 = Position(
            id="pos_001",
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("0.1"),
            spot_entry_price=Decimal("50000"),
            perp_entry_price=Decimal("50010"),
            spot_order_id="s1",
            perp_order_id="p1",
            opened_at=now,
            entry_fee_total=Decimal("7.75"),
        )
        pos2 = Position(
            id="pos_002",
            spot_symbol="ETH/USDT",
            perp_symbol="ETH/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("1.0"),
            spot_entry_price=Decimal("3000"),
            perp_entry_price=Decimal("3001"),
            spot_order_id="s2",
            perp_order_id="p2",
            opened_at=now,
            entry_fee_total=Decimal("4.65"),
        )

        tracker.record_open(pos1, entry_fee=Decimal("7.75"))
        tracker.record_open(pos2, entry_fee=Decimal("4.65"))

        funding_rates = {
            "BTC/USDT:USDT": FundingRateData(
                symbol="BTC/USDT:USDT",
                rate=Decimal("0.0005"),
                next_funding_time=0,
                mark_price=Decimal("50000"),
            ),
            "ETH/USDT:USDT": FundingRateData(
                symbol="ETH/USDT:USDT",
                rate=Decimal("0.0003"),
                next_funding_time=0,
                mark_price=Decimal("3000"),
            ),
        }

        tracker.simulate_funding_settlement([pos1, pos2], funding_rates)

        pnl1 = tracker.get_position_pnl("pos_001")
        pnl2 = tracker.get_position_pnl("pos_002")
        assert pnl1 is not None
        assert pnl2 is not None
        assert len(pnl1.funding_payments) == 1
        assert len(pnl2.funding_payments) == 1

        # BTC: 0.1 * 50000 * 0.0005 = 2.5
        assert pnl1.funding_payments[0].amount == Decimal("2.5")
        # ETH: 1.0 * 3000 * 0.0003 = 0.9
        assert pnl2.funding_payments[0].amount == Decimal("0.9")

    def test_skips_positions_without_funding_rate(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """simulate_funding_settlement skips positions with no matching rate."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        # Empty funding rates -- no matching symbol
        tracker.simulate_funding_settlement([sample_position], {})

        pnl = tracker.get_position_pnl("pos_001")
        assert pnl is not None
        assert len(pnl.funding_payments) == 0


class TestPortfolioSummary:
    """Tests for get_portfolio_summary."""

    def test_aggregates_multiple_positions(
        self, tracker: PnLTracker
    ) -> None:
        """Portfolio summary aggregates across all positions."""
        now = time.time()

        pos1 = Position(
            id="pos_001",
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("0.1"),
            spot_entry_price=Decimal("50000"),
            perp_entry_price=Decimal("50010"),
            spot_order_id="s1",
            perp_order_id="p1",
            opened_at=now,
            entry_fee_total=Decimal("7.75"),
        )
        pos2 = Position(
            id="pos_002",
            spot_symbol="ETH/USDT",
            perp_symbol="ETH/USDT:USDT",
            side=PositionSide.SHORT,
            quantity=Decimal("1.0"),
            spot_entry_price=Decimal("3000"),
            perp_entry_price=Decimal("3001"),
            spot_order_id="s2",
            perp_order_id="p2",
            opened_at=now,
            entry_fee_total=Decimal("4.65"),
        )

        tracker.record_open(pos1, entry_fee=Decimal("7.75"))
        tracker.record_open(pos2, entry_fee=Decimal("4.65"))

        # Add funding to both
        tracker.record_funding_payment(
            "pos_001", Decimal("0.0005"), Decimal("50000"), Decimal("0.1")
        )
        tracker.record_funding_payment(
            "pos_002", Decimal("0.0003"), Decimal("3000"), Decimal("1.0")
        )

        summary = tracker.get_portfolio_summary()

        assert summary["position_count"] == 2
        # Total funding: 2.5 + 0.9 = 3.4
        assert summary["total_funding_collected"] == Decimal("3.4")
        # Total fees: 7.75 + 4.65 = 12.4
        assert summary["total_fees_paid"] == Decimal("12.4")
        # Net: 3.4 - 12.4 = -9.0
        assert summary["net_portfolio_pnl"] == Decimal("-9.0")

    def test_empty_portfolio(self, tracker: PnLTracker) -> None:
        """Portfolio summary handles empty state."""
        summary = tracker.get_portfolio_summary()

        assert summary["position_count"] == 0
        assert summary["total_funding_collected"] == Decimal("0")
        assert summary["total_fees_paid"] == Decimal("0")
        assert summary["net_portfolio_pnl"] == Decimal("0")


class TestRecordClose:
    """Tests for record_close."""

    def test_sets_exit_fee_and_closed_at(
        self, tracker: PnLTracker, sample_position: Position
    ) -> None:
        """record_close sets exit_fee and closed_at timestamp."""
        tracker.record_open(sample_position, entry_fee=Decimal("7.75"))

        tracker.record_close(
            "pos_001",
            spot_exit_price=Decimal("50100"),
            perp_exit_price=Decimal("50050"),
            exit_fee=Decimal("7.50"),
        )

        pnl = tracker.get_position_pnl("pos_001")
        assert pnl is not None
        assert pnl.exit_fee == Decimal("7.50")
        assert pnl.closed_at is not None

    def test_raises_for_unknown_position(
        self, tracker: PnLTracker
    ) -> None:
        """record_close raises KeyError for unknown position."""
        with pytest.raises(KeyError):
            tracker.record_close(
                "nonexistent",
                spot_exit_price=Decimal("50000"),
                perp_exit_price=Decimal("50000"),
                exit_fee=Decimal("7.50"),
            )
