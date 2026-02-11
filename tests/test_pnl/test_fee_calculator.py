"""TDD tests for FeeCalculator -- RED phase: write tests before implementation.

All test cases use exact Decimal values to verify precision.
Fee rates from Bybit Non-VIP base tier (verified Feb 2026):
  - Spot taker: 0.1% (0.001)
  - Perp taker: 0.055% (0.00055)
"""

from decimal import Decimal

import pytest

from bot.config import FeeSettings
from bot.pnl.fee_calculator import FeeCalculator


@pytest.fixture
def fee_settings() -> FeeSettings:
    """Default Bybit Non-VIP fee settings."""
    return FeeSettings()


@pytest.fixture
def calculator(fee_settings: FeeSettings) -> FeeCalculator:
    """FeeCalculator with default fee settings."""
    return FeeCalculator(fee_settings)


class TestEntryFee:
    """Test calculate_entry_fee: spot taker + perp taker on entry."""

    def test_btc_equal_prices(self, calculator: FeeCalculator) -> None:
        """1 BTC at $50,000 spot and $50,000 perp."""
        fee = calculator.calculate_entry_fee(
            quantity=Decimal("1.0"),
            spot_price=Decimal("50000"),
            perp_price=Decimal("50000"),
        )
        # spot: 1.0 * 50000 * 0.001 = 50.0
        # perp: 1.0 * 50000 * 0.00055 = 27.5
        # total: 77.5
        assert fee == Decimal("77.5")

    def test_eth_different_prices(self, calculator: FeeCalculator) -> None:
        """0.5 ETH at $3,000 spot and $3,010 perp (basis spread)."""
        fee = calculator.calculate_entry_fee(
            quantity=Decimal("0.5"),
            spot_price=Decimal("3000"),
            perp_price=Decimal("3010"),
        )
        # spot: 0.5 * 3000 * 0.001 = 1.5
        # perp: 0.5 * 3010 * 0.00055 = 0.82775
        # total: 2.32775
        assert fee == Decimal("2.32775")


class TestExitFee:
    """Test calculate_exit_fee: spot taker + perp taker on exit."""

    def test_btc_exit_different_prices(self, calculator: FeeCalculator) -> None:
        """Exit 1 BTC: spot at $51,000 (sell), perp at $49,000 (close short)."""
        fee = calculator.calculate_exit_fee(
            quantity=Decimal("1.0"),
            spot_price=Decimal("51000"),
            perp_price=Decimal("49000"),
        )
        # spot: 1.0 * 51000 * 0.001 = 51.0
        # perp: 1.0 * 49000 * 0.00055 = 26.95
        # total: 77.95
        assert fee == Decimal("77.95")


class TestRoundTripFee:
    """Test calculate_round_trip_fee: entry + exit combined."""

    def test_round_trip_btc(self, calculator: FeeCalculator) -> None:
        """Full round trip: entry at 50k/50k, exit at 51k/49k."""
        fee = calculator.calculate_round_trip_fee(
            quantity=Decimal("1.0"),
            spot_entry_price=Decimal("50000"),
            perp_entry_price=Decimal("50000"),
            spot_exit_price=Decimal("51000"),
            perp_exit_price=Decimal("49000"),
        )
        # entry: 77.5 + exit: 77.95 = 155.45
        assert fee == Decimal("155.45")


class TestBreakEvenFundingRate:
    """Test min_funding_rate_for_breakeven: minimum rate to cover fees."""

    def test_breakeven_3_periods(self, calculator: FeeCalculator) -> None:
        """Break-even funding rate over 3 funding periods (24h)."""
        rate = calculator.min_funding_rate_for_breakeven(
            quantity=Decimal("1.0"),
            entry_price=Decimal("50000"),
            round_trip_fee=Decimal("155"),
            funding_periods=3,
        )
        # 155 / (1.0 * 50000 * 3) = 155 / 150000 = 0.001033333...
        # We check it's approximately right (Decimal division is exact rational)
        expected = Decimal("155") / (Decimal("1.0") * Decimal("50000") * Decimal("3"))
        assert rate == expected

    def test_breakeven_higher_fee(self, calculator: FeeCalculator) -> None:
        """Higher fees require higher funding rate."""
        rate = calculator.min_funding_rate_for_breakeven(
            quantity=Decimal("1.0"),
            entry_price=Decimal("50000"),
            round_trip_fee=Decimal("310"),
            funding_periods=3,
        )
        expected = Decimal("310") / (Decimal("50000") * Decimal("3"))
        assert rate == expected


