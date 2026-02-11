"""Tests for PositionManager position lifecycle.

Verifies:
- open_position creates position with both legs via mocked executor
- open_position validates delta after fills
- close_position creates reverse orders
- Simultaneous execution via asyncio.gather (both orders placed)
- Position tracking (get_open_positions, get_position)
- Error handling (InsufficientSizeError, DeltaDriftExceeded)
"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config import FeeSettings, TradingSettings
from bot.exceptions import DeltaDriftExceeded, InsufficientSizeError, PriceUnavailableError
from bot.exchange.types import InstrumentInfo
from bot.execution.executor import Executor
from bot.market_data.ticker_service import TickerService
from bot.models import OrderRequest, OrderResult, OrderSide, OrderType, Position
from bot.pnl.fee_calculator import FeeCalculator
from bot.position.delta_validator import DeltaValidator
from bot.position.manager import PositionManager
from bot.position.sizing import PositionSizer


@pytest.fixture
def settings() -> TradingSettings:
    return TradingSettings(
        max_position_size_usd=Decimal("1000"),
        delta_drift_tolerance=Decimal("0.02"),
        order_timeout_seconds=5.0,
    )


@pytest.fixture
def fee_settings() -> FeeSettings:
    return FeeSettings()


@pytest.fixture
def mock_executor() -> AsyncMock:
    executor = AsyncMock(spec=Executor)
    return executor


@pytest.fixture
def ticker_service() -> TickerService:
    return TickerService()


@pytest.fixture
def position_sizer(settings: TradingSettings) -> PositionSizer:
    return PositionSizer(settings)


@pytest.fixture
def fee_calculator(fee_settings: FeeSettings) -> FeeCalculator:
    return FeeCalculator(fee_settings)


@pytest.fixture
def delta_validator(settings: TradingSettings) -> DeltaValidator:
    return DeltaValidator(settings)


@pytest.fixture
def spot_instrument() -> InstrumentInfo:
    return InstrumentInfo(
        symbol="BTC/USDT",
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        qty_step=Decimal("0.001"),
        min_notional=Decimal("10"),
    )


@pytest.fixture
def perp_instrument() -> InstrumentInfo:
    return InstrumentInfo(
        symbol="BTC/USDT:USDT",
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        qty_step=Decimal("0.001"),
        min_notional=Decimal("10"),
    )


def _make_order_result(
    symbol: str,
    side: OrderSide,
    qty: Decimal = Decimal("0.02"),
    price: Decimal = Decimal("50000"),
    fee: Decimal = Decimal("1"),
    is_simulated: bool = True,
) -> OrderResult:
    """Create a mock OrderResult for testing."""
    return OrderResult(
        order_id=f"test_{side.value}_{symbol[:3]}",
        symbol=symbol,
        side=side,
        filled_qty=qty,
        filled_price=price,
        fee=fee,
        timestamp=time.time(),
        is_simulated=is_simulated,
    )


@pytest.fixture
def manager(
    mock_executor: AsyncMock,
    position_sizer: PositionSizer,
    fee_calculator: FeeCalculator,
    delta_validator: DeltaValidator,
    ticker_service: TickerService,
    settings: TradingSettings,
) -> PositionManager:
    return PositionManager(
        executor=mock_executor,
        position_sizer=position_sizer,
        fee_calculator=fee_calculator,
        delta_validator=delta_validator,
        ticker_service=ticker_service,
        settings=settings,
    )


@pytest.mark.asyncio
async def test_open_position_creates_both_legs(
    manager: PositionManager,
    mock_executor: AsyncMock,
    ticker_service: TickerService,
    spot_instrument: InstrumentInfo,
    perp_instrument: InstrumentInfo,
) -> None:
    """open_position should place spot BUY and perp SELL orders."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    spot_result = _make_order_result("BTC/USDT", OrderSide.BUY)
    perp_result = _make_order_result("BTC/USDT:USDT", OrderSide.SELL)
    mock_executor.place_order.side_effect = [spot_result, perp_result]

    position = await manager.open_position(
        spot_symbol="BTC/USDT",
        perp_symbol="BTC/USDT:USDT",
        available_balance=Decimal("10000"),
        spot_instrument=spot_instrument,
        perp_instrument=perp_instrument,
    )

    assert mock_executor.place_order.call_count == 2
    assert position.spot_symbol == "BTC/USDT"
    assert position.perp_symbol == "BTC/USDT:USDT"
    assert position.quantity == Decimal("0.02")


