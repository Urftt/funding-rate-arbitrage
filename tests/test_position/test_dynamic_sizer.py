"""TDD tests for DynamicSizer -- RED phase: write tests before implementation.

Proves SIZE-01 (signal-conviction scaling), SIZE-02 (portfolio exposure cap),
SIZE-03 (PositionSizer delegation).

All test cases use exact Decimal values. DynamicSizer must:
- Map signal score to allocation fraction (linear interpolation)
- Compute USD budget capped by portfolio exposure limit
- Delegate to PositionSizer.calculate_matching_quantity for exchange constraints
- Return None when portfolio cap reached
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from bot.config import DynamicSizingSettings, TradingSettings
from bot.exchange.types import InstrumentInfo
from bot.position.dynamic_sizer import DynamicSizer
from bot.position.sizing import PositionSizer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sizing_settings() -> DynamicSizingSettings:
    """Default dynamic sizing settings."""
    return DynamicSizingSettings(
        enabled=True,
        min_allocation_fraction=Decimal("0.3"),
        max_allocation_fraction=Decimal("1.0"),
        max_portfolio_exposure=Decimal("5000"),
    )


@pytest.fixture
def trading_settings() -> TradingSettings:
    """Trading settings with max_position_size_usd=1000."""
    return TradingSettings(max_position_size_usd=Decimal("1000"))


@pytest.fixture
def position_sizer(trading_settings: TradingSettings) -> PositionSizer:
    """Real PositionSizer from trading settings."""
    return PositionSizer(trading_settings)


@pytest.fixture
def dynamic_sizer(
    position_sizer: PositionSizer,
    sizing_settings: DynamicSizingSettings,
    trading_settings: TradingSettings,
) -> DynamicSizer:
    """DynamicSizer wrapping real PositionSizer."""
    return DynamicSizer(
        position_sizer=position_sizer,
        settings=sizing_settings,
        max_position_size_usd=trading_settings.max_position_size_usd,
    )


@pytest.fixture
def spot_instrument() -> InstrumentInfo:
    """Generous spot instrument for testing (low minimums)."""
    return InstrumentInfo(
        symbol="BTC/USDT",
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        qty_step=Decimal("0.001"),
        min_notional=Decimal("5"),
    )


@pytest.fixture
def perp_instrument() -> InstrumentInfo:
    """Generous perp instrument for testing (low minimums)."""
    return InstrumentInfo(
        symbol="BTC/USDT:USDT",
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        qty_step=Decimal("0.001"),
        min_notional=Decimal("5"),
    )


# ---------------------------------------------------------------------------
# SIZE-01: Signal-conviction scaling
# ---------------------------------------------------------------------------


class TestSignalBudget:
    """Test compute_signal_budget maps signal score to USD budget."""

    def test_strong_signal_larger_than_weak(
        self, dynamic_sizer: DynamicSizer
    ) -> None:
        """SIZE-01: score=0.9 budget > score=0.3 budget."""
        strong = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("0.9"),
            current_exposure=Decimal("0"),
        )
        weak = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("0.3"),
            current_exposure=Decimal("0"),
        )
        assert strong is not None
        assert weak is not None
        assert strong > weak

    def test_max_score_full_allocation(
        self, dynamic_sizer: DynamicSizer
    ) -> None:
        """score=1.0 -> fraction=1.0, budget = max_position_size_usd * 1.0 = 1000."""
        budget = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("1.0"),
            current_exposure=Decimal("0"),
        )
        assert budget == Decimal("1000")

    def test_min_score_min_allocation(
        self, dynamic_sizer: DynamicSizer
    ) -> None:
        """score=0.0 -> fraction=0.3, budget = 1000 * 0.3 = 300."""
        budget = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("0.0"),
            current_exposure=Decimal("0"),
        )
        assert budget == Decimal("300")

    def test_mid_score_linear_interpolation(
        self, dynamic_sizer: DynamicSizer
    ) -> None:
        """score=0.5 -> fraction = 0.3 + (1.0 - 0.3) * 0.5 = 0.65, budget = 650."""
        budget = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("0.5"),
            current_exposure=Decimal("0"),
        )
        assert budget == Decimal("650")


# ---------------------------------------------------------------------------
# SIZE-02: Portfolio exposure cap
# ---------------------------------------------------------------------------


class TestPortfolioCap:
    """Test portfolio exposure cap enforcement."""

    def test_budget_none_at_cap(self, dynamic_sizer: DynamicSizer) -> None:
        """SIZE-02: exposure=5000 (at cap=5000) -> None."""
        budget = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("1.0"),
            current_exposure=Decimal("5000"),
        )
        assert budget is None

    def test_budget_none_over_cap(self, dynamic_sizer: DynamicSizer) -> None:
        """exposure=6000 (over cap=5000) -> None."""
        budget = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("1.0"),
            current_exposure=Decimal("6000"),
        )
        assert budget is None

    def test_budget_capped_by_remaining(
        self, dynamic_sizer: DynamicSizer
    ) -> None:
        """exposure=4500, cap=5000, score=1.0 -> remaining=500, budget=min(1000, 500)=500."""
        budget = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("1.0"),
            current_exposure=Decimal("4500"),
        )
        assert budget == Decimal("500")

    def test_zero_exposure_full_budget(
        self, dynamic_sizer: DynamicSizer
    ) -> None:
        """exposure=0 -> full raw budget (not capped by remaining)."""
        budget = dynamic_sizer.compute_signal_budget(
            signal_score=Decimal("1.0"),
            current_exposure=Decimal("0"),
        )
        assert budget == Decimal("1000")


# ---------------------------------------------------------------------------
# SIZE-03: Delegation to PositionSizer
# ---------------------------------------------------------------------------


class TestDelegation:
    """Test that DynamicSizer delegates to PositionSizer."""

    def test_delegates_to_position_sizer(
        self,
        sizing_settings: DynamicSizingSettings,
        trading_settings: TradingSettings,
        spot_instrument: InstrumentInfo,
        perp_instrument: InstrumentInfo,
    ) -> None:
        """SIZE-03: calculate_matching_quantity calls PositionSizer.calculate_matching_quantity."""
        mock_sizer = MagicMock(spec=PositionSizer)
        mock_sizer.calculate_matching_quantity.return_value = Decimal("0.010")

        ds = DynamicSizer(
            position_sizer=mock_sizer,
            settings=sizing_settings,
            max_position_size_usd=trading_settings.max_position_size_usd,
        )
        result = ds.calculate_matching_quantity(
            signal_score=Decimal("0.8"),
            current_exposure=Decimal("0"),
            price=Decimal("50000"),
            available_balance=Decimal("10000"),
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )
        mock_sizer.calculate_matching_quantity.assert_called_once()
        assert result == Decimal("0.010")

    def test_returns_none_when_budget_none(
        self,
        sizing_settings: DynamicSizingSettings,
        trading_settings: TradingSettings,
        spot_instrument: InstrumentInfo,
        perp_instrument: InstrumentInfo,
    ) -> None:
        """When exposure >= cap, returns None WITHOUT calling PositionSizer."""
        mock_sizer = MagicMock(spec=PositionSizer)

        ds = DynamicSizer(
            position_sizer=mock_sizer,
            settings=sizing_settings,
            max_position_size_usd=trading_settings.max_position_size_usd,
        )
        result = ds.calculate_matching_quantity(
            signal_score=Decimal("1.0"),
            current_exposure=Decimal("5000"),  # At cap
            price=Decimal("50000"),
            available_balance=Decimal("10000"),
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )
        assert result is None
        mock_sizer.calculate_matching_quantity.assert_not_called()

    def test_effective_balance_is_min_of_balance_and_budget(
        self,
        sizing_settings: DynamicSizingSettings,
        trading_settings: TradingSettings,
        spot_instrument: InstrumentInfo,
        perp_instrument: InstrumentInfo,
    ) -> None:
        """Effective balance passed to PositionSizer is min(available_balance, budget)."""
        mock_sizer = MagicMock(spec=PositionSizer)
        mock_sizer.calculate_matching_quantity.return_value = Decimal("0.005")

        ds = DynamicSizer(
            position_sizer=mock_sizer,
            settings=sizing_settings,
            max_position_size_usd=trading_settings.max_position_size_usd,
        )
        # score=0.5 -> fraction=0.65, budget=650
        # available_balance=500 < budget=650 -> effective_balance=500
        ds.calculate_matching_quantity(
            signal_score=Decimal("0.5"),
            current_exposure=Decimal("0"),
            price=Decimal("50000"),
            available_balance=Decimal("500"),
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )
        call_args = mock_sizer.calculate_matching_quantity.call_args
        assert call_args.kwargs["available_balance"] == Decimal("500")

        # Reset mock
        mock_sizer.reset_mock()

        # score=0.5 -> budget=650, available_balance=10000 -> effective=650
        ds.calculate_matching_quantity(
            signal_score=Decimal("0.5"),
            current_exposure=Decimal("0"),
            price=Decimal("50000"),
            available_balance=Decimal("10000"),
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )
        call_args = mock_sizer.calculate_matching_quantity.call_args
        assert call_args.kwargs["available_balance"] == Decimal("650")
