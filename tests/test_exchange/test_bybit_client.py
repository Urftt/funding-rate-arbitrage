"""Tests for BybitClient and exchange types.

All tests use mocked ccxt exchange objects to avoid real API calls.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config import ExchangeSettings
from bot.exchange.bybit_client import BybitClient
from bot.exchange.types import InstrumentInfo, round_to_step


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_MARKETS = {
    "BTC/USDT:USDT": {
        "id": "BTCUSDT",
        "symbol": "BTC/USDT:USDT",
        "base": "BTC",
        "quote": "USDT",
        "settle": "USDT",
        "type": "swap",
        "spot": False,
        "swap": True,
        "linear": True,
        "inverse": False,
        "limits": {
            "amount": {"min": 0.001, "max": 100},
            "cost": {"min": 5, "max": None},
        },
        "precision": {
            "amount": 0.001,
            "price": 0.1,
        },
    },
    "ETH/USDT:USDT": {
        "id": "ETHUSDT",
        "symbol": "ETH/USDT:USDT",
        "base": "ETH",
        "quote": "USDT",
        "settle": "USDT",
        "type": "swap",
        "spot": False,
        "swap": True,
        "linear": True,
        "inverse": False,
        "limits": {
            "amount": {"min": 0.01, "max": 1000},
            "cost": {"min": 1, "max": None},
        },
        "precision": {
            "amount": 0.01,
            "price": 0.01,
        },
    },
    "BTC/USDT": {
        "id": "BTCUSDT",
        "symbol": "BTC/USDT",
        "base": "BTC",
        "quote": "USDT",
        "type": "spot",
        "spot": True,
        "swap": False,
        "linear": False,
        "inverse": False,
        "limits": {
            "amount": {"min": 0.00001, "max": 100},
            "cost": {"min": 1, "max": None},
        },
        "precision": {
            "amount": 0.00001,
            "price": 0.01,
        },
    },
    "BTC/USD:BTC": {
        "id": "BTCUSD",
        "symbol": "BTC/USD:BTC",
        "base": "BTC",
        "quote": "USD",
        "settle": "BTC",
        "type": "swap",
        "spot": False,
        "swap": True,
        "linear": False,
        "inverse": True,
        "limits": {
            "amount": {"min": 1, "max": 1000000},
            "cost": {"min": None, "max": None},
        },
        "precision": {
            "amount": 1,
            "price": 0.5,
        },
    },
}


@pytest.fixture
def exchange_settings() -> ExchangeSettings:
    """Exchange settings for testing."""
    return ExchangeSettings(
        api_key="test-key",  # type: ignore[arg-type]
        api_secret="test-secret",  # type: ignore[arg-type]
        testnet=False,
        demo_trading=False,
    )


@pytest.fixture
def demo_settings() -> ExchangeSettings:
    """Exchange settings with demo trading enabled."""
    return ExchangeSettings(
        api_key="test-key",  # type: ignore[arg-type]
        api_secret="test-secret",  # type: ignore[arg-type]
        testnet=False,
        demo_trading=True,
    )


@pytest.fixture
def bybit_client(exchange_settings: ExchangeSettings) -> BybitClient:
    """BybitClient with mocked markets pre-loaded."""
    client = BybitClient(exchange_settings)
    client._markets = MOCK_MARKETS
    return client


# ---------------------------------------------------------------------------
# round_to_step tests
# ---------------------------------------------------------------------------


class TestRoundToStep:
    """Tests for the round_to_step helper function."""

    def test_round_down_to_hundredths(self) -> None:
        assert round_to_step(Decimal("1.2345"), Decimal("0.01")) == Decimal("1.23")

    def test_round_down_to_ones(self) -> None:
        assert round_to_step(Decimal("100.7"), Decimal("1")) == Decimal("100")

    def test_exact_step_unchanged(self) -> None:
        assert round_to_step(Decimal("0.005"), Decimal("0.001")) == Decimal("0.005")

    def test_round_down_to_thousandths(self) -> None:
        assert round_to_step(Decimal("0.1999"), Decimal("0.001")) == Decimal("0.199")

    def test_large_step(self) -> None:
        assert round_to_step(Decimal("17"), Decimal("5")) == Decimal("15")

    def test_zero_value(self) -> None:
        assert round_to_step(Decimal("0"), Decimal("0.01")) == Decimal("0")

    def test_value_less_than_step(self) -> None:
        assert round_to_step(Decimal("0.005"), Decimal("0.01")) == Decimal("0.00")


# ---------------------------------------------------------------------------
# InstrumentInfo tests
# ---------------------------------------------------------------------------


class TestInstrumentInfo:
    """Tests for InstrumentInfo dataclass."""

    def test_create_instrument_info(self) -> None:
        info = InstrumentInfo(
            symbol="BTC/USDT:USDT",
            min_qty=Decimal("0.001"),
            max_qty=Decimal("100"),
            qty_step=Decimal("0.001"),
            min_notional=Decimal("5"),
            tick_size=Decimal("0.1"),
        )
        assert info.symbol == "BTC/USDT:USDT"
        assert info.min_qty == Decimal("0.001")
        assert info.tick_size == Decimal("0.1")

    def test_instrument_info_defaults(self) -> None:
        info = InstrumentInfo(
            symbol="TEST/USDT",
            min_qty=Decimal("0.01"),
            max_qty=Decimal("100"),
            qty_step=Decimal("0.01"),
        )
        # Default values should be applied
        assert info.min_notional == Decimal("0")
        assert info.tick_size == Decimal("0.01")


# ---------------------------------------------------------------------------
# BybitClient tests
# ---------------------------------------------------------------------------


class TestBybitClientInit:
    """Tests for BybitClient initialization."""

    def test_demo_trading_overrides_urls(self, demo_settings: ExchangeSettings) -> None:
        client = BybitClient(demo_settings)
        exchange = client.exchange
        # Demo trading should override the API URLs
        urls = exchange.urls
        assert "api-demo.bybit.com" in str(urls)

    def test_standard_init(self, exchange_settings: ExchangeSettings) -> None:
        client = BybitClient(exchange_settings)
        assert client.exchange.enableRateLimit is True


class TestFetchPerpetualSymbols:
    """Tests for fetch_perpetual_symbols filtering."""

    @pytest.mark.asyncio
    async def test_returns_only_linear_swaps(self, bybit_client: BybitClient) -> None:
        symbols = await bybit_client.fetch_perpetual_symbols()
        assert "BTC/USDT:USDT" in symbols
        assert "ETH/USDT:USDT" in symbols

    @pytest.mark.asyncio
    async def test_excludes_spot(self, bybit_client: BybitClient) -> None:
        symbols = await bybit_client.fetch_perpetual_symbols()
        assert "BTC/USDT" not in symbols

    @pytest.mark.asyncio
    async def test_excludes_inverse(self, bybit_client: BybitClient) -> None:
        symbols = await bybit_client.fetch_perpetual_symbols()
        assert "BTC/USD:BTC" not in symbols

    @pytest.mark.asyncio
    async def test_correct_count(self, bybit_client: BybitClient) -> None:
        symbols = await bybit_client.fetch_perpetual_symbols()
        assert len(symbols) == 2


class TestGetInstrumentInfo:
    """Tests for get_instrument_info extraction."""

    @pytest.mark.asyncio
    async def test_btc_instrument_info(self, bybit_client: BybitClient) -> None:
        info = await bybit_client.get_instrument_info("BTC/USDT:USDT")
        assert info.symbol == "BTC/USDT:USDT"
        assert info.min_qty == Decimal("0.001")
        assert info.max_qty == Decimal("100")
        assert info.qty_step == Decimal("0.001")
        assert info.min_notional == Decimal("5")
        assert info.tick_size == Decimal("0.1")

    @pytest.mark.asyncio
    async def test_eth_instrument_info(self, bybit_client: BybitClient) -> None:
        info = await bybit_client.get_instrument_info("ETH/USDT:USDT")
        assert info.symbol == "ETH/USDT:USDT"
        assert info.min_qty == Decimal("0.01")
        assert info.qty_step == Decimal("0.01")
        assert info.tick_size == Decimal("0.01")

    @pytest.mark.asyncio
    async def test_unknown_symbol_raises(self, bybit_client: BybitClient) -> None:
        with pytest.raises(ValueError, match="not found"):
            await bybit_client.get_instrument_info("FAKE/USDT:USDT")

    @pytest.mark.asyncio
    async def test_all_values_are_decimal(self, bybit_client: BybitClient) -> None:
        info = await bybit_client.get_instrument_info("BTC/USDT:USDT")
        assert isinstance(info.min_qty, Decimal)
        assert isinstance(info.max_qty, Decimal)
        assert isinstance(info.qty_step, Decimal)
        assert isinstance(info.min_notional, Decimal)
        assert isinstance(info.tick_size, Decimal)


class TestBybitClientDelegation:
    """Tests for methods that delegate to ccxt exchange."""

    @pytest.mark.asyncio
    async def test_connect_loads_markets(
        self, exchange_settings: ExchangeSettings
    ) -> None:
        client = BybitClient(exchange_settings)
        client._exchange.load_markets = AsyncMock(return_value=MOCK_MARKETS)
        await client.connect()
        client._exchange.load_markets.assert_awaited_once()
        assert len(client._markets) == len(MOCK_MARKETS)
        # Clean up
        client._exchange.close = AsyncMock()
        await client.close()

    @pytest.mark.asyncio
    async def test_close_calls_exchange_close(
        self, exchange_settings: ExchangeSettings
    ) -> None:
        client = BybitClient(exchange_settings)
        client._exchange.close = AsyncMock()
        await client.close()
        client._exchange.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_ticker_delegates(self, bybit_client: BybitClient) -> None:
        mock_ticker = {"symbol": "BTC/USDT:USDT", "last": 50000.0}
        bybit_client._exchange.fetch_ticker = AsyncMock(return_value=mock_ticker)
        result = await bybit_client.fetch_ticker("BTC/USDT:USDT")
        assert result == mock_ticker
        bybit_client._exchange.fetch_ticker.assert_awaited_once_with("BTC/USDT:USDT")

    @pytest.mark.asyncio
    async def test_fetch_balance_delegates(self, bybit_client: BybitClient) -> None:
        mock_balance = {"USDT": {"free": 1000, "total": 1000}}
        bybit_client._exchange.fetch_balance = AsyncMock(return_value=mock_balance)
        result = await bybit_client.fetch_balance()
        assert result == mock_balance
