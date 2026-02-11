"""Tests for RiskManager -- pre-trade checks and margin monitoring.

Covers RISK-01 (per-pair size), RISK-02 (max positions), RISK-05 (margin),
duplicate pair prevention, and zero/negative size rejection.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import RiskSettings
from bot.models import Position, PositionSide
from bot.risk.manager import RiskManager


def _make_position(perp_symbol: str = "BTC/USDT:USDT", **kwargs) -> Position:
    """Create a minimal Position for testing."""
    defaults = dict(
        id="pos-1",
        spot_symbol="BTC/USDT",
        perp_symbol=perp_symbol,
        side=PositionSide.SHORT,
        quantity=Decimal("0.01"),
        spot_entry_price=Decimal("50000"),
        perp_entry_price=Decimal("50010"),
        spot_order_id="s-1",
        perp_order_id="p-1",
        opened_at=1000.0,
        entry_fee_total=Decimal("1.50"),
    )
    defaults.update(kwargs)
    return Position(**defaults)


@pytest.fixture()
def settings() -> RiskSettings:
    return RiskSettings(
        max_position_size_per_pair=Decimal("1000"),
        max_simultaneous_positions=3,
        margin_alert_threshold=Decimal("0.8"),
        margin_critical_threshold=Decimal("0.9"),
    )


@pytest.fixture()
def risk_manager(settings: RiskSettings) -> RiskManager:
    return RiskManager(settings=settings)


# ---- check_can_open tests ----


class TestCheckCanOpen:
    """Tests for RiskManager.check_can_open."""

    def test_allows_valid_position(self, risk_manager: RiskManager) -> None:
        allowed, reason = risk_manager.check_can_open(
            symbol="ETH/USDT:USDT",
            position_size_usd=Decimal("500"),
            current_positions=[],
        )
        assert allowed is True
        assert reason == ""

    def test_rejects_exceeding_max_per_pair_size(
        self, risk_manager: RiskManager
    ) -> None:
        allowed, reason = risk_manager.check_can_open(
            symbol="ETH/USDT:USDT",
            position_size_usd=Decimal("1500"),
            current_positions=[],
        )
        assert allowed is False
        assert "max per-pair size" in reason.lower()

    def test_rejects_exact_max_per_pair_boundary(
        self, risk_manager: RiskManager
    ) -> None:
        """Size exactly at max is allowed (not exceeding)."""
        allowed, reason = risk_manager.check_can_open(
            symbol="ETH/USDT:USDT",
            position_size_usd=Decimal("1000"),
            current_positions=[],
        )
        assert allowed is True
        assert reason == ""

    def test_rejects_at_max_simultaneous_positions(
        self, risk_manager: RiskManager
    ) -> None:
        positions = [
            _make_position(perp_symbol=f"COIN{i}/USDT:USDT", id=f"pos-{i}")
            for i in range(3)
        ]
        allowed, reason = risk_manager.check_can_open(
            symbol="NEW/USDT:USDT",
            position_size_usd=Decimal("500"),
            current_positions=positions,
        )
        assert allowed is False
        assert "max positions" in reason.lower()

    def test_rejects_duplicate_symbol(self, risk_manager: RiskManager) -> None:
        positions = [_make_position(perp_symbol="BTC/USDT:USDT")]
        allowed, reason = risk_manager.check_can_open(
            symbol="BTC/USDT:USDT",
            position_size_usd=Decimal("500"),
            current_positions=positions,
        )
        assert allowed is False
        assert "already have position" in reason.lower()

    def test_rejects_zero_size(self, risk_manager: RiskManager) -> None:
        allowed, reason = risk_manager.check_can_open(
            symbol="ETH/USDT:USDT",
            position_size_usd=Decimal("0"),
            current_positions=[],
        )
        assert allowed is False
        assert "positive" in reason.lower()

    def test_rejects_negative_size(self, risk_manager: RiskManager) -> None:
        allowed, reason = risk_manager.check_can_open(
            symbol="ETH/USDT:USDT",
            position_size_usd=Decimal("-100"),
            current_positions=[],
        )
        assert allowed is False
        assert "positive" in reason.lower()


# ---- check_margin_ratio tests ----


class TestCheckMarginRatio:
    """Tests for RiskManager.check_margin_ratio."""

    @pytest.mark.asyncio()
    async def test_returns_ratio_and_alert_from_exchange(
        self, settings: RiskSettings
    ) -> None:
        mock_client = AsyncMock()
        mock_client.fetch_wallet_balance_raw.return_value = {
            "accountMMRate": "0.5",
            "totalEquity": "10000",
        }
        rm = RiskManager(settings=settings, exchange_client=mock_client)

        mm_rate, is_alert = await rm.check_margin_ratio()
        assert mm_rate == Decimal("0.5")
        assert is_alert is False
        mock_client.fetch_wallet_balance_raw.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_alerts_when_above_threshold(
        self, settings: RiskSettings
    ) -> None:
        mock_client = AsyncMock()
        mock_client.fetch_wallet_balance_raw.return_value = {
            "accountMMRate": "0.85",
        }
        rm = RiskManager(settings=settings, exchange_client=mock_client)

        mm_rate, is_alert = await rm.check_margin_ratio()
        assert mm_rate == Decimal("0.85")
        assert is_alert is True

    @pytest.mark.asyncio()
    async def test_uses_paper_margin_fn_when_no_exchange(
        self, settings: RiskSettings
    ) -> None:
        paper_fn = MagicMock(return_value={"accountMMRate": "0.3"})
        rm = RiskManager(settings=settings, paper_margin_fn=paper_fn)

        mm_rate, is_alert = await rm.check_margin_ratio()
        assert mm_rate == Decimal("0.3")
        assert is_alert is False
        paper_fn.assert_called_once()

    @pytest.mark.asyncio()
    async def test_returns_zero_when_no_client_or_fn(
        self, settings: RiskSettings
    ) -> None:
        rm = RiskManager(settings=settings)

        mm_rate, is_alert = await rm.check_margin_ratio()
        assert mm_rate == Decimal("0")
        assert is_alert is False


# ---- is_margin_critical tests ----


class TestIsMarginCritical:
    """Tests for RiskManager.is_margin_critical."""

    def test_returns_true_above_critical(
        self, risk_manager: RiskManager
    ) -> None:
        assert risk_manager.is_margin_critical(Decimal("0.95")) is True

    def test_returns_true_at_critical(
        self, risk_manager: RiskManager
    ) -> None:
        assert risk_manager.is_margin_critical(Decimal("0.9")) is True

    def test_returns_false_below_critical(
        self, risk_manager: RiskManager
    ) -> None:
        assert risk_manager.is_margin_critical(Decimal("0.85")) is False