@pytest.mark.asyncio
async def test_open_position_spot_buy_perp_sell(
    manager: PositionManager,
    mock_executor: AsyncMock,
    ticker_service: TickerService,
    spot_instrument: InstrumentInfo,
    perp_instrument: InstrumentInfo,
) -> None:
    """Spot order should be BUY, perp order should be SELL."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    spot_result = _make_order_result("BTC/USDT", OrderSide.BUY)
    perp_result = _make_order_result("BTC/USDT:USDT", OrderSide.SELL)
    mock_executor.place_order.side_effect = [spot_result, perp_result]

    await manager.open_position(
        spot_symbol="BTC/USDT",
        perp_symbol="BTC/USDT:USDT",
        available_balance=Decimal("10000"),
        spot_instrument=spot_instrument,
        perp_instrument=perp_instrument,
    )

    calls = mock_executor.place_order.call_args_list
    spot_order: OrderRequest = calls[0][0][0]
    perp_order: OrderRequest = calls[1][0][0]

    assert spot_order.side == OrderSide.BUY
    assert spot_order.category == "spot"
    assert perp_order.side == OrderSide.SELL
    assert perp_order.category == "linear"


@pytest.mark.asyncio
async def test_open_position_validates_delta(
    manager: PositionManager,
    mock_executor: AsyncMock,
    ticker_service: TickerService,
    spot_instrument: InstrumentInfo,
    perp_instrument: InstrumentInfo,
) -> None:
    """open_position should validate delta and accept fills within tolerance."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    # Both legs fill with same quantity -> zero drift
    spot_result = _make_order_result("BTC/USDT", OrderSide.BUY, qty=Decimal("0.02"))
    perp_result = _make_order_result("BTC/USDT:USDT", OrderSide.SELL, qty=Decimal("0.02"))
    mock_executor.place_order.side_effect = [spot_result, perp_result]

    position = await manager.open_position(
        spot_symbol="BTC/USDT",
        perp_symbol="BTC/USDT:USDT",
        available_balance=Decimal("10000"),
        spot_instrument=spot_instrument,
        perp_instrument=perp_instrument,
    )

    # Position should be created successfully
    assert position is not None
    assert len(manager.get_open_positions()) == 1


@pytest.mark.asyncio
async def test_open_position_rejects_excessive_drift(
    manager: PositionManager,
    mock_executor: AsyncMock,
    ticker_service: TickerService,
    spot_instrument: InstrumentInfo,
    perp_instrument: InstrumentInfo,
) -> None:
    """open_position should raise DeltaDriftExceeded when fills drift >2%."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    # 5% drift: spot fills 0.02, perp fills 0.019 -> drift = 0.001/0.02 = 5%
    spot_result = _make_order_result("BTC/USDT", OrderSide.BUY, qty=Decimal("0.020"))
    perp_result = _make_order_result("BTC/USDT:USDT", OrderSide.SELL, qty=Decimal("0.019"))
    mock_executor.place_order.side_effect = [
        spot_result,
        perp_result,
        # Close legs after drift detection (emergency close)
        _make_order_result("BTC/USDT", OrderSide.SELL),
        _make_order_result("BTC/USDT:USDT", OrderSide.BUY),
    ]

    with pytest.raises(DeltaDriftExceeded):
        await manager.open_position(
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            available_balance=Decimal("10000"),
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )

    # Position should NOT be stored
    assert len(manager.get_open_positions()) == 0


@pytest.mark.asyncio
async def test_close_position_creates_reverse_orders(
    manager: PositionManager,
    mock_executor: AsyncMock,
    ticker_service: TickerService,
    spot_instrument: InstrumentInfo,
    perp_instrument: InstrumentInfo,
) -> None:
    """close_position should create spot SELL and perp BUY orders."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    # Open position first
    spot_result = _make_order_result("BTC/USDT", OrderSide.BUY)
    perp_result = _make_order_result("BTC/USDT:USDT", OrderSide.SELL)
    mock_executor.place_order.side_effect = [spot_result, perp_result]

    position = await manager.open_position(
        spot_symbol="BTC/USDT",
        perp_symbol="BTC/USDT:USDT",
        available_balance=Decimal("10000"),
        spot_instrument=spot_instrument,
        perp_instrument=perp_instrument,
    )

    # Set up close order results
    close_spot = _make_order_result("BTC/USDT", OrderSide.SELL)
    close_perp = _make_order_result("BTC/USDT:USDT", OrderSide.BUY)
    mock_executor.place_order.side_effect = [close_spot, close_perp]

    spot_close_result, perp_close_result = await manager.close_position(
        position.id
    )

    # Verify reverse order sides
    close_calls = mock_executor.place_order.call_args_list[2:]  # Skip open calls
    close_spot_order: OrderRequest = close_calls[0][0][0]
    close_perp_order: OrderRequest = close_calls[1][0][0]

    assert close_spot_order.side == OrderSide.SELL
    assert close_spot_order.category == "spot"
    assert close_perp_order.side == OrderSide.BUY
    assert close_perp_order.category == "linear"

    # Position should be removed
    assert len(manager.get_open_positions()) == 0


