"""Tests for EmergencyController -- concurrent close-all with retry logic.

Covers successful close, partial failure, empty positions, double trigger,
and retry backoff scenarios.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.models import OrderResult, OrderSide, Position, PositionSide
from bot.risk.emergency import EmergencyController


def _make_position(
    position_id: str = "pos-1",
    perp_symbol: str = "BTC/USDT:USDT",
) -> Position:
    """Create a minimal Position for testing."""
    return Position(
        id=position_id,
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


def _make_order_result(
    symbol: str = "BTC/USDT",
    side: OrderSide = OrderSide.SELL,
) -> OrderResult:
    """Create a minimal OrderResult for testing."""
    return OrderResult(
        order_id="ord-1",
        symbol=symbol,
        side=side,
        filled_qty=Decimal("0.01"),
        filled_price=Decimal("50050"),
        fee=Decimal("0.50"),
        timestamp=1001.0,
        is_simulated=True,
    )


@pytest.fixture()
def position_manager() -> AsyncMock:
    pm = AsyncMock()
    pm.get_open_positions = MagicMock(return_value=[])
    pm.close_position = AsyncMock(
        return_value=(
            _make_order_result(side=OrderSide.SELL),
            _make_order_result(side=OrderSide.BUY),
        )
    )
    return pm


@pytest.fixture()
def pnl_tracker() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def stop_callback() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def controller(
    position_manager: AsyncMock,
    pnl_tracker: MagicMock,
    stop_callback: AsyncMock,
) -> EmergencyController:
    return EmergencyController(
        position_manager=position_manager,
        pnl_tracker=pnl_tracker,
        stop_callback=stop_callback,
        max_retries=3,
    )


class TestEmergencyTrigger:
    """Tests for EmergencyController.trigger."""

    @pytest.mark.asyncio()
    async def test_closes_all_positions_successfully(
        self,
        controller: EmergencyController,
        position_manager: AsyncMock,
        pnl_tracker: MagicMock,
        stop_callback: AsyncMock,
    ) -> None:
        pos1 = _make_position("pos-1", "BTC/USDT:USDT")
        pos2 = _make_position("pos-2", "ETH/USDT:USDT")
        position_manager.get_open_positions.return_value = [pos1, pos2]

        closed, failed = await controller.trigger("test emergency")

        assert closed == ["pos-1", "pos-2"]
        assert failed == []
        assert position_manager.close_position.await_count == 2
        assert pnl_tracker.record_close.call_count == 2
        stop_callback.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_one_position_fails_all_retries(
        self,
        controller: EmergencyController,
        position_manager: AsyncMock,
        stop_callback: AsyncMock,
    ) -> None:
        pos1 = _make_position("pos-1", "BTC/USDT:USDT")
        pos2 = _make_position("pos-2", "ETH/USDT:USDT")
        position_manager.get_open_positions.return_value = [pos1, pos2]

        # pos-1 succeeds, pos-2 always fails
        close_results = {
            "pos-1": (
                _make_order_result(side=OrderSide.SELL),
                _make_order_result(side=OrderSide.BUY),
            ),
        }

        async def mock_close(pid: str):
            if pid in close_results:
                return close_results[pid]
            raise RuntimeError(f"Exchange error closing {pid}")

        position_manager.close_position.side_effect = mock_close

        with patch("bot.risk.emergency.asyncio.sleep", new_callable=AsyncMock):
            closed, failed = await controller.trigger("test partial failure")

        assert closed == ["pos-1"]
        assert failed == ["pos-2"]
        stop_callback.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_calls_stop_callback(
        self,
        controller: EmergencyController,
        position_manager: AsyncMock,
        stop_callback: AsyncMock,
    ) -> None:
        pos = _make_position()
        position_manager.get_open_positions.return_value = [pos]

        await controller.trigger("stop test")

        stop_callback.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_empty_positions_calls_stop(
        self,
        controller: EmergencyController,
        position_manager: AsyncMock,
        stop_callback: AsyncMock,
    ) -> None:
        position_manager.get_open_positions.return_value = []

        closed, failed = await controller.trigger("no positions")

        assert closed == []
        assert failed == []
        position_manager.close_position.assert_not_awaited()
        stop_callback.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_double_trigger_returns_early(
        self,
        controller: EmergencyController,
        position_manager: AsyncMock,
        stop_callback: AsyncMock,
    ) -> None:
        pos = _make_position()
        position_manager.get_open_positions.return_value = [pos]

        await controller.trigger("first")
        # Reset mock to track second call
        stop_callback.reset_mock()
        position_manager.close_position.reset_mock()

        closed, failed = await controller.trigger("second")

        assert closed == []
        assert failed == []
        position_manager.close_position.assert_not_awaited()
        stop_callback.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_retry_backoff_then_succeed(
        self,
        controller: EmergencyController,
        position_manager: AsyncMock,
        pnl_tracker: MagicMock,
    ) -> None:
        pos = _make_position()
        position_manager.get_open_positions.return_value = [pos]

        # Fail twice, succeed on third attempt
        success_result = (
            _make_order_result(side=OrderSide.SELL),
            _make_order_result(side=OrderSide.BUY),
        )
        position_manager.close_position.side_effect = [
            RuntimeError("fail 1"),
            RuntimeError("fail 2"),
            success_result,
        ]

        with patch(
            "bot.risk.emergency.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            closed, failed = await controller.trigger("retry test")

        assert closed == ["pos-1"]
        assert failed == []
        # Should have slept twice (after attempt 1 and 2)
        assert mock_sleep.await_count == 2
        # Linear backoff: sleep(1*1), sleep(1*2)
        mock_sleep.assert_any_await(1)
        mock_sleep.assert_any_await(2)
        pnl_tracker.record_close.assert_called_once()


class TestEmergencyProperties:
    """Tests for EmergencyController properties and reset."""

    def test_triggered_initially_false(
        self, controller: EmergencyController
    ) -> None:
        assert controller.triggered is False

    @pytest.mark.asyncio()
    async def test_triggered_after_trigger(
        self,
        controller: EmergencyController,
        position_manager: AsyncMock,
    ) -> None:
        position_manager.get_open_positions.return_value = []
        await controller.trigger("test")
        assert controller.triggered is True

    def test_reset(self, controller: EmergencyController) -> None:
        controller._triggered = True
        controller.reset()
        assert controller.triggered is False
