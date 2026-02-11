"""Tests for DeltaValidator delta neutrality checking.

Verifies:
- Equal quantities -> within tolerance, drift=0
- Small drift (1%) -> within 2% tolerance
- Large drift (3%) -> exceeds 2% tolerance
- Zero quantities -> handled gracefully
- validate_position wraps validate with position ID
"""

import time
from decimal import Decimal

import pytest

from bot.config import TradingSettings
from bot.models import DeltaStatus, Position, PositionSide
from bot.position.delta_validator import DeltaValidator


@pytest.fixture
def settings() -> TradingSettings:
    return TradingSettings(delta_drift_tolerance=Decimal("0.02"))


@pytest.fixture
def validator(settings: TradingSettings) -> DeltaValidator:
    return DeltaValidator(settings)


def test_equal_quantities_zero_drift(validator: DeltaValidator) -> None:
    """Equal spot and perp quantities should have zero drift."""
    status = validator.validate(
        spot_qty=Decimal("1.0"),
        perp_qty=Decimal("1.0"),
    )
    assert status.drift_pct == Decimal("0")
    assert status.is_within_tolerance is True


def test_one_percent_drift_within_tolerance(validator: DeltaValidator) -> None:
    """1% drift should be within 2% tolerance."""
    # spot=1.0, perp=0.99 -> drift = 0.01/1.0 = 1%
    status = validator.validate(
        spot_qty=Decimal("1.0"),
        perp_qty=Decimal("0.99"),
    )
    assert status.drift_pct == Decimal("0.01")
    assert status.is_within_tolerance is True


def test_two_percent_drift_at_boundary(validator: DeltaValidator) -> None:
    """2% drift should be exactly at tolerance (within)."""
    status = validator.validate(
        spot_qty=Decimal("1.0"),
        perp_qty=Decimal("0.98"),
    )
    assert status.drift_pct == Decimal("0.02")
    assert status.is_within_tolerance is True


def test_three_percent_drift_exceeds_tolerance(validator: DeltaValidator) -> None:
    """3% drift should exceed 2% tolerance."""
    # spot=1.0, perp=0.97 -> drift = 0.03/1.0 = 3%
    status = validator.validate(
        spot_qty=Decimal("1.0"),
        perp_qty=Decimal("0.97"),
    )
    assert status.drift_pct == Decimal("0.03")
    assert status.is_within_tolerance is False


def test_zero_quantities_handled_gracefully(validator: DeltaValidator) -> None:
    """Both quantities zero should result in zero drift, within tolerance."""
    status = validator.validate(
        spot_qty=Decimal("0"),
        perp_qty=Decimal("0"),
    )
    assert status.drift_pct == Decimal("0")
    assert status.is_within_tolerance is True


def test_one_zero_quantity(validator: DeltaValidator) -> None:
    """One zero and one non-zero should show 100% drift (exceeds tolerance)."""
    status = validator.validate(
        spot_qty=Decimal("1.0"),
        perp_qty=Decimal("0"),
    )
    assert status.drift_pct == Decimal("1")
    assert status.is_within_tolerance is False


def test_validate_returns_delta_status(validator: DeltaValidator) -> None:
    """validate() should return a DeltaStatus with all fields populated."""
    status = validator.validate(
        spot_qty=Decimal("10"),
        perp_qty=Decimal("9.5"),
        position_id="test-pos-1",
    )
    assert isinstance(status, DeltaStatus)
    assert status.position_id == "test-pos-1"
    assert status.spot_qty == Decimal("10")
    assert status.perp_qty == Decimal("9.5")
    assert status.checked_at > 0


def test_validate_position_uses_position_id(
    validator: DeltaValidator,
) -> None:
    """validate_position() should populate position_id from the Position."""
    position = Position(
        id="pos-abc",
        spot_symbol="BTC/USDT",
        perp_symbol="BTC/USDT:USDT",
        side=PositionSide.SHORT,
        quantity=Decimal("1"),
        spot_entry_price=Decimal("50000"),
        perp_entry_price=Decimal("50000"),
        spot_order_id="spot-1",
        perp_order_id="perp-1",
        opened_at=time.time(),
        entry_fee_total=Decimal("10"),
    )
    status = validator.validate_position(
        position=position,
        current_spot_qty=Decimal("1"),
        current_perp_qty=Decimal("1"),
    )
    assert status.position_id == "pos-abc"
    assert status.is_within_tolerance is True


def test_perp_larger_than_spot(validator: DeltaValidator) -> None:
    """Drift calculation should work when perp > spot too."""
    status = validator.validate(
        spot_qty=Decimal("0.97"),
        perp_qty=Decimal("1.0"),
    )
    assert status.drift_pct == Decimal("0.03")
    assert status.is_within_tolerance is False