class TestIsProfitable:
    """Test is_profitable: expected funding vs round-trip fees."""

    def test_not_profitable_3_periods(self, calculator: FeeCalculator) -> None:
        """At 0.1% rate over 3 periods, expected funding < fees."""
        result = calculator.is_profitable(
            funding_rate=Decimal("0.001"),
            quantity=Decimal("1.0"),
            entry_price=Decimal("50000"),
            min_periods=3,
        )
        # expected funding: 1.0 * 50000 * 0.001 * 3 = 150
        # round-trip fee (approx): 50000 * (0.001 + 0.00055) * 2 = 155
        # 150 < 155 => not profitable
        assert result is False

    def test_profitable_4_periods(self, calculator: FeeCalculator) -> None:
        """At 0.1% rate over 4 periods, expected funding > fees."""
        result = calculator.is_profitable(
            funding_rate=Decimal("0.001"),
            quantity=Decimal("1.0"),
            entry_price=Decimal("50000"),
            min_periods=4,
        )
        # expected funding: 1.0 * 50000 * 0.001 * 4 = 200
        # round-trip fee (approx): ~155
        # 200 > 155 => profitable
        assert result is True


class TestFundingPayment:
    """Test calculate_funding_payment: Bybit convention encoding.

    Bybit convention: positive funding rate = longs pay shorts.
    Our strategy: LONG spot + SHORT perp = we COLLECT when rate > 0.
    """

    def test_short_positive_rate_receives(self, calculator: FeeCalculator) -> None:
        """Short position with positive rate receives funding."""
        payment = calculator.calculate_funding_payment(
            position_qty=Decimal("1.0"),
            mark_price=Decimal("50000"),
            funding_rate=Decimal("0.001"),
            is_short=True,
        )
        # position_value = 1.0 * 50000 = 50000
        # payment = 50000 * 0.001 = 50 (positive = income for short)
        assert payment == Decimal("50")

    def test_long_positive_rate_pays(self, calculator: FeeCalculator) -> None:
        """Long position with positive rate pays funding."""
        payment = calculator.calculate_funding_payment(
            position_qty=Decimal("1.0"),
            mark_price=Decimal("50000"),
            funding_rate=Decimal("0.001"),
            is_short=False,
        )
        # payment = -(50000 * 0.001) = -50 (negative = expense for long)
        assert payment == Decimal("-50")

    def test_short_negative_rate_pays(self, calculator: FeeCalculator) -> None:
        """Short position with negative rate pays funding (shorts pay longs)."""
        payment = calculator.calculate_funding_payment(
            position_qty=Decimal("1.0"),
            mark_price=Decimal("50000"),
            funding_rate=Decimal("-0.0005"),
            is_short=True,
        )
        # position_value = 50000
        # raw_payment = 50000 * -0.0005 = -25 (negative = expense for short)
        assert payment == Decimal("-25")

    def test_long_negative_rate_receives(self, calculator: FeeCalculator) -> None:
        """Long position with negative rate receives funding."""
        payment = calculator.calculate_funding_payment(
            position_qty=Decimal("1.0"),
            mark_price=Decimal("50000"),
            funding_rate=Decimal("-0.0005"),
            is_short=False,
        )
        # raw = 50000 * -0.0005 = -25
        # long: negate => 25 (positive = income)
        assert payment == Decimal("25")
