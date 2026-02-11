"""TDD tests for PositionSizer -- RED phase: write tests before implementation.

All test cases use exact Decimal values. PositionSizer must:
- Respect max_position_size_usd from TradingSettings
- Respect available_balance
- Round to qty_step (always down)
- Return None when below min_qty or min_notional
- Calculate matching quantities for spot+perp using coarser step
"""

from decimal import Decimal

import pytest

from bot.config import TradingSettings
from bot.exchange.types import InstrumentInfo
from bot.position.sizing import PositionSizer


@pytest.fixture
def trading_settings() -> TradingSettings:
    """Default trading settings with max_position_size_usd=1000."""
    return TradingSettings(max_position_size_usd=Decimal("1000"))


@pytest.fixture
def sizer(trading_settings: TradingSettings) -> PositionSizer:
    """PositionSizer with default settings."""
    return PositionSizer(trading_settings)


@pytest.fixture
def btc_instrument() -> InstrumentInfo:
    """BTC perpetual instrument constraints."""
    return InstrumentInfo(
        symbol="BTC/USDT:USDT",
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        qty_step=Decimal("0.001"),
        min_notional=Decimal("5"),
    )


@pytest.fixture
def low_price_instrument() -> InstrumentInfo:
    """Low-price token with integer qty_step."""
    return InstrumentInfo(
        symbol="LOW/USDT:USDT",
        min_qty=Decimal("1"),
        max_qty=Decimal("1000000"),
        qty_step=Decimal("1"),
        min_notional=Decimal("10"),
    )


class TestBasicPositionSizing:
    """Test calculate_quantity with standard inputs."""

    def test_btc_config_limited(
        self, sizer: PositionSizer, btc_instrument: InstrumentInfo
    ) -> None:
        """Max position 1000 USD at 50,000 BTC = 0.020 BTC."""
        qty = sizer.calculate_quantity(
            price=Decimal("50000"),
            available_balance=Decimal("10000"),
            instrument=btc_instrument,
        )
        # 1000 / 50000 = 0.02, rounded to step 0.001 = 0.020
        assert qty == Decimal("0.020")

    def test_low_price_token(
        self, sizer: PositionSizer, low_price_instrument: InstrumentInfo
    ) -> None:
        """Low-price token: 1000/3 = 333.33, rounded down to step=1 -> 333."""
        qty = sizer.calculate_quantity(
            price=Decimal("3"),
            available_balance=Decimal("10000"),
            instrument=low_price_instrument,
        )
        assert qty == Decimal("333")


class TestBalanceLimited:
    """Test that available_balance limits position size."""

    def test_balance_smaller_than_config(
        self, sizer: PositionSizer, btc_instrument: InstrumentInfo
    ) -> None:
        """Balance 500 < max_position 1000: limited by balance."""
        qty = sizer.calculate_quantity(
            price=Decimal("50000"),
            available_balance=Decimal("500"),
            instrument=btc_instrument,
        )
        # 500 / 50000 = 0.01, rounded to step 0.001 = 0.010
        assert qty == Decimal("0.010")


class TestBelowMinimum:
    """Test that None is returned when quantity would be below min_qty."""

    def test_below_min_qty(
        self, sizer: PositionSizer, btc_instrument: InstrumentInfo
    ) -> None:
        """Balance $10: 10/50000=0.0002, below min_qty 0.001 -> None."""
        qty = sizer.calculate_quantity(
            price=Decimal("50000"),
            available_balance=Decimal("10"),
            instrument=btc_instrument,
        )
        assert qty is None


class TestMinNotional:
    """Test that min_notional constraint is enforced."""

    def test_below_min_notional(self, sizer: PositionSizer) -> None:
        """Tiny price: calculated qty * price < min_notional -> None."""
        instrument = InstrumentInfo(
            symbol="TINY/USDT:USDT",
            min_qty=Decimal("1"),
            max_qty=Decimal("1000000"),
            qty_step=Decimal("1"),
            min_notional=Decimal("10"),
        )
        # With max_position=1000 and price=0.001:
        # raw = 1000/0.001 = 1,000,000 (capped by max_qty? No, max_qty=1000000)
        # But let's use a scenario where min_notional blocks:
        # Small balance: 5 / 0.01 = 500, qty*price = 500*0.01 = 5 < 10
        qty = sizer.calculate_quantity(
            price=Decimal("0.01"),
            available_balance=Decimal("5"),
            instrument=instrument,
        )
        assert qty is None

    def test_above_min_notional(self, sizer: PositionSizer) -> None:
        """Price where qty * price >= min_notional should succeed."""
        instrument = InstrumentInfo(
            symbol="LOW/USDT:USDT",
            min_qty=Decimal("1"),
            max_qty=Decimal("1000000"),
            qty_step=Decimal("1"),
            min_notional=Decimal("10"),
        )
        qty = sizer.calculate_quantity(
            price=Decimal("0.01"),
            available_balance=Decimal("10000"),
            instrument=instrument,
        )
        # raw = 1000/0.01 = 100000, rounded to step=1 = 100000
        # notional = 100000 * 0.01 = 1000 >= 10 OK
        assert qty is not None
        assert qty == Decimal("100000")