@pytest.mark.asyncio
async def test_simultaneous_execution(
    manager: PositionManager,
    mock_executor: AsyncMock,
    ticker_service: TickerService,
    spot_instrument: InstrumentInfo,
    perp_instrument: InstrumentInfo,
) -> None:
    """Both spot and perp orders should be placed (verifying gather call)."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    spot_result = _make_order_result("BTC/USDT", OrderSide.BUY)
    perp_result = _make_order_result("BTC/USDT:USDT", OrderSide.SELL)
    mock_executor.place_order.side_effect = [spot_result, perp_result]

    position = await manager.open_position(
        spot_symbol="BTC/USDT",
        perp_symbol="BTC/USDT:USDT",
        available_balance=Decimal("10000"),
        spot_instrument=spot_instrument,
        perp_instrument=perp_instrument,
    )

    # Both orders must have been placed
    assert mock_executor.place_order.call_count == 2

    # Position should store both order IDs
    assert position.spot_order_id == spot_result.order_id
    assert position.perp_order_id == perp_result.order_id


@pytest.mark.asyncio
async def test_position_entry_fee_total(
    manager: PositionManager,
    mock_executor: AsyncMock,
    ticker_service: TickerService,
    spot_instrument: InstrumentInfo,
    perp_instrument: InstrumentInfo,
) -> None:
    """Entry fee should be sum of spot and perp fees."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    spot_result = _make_order_result(
        "BTC/USDT", OrderSide.BUY, fee=Decimal("5.00")
    )
    perp_result = _make_order_result(
        "BTC/USDT:USDT", OrderSide.SELL, fee=Decimal("2.75")
    )
    mock_executor.place_order.side_effect = [spot_result, perp_result]

    position = await manager.open_position(
        spot_symbol="BTC/USDT",
        perp_symbol="BTC/USDT:USDT",
        available_balance=Decimal("10000"),
        spot_instrument=spot_instrument,
        perp_instrument=perp_instrument,
    )

    assert position.entry_fee_total == Decimal("7.75")


@pytest.mark.asyncio
async def test_insufficient_size_raises_error(
    manager: PositionManager,
    mock_executor: AsyncMock,
    ticker_service: TickerService,
) -> None:
    """Should raise InsufficientSizeError when quantity is below minimums."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    # Very high min_qty that balance cannot reach
    spot_instrument = InstrumentInfo(
        symbol="BTC/USDT",
        min_qty=Decimal("100"),
        max_qty=Decimal("1000"),
        qty_step=Decimal("0.001"),
        min_notional=Decimal("10"),
    )
    perp_instrument = InstrumentInfo(
        symbol="BTC/USDT:USDT",
        min_qty=Decimal("100"),
        max_qty=Decimal("1000"),
        qty_step=Decimal("0.001"),
        min_notional=Decimal("10"),
    )

    with pytest.raises(InsufficientSizeError):
        await manager.open_position(
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            available_balance=Decimal("1000"),
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )


@pytest.mark.asyncio
async def test_price_unavailable_raises_error(
    manager: PositionManager,
    mock_executor: AsyncMock,
    spot_instrument: InstrumentInfo,
    perp_instrument: InstrumentInfo,
) -> None:
    """Should raise PriceUnavailableError when no price is cached."""
    with pytest.raises(PriceUnavailableError):
        await manager.open_position(
            spot_symbol="BTC/USDT",
            perp_symbol="BTC/USDT:USDT",
            available_balance=Decimal("10000"),
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )


@pytest.mark.asyncio
async def test_get_position_returns_none_for_unknown(
    manager: PositionManager,
) -> None:
    """get_position should return None for non-existent position ID."""
    assert manager.get_position("nonexistent") is None


@pytest.mark.asyncio
async def test_get_open_positions_empty(
    manager: PositionManager,
) -> None:
    """get_open_positions should return empty list when no positions."""
    assert manager.get_open_positions() == []
