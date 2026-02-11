"""Tests for PaperExecutor simulated order execution.

Verifies:
- Correct fee calculation using spot/perp taker rates
- Slippage applied in correct direction (higher for buys, lower for sells)
- PriceUnavailableError when price is None or stale
- Virtual balance tracking
- is_simulated=True on all results
- Order ID format (paper_{hex})
"""

import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from bot.config import FeeSettings
from bot.exceptions import PriceUnavailableError
from bot.execution.paper_executor import PaperExecutor
from bot.market_data.ticker_service import TickerService
from bot.models import OrderRequest, OrderSide, OrderType


@pytest.fixture
def fee_settings() -> FeeSettings:
    return FeeSettings(
        spot_taker=Decimal("0.001"),
        spot_maker=Decimal("0.001"),
        perp_taker=Decimal("0.00055"),
        perp_maker=Decimal("0.0002"),
    )


@pytest.fixture
def ticker_service() -> TickerService:
    service = TickerService()
    return service


@pytest.fixture
def executor(
    ticker_service: TickerService, fee_settings: FeeSettings
) -> PaperExecutor:
    return PaperExecutor(ticker_service, fee_settings)


@pytest.mark.asyncio
async def test_buy_order_applies_positive_slippage(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """Buy orders should fill at price * (1 + 0.0005) -- slightly higher."""
    await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())

    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        category="spot",
    )
    result = await executor.place_order(request)

    expected_price = Decimal("50000") * Decimal("1.0005")
    assert result.filled_price == expected_price
    assert result.filled_qty == Decimal("1")


@pytest.mark.asyncio
async def test_sell_order_applies_negative_slippage(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """Sell orders should fill at price * (1 - 0.0005) -- slightly lower."""
    await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())

    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        category="linear",
    )
    result = await executor.place_order(request)

    expected_price = Decimal("50000") * Decimal("0.9995")
    assert result.filled_price == expected_price


@pytest.mark.asyncio
async def test_spot_order_uses_spot_taker_fee(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """Spot category orders should use spot_taker fee rate (0.1%)."""
    await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())

    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        category="spot",
    )
    result = await executor.place_order(request)

    # Fee = quantity * fill_price * spot_taker
    fill_price = Decimal("50000") * Decimal("1.0005")
    expected_fee = Decimal("1") * fill_price * Decimal("0.001")
    assert result.fee == expected_fee


@pytest.mark.asyncio
async def test_perp_order_uses_perp_taker_fee(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """Linear category orders should use perp_taker fee rate (0.055%)."""
    await ticker_service.update_price(
        "BTC/USDT:USDT", Decimal("50000"), time.time()
    )

    request = OrderRequest(
        symbol="BTC/USDT:USDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        category="linear",
    )
    result = await executor.place_order(request)

    fill_price = Decimal("50000") * Decimal("0.9995")
    expected_fee = Decimal("1") * fill_price * Decimal("0.00055")
    assert result.fee == expected_fee


@pytest.mark.asyncio
async def test_raises_when_price_is_none(
    executor: PaperExecutor,
) -> None:
    """Should raise PriceUnavailableError when no price is cached."""
    request = OrderRequest(
        symbol="UNKNOWN/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        category="spot",
    )
    with pytest.raises(PriceUnavailableError, match="No price available"):
        await executor.place_order(request)


@pytest.mark.asyncio
async def test_raises_when_price_is_stale(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """Should raise PriceUnavailableError when price is >60s old."""
    stale_time = time.time() - 120  # 2 minutes ago
    await ticker_service.update_price("BTC/USDT", Decimal("50000"), stale_time)

    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        category="spot",
    )
    with pytest.raises(PriceUnavailableError, match="stale"):
        await executor.place_order(request)


@pytest.mark.asyncio
async def test_is_simulated_always_true(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """All paper executor results must have is_simulated=True."""
    await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())

    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        category="spot",
    )
    result = await executor.place_order(request)
    assert result.is_simulated is True


@pytest.mark.asyncio
async def test_order_id_format(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """Paper order IDs should start with 'paper_' and be unique."""
    await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())

    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
        category="spot",
    )
    result1 = await executor.place_order(request)
    result2 = await executor.place_order(request)

    assert result1.order_id.startswith("paper_")
    assert result2.order_id.startswith("paper_")
    assert result1.order_id != result2.order_id


@pytest.mark.asyncio
async def test_virtual_balance_tracking_buy(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """Buying should reduce virtual balance by cost + fee."""
    executor.set_initial_balance("USDT", Decimal("100000"))
    await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())

    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        category="spot",
    )
    result = await executor.place_order(request)

    balances = executor.get_virtual_balance()
    cost = result.filled_qty * result.filled_price + result.fee
    expected = Decimal("100000") - cost
    assert balances["USDT"] == expected


@pytest.mark.asyncio
async def test_virtual_balance_tracking_sell(
    executor: PaperExecutor, ticker_service: TickerService
) -> None:
    """Selling should increase virtual balance by proceeds - fee."""
    executor.set_initial_balance("USDT", Decimal("100000"))
    await ticker_service.update_price("BTC/USDT", Decimal("50000"), time.time())

    request = OrderRequest(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        category="linear",
    )
    result = await executor.place_order(request)

    balances = executor.get_virtual_balance()
    proceeds = result.filled_qty * result.filled_price - result.fee
    expected = Decimal("100000") + proceeds
    assert balances["USDT"] == expected


@pytest.mark.asyncio
async def test_cancel_order_always_true(executor: PaperExecutor) -> None:
    """Paper cancel_order should always return True."""
    result = await executor.cancel_order("paper_abc123", "BTC/USDT")
    assert result is True