class TestStepRounding:
    """Test that quantity is always rounded DOWN to qty_step."""

    def test_round_to_step(self, sizer: PositionSizer) -> None:
        """1000/100=10.0, step=0.1, result=10.0 (exact)."""
        instrument = InstrumentInfo(
            symbol="ETH/USDT:USDT",
            min_qty=Decimal("0.1"),
            max_qty=Decimal("10000"),
            qty_step=Decimal("0.1"),
            min_notional=Decimal("5"),
        )
        qty = sizer.calculate_quantity(
            price=Decimal("100"),
            available_balance=Decimal("10000"),
            instrument=instrument,
        )
        assert qty == Decimal("10.0")

    def test_round_down_not_up(self, sizer: PositionSizer) -> None:
        """Ensure rounding is always DOWN, never nearest or up."""
        instrument = InstrumentInfo(
            symbol="X/USDT:USDT",
            min_qty=Decimal("0.01"),
            max_qty=Decimal("100000"),
            qty_step=Decimal("0.01"),
            min_notional=Decimal("1"),
        )
        # 1000 / 33 = 30.30303..., step 0.01 -> 30.30
        qty = sizer.calculate_quantity(
            price=Decimal("33"),
            available_balance=Decimal("10000"),
            instrument=instrument,
        )
        assert qty == Decimal("30.30")


class TestMatchingQuantity:
    """Test calculate_matching_quantity for spot+perp alignment."""

    def test_matching_same_step(self, sizer: PositionSizer) -> None:
        """Both instruments have same qty_step -> standard calculation."""
        spot = InstrumentInfo(
            symbol="BTC/USDT",
            min_qty=Decimal("0.001"),
            max_qty=Decimal("100"),
            qty_step=Decimal("0.001"),
            min_notional=Decimal("5"),
        )
        perp = InstrumentInfo(
            symbol="BTC/USDT:USDT",
            min_qty=Decimal("0.001"),
            max_qty=Decimal("100"),
            qty_step=Decimal("0.001"),
            min_notional=Decimal("5"),
        )
        qty = sizer.calculate_matching_quantity(
            price=Decimal("50000"),
            available_balance=Decimal("10000"),
            spot_instrument=spot,
            perp_instrument=perp,
        )
        assert qty == Decimal("0.020")

    def test_matching_different_step_uses_coarser(
        self, sizer: PositionSizer
    ) -> None:
        """Spot step=0.001, perp step=0.01 -> uses 0.01 (coarser)."""
        spot = InstrumentInfo(
            symbol="ETH/USDT",
            min_qty=Decimal("0.001"),
            max_qty=Decimal("10000"),
            qty_step=Decimal("0.001"),
            min_notional=Decimal("5"),
        )
        perp = InstrumentInfo(
            symbol="ETH/USDT:USDT",
            min_qty=Decimal("0.01"),
            max_qty=Decimal("10000"),
            qty_step=Decimal("0.01"),
            min_notional=Decimal("5"),
        )
        qty = sizer.calculate_matching_quantity(
            price=Decimal("3000"),
            available_balance=Decimal("10000"),
            spot_instrument=spot,
            perp_instrument=perp,
        )
        # 1000/3000 = 0.3333..., coarser step=0.01, round down = 0.33
        assert qty == Decimal("0.33")

    def test_matching_returns_none_below_min(self, sizer: PositionSizer) -> None:
        """If matching quantity is below either min_qty, return None."""
        spot = InstrumentInfo(
            symbol="BTC/USDT",
            min_qty=Decimal("0.01"),
            max_qty=Decimal("100"),
            qty_step=Decimal("0.01"),
            min_notional=Decimal("5"),
        )
        perp = InstrumentInfo(
            symbol="BTC/USDT:USDT",
            min_qty=Decimal("0.01"),
            max_qty=Decimal("100"),
            qty_step=Decimal("0.01"),
            min_notional=Decimal("5"),
        )
        # $10 balance at $50000 = 0.0002, below min_qty 0.01
        qty = sizer.calculate_matching_quantity(
            price=Decimal("50000"),
            available_balance=Decimal("10"),
            spot_instrument=spot,
            perp_instrument=perp,
        )
        assert qty is None


class TestValidateMatchingQuantity:
    """Test validate_matching_quantity for fill comparison."""

    def test_exact_match(self, sizer: PositionSizer) -> None:
        """Identical quantities are valid."""
        assert sizer.validate_matching_quantity(
            spot_qty=Decimal("1.0"),
            perp_qty=Decimal("1.0"),
        ) is True

    def test_within_step_tolerance(self, sizer: PositionSizer) -> None:
        """Quantities within 0.001 step tolerance are valid."""
        assert sizer.validate_matching_quantity(
            spot_qty=Decimal("1.001"),
            perp_qty=Decimal("1.0"),
        ) is True

    def test_exceeds_tolerance(self, sizer: PositionSizer) -> None:
        """Quantities differing by more than tolerance are invalid."""
        assert sizer.validate_matching_quantity(
            spot_qty=Decimal("1.1"),
            perp_qty=Decimal("1.0"),
        ) is False
