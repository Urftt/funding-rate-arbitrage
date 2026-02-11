"""Tests for FundingMonitor and TickerService.

All tests use mocked exchange client to avoid real API calls.
"""

import time

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from bot.market_data.funding_monitor import FundingMonitor
from bot.market_data.ticker_service import TickerService
from bot.models import FundingRateData


# ---------------------------------------------------------------------------
# Sample ticker data (mimics ccxt fetch_tickers response for Bybit linear)
# ---------------------------------------------------------------------------

MOCK_TICKERS = {
    "BTC/USDT:USDT": {
        "symbol": "BTC/USDT:USDT",
        "last": 50000.0,
        "info": {
            "fundingRate": "0.0005",
            "nextFundingTime": "1700000000000",
            "fundingIntervalHour": "8",
            "volume24h": "1000000",
        },
    },
    "ETH/USDT:USDT": {
        "symbol": "ETH/USDT:USDT",
        "last": 3000.0,
        "info": {
            "fundingRate": "0.0001",
            "nextFundingTime": "1700000000000",
            "fundingIntervalHour": "8",
            "volume24h": "500000",
        },
    },
    "DOGE/USDT:USDT": {
        "symbol": "DOGE/USDT:USDT",
        "last": 0.15,
        "info": {
            "fundingRate": "-0.0002",
            "nextFundingTime": "1700000000000",
            "fundingIntervalHour": "8",
            "volume24h": "200000",
        },
    },
    "SOL/USDT:USDT": {
        "symbol": "SOL/USDT:USDT",
        "last": 100.0,
        "info": {
            "fundingRate": "0.001",
            "nextFundingTime": "1700000000000",
            "fundingIntervalHour": "8",
            "volume24h": "800000",
        },
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_exchange() -> AsyncMock:
    """Mock ExchangeClient that returns sample ticker data."""
    exchange = AsyncMock()
    exchange.fetch_tickers = AsyncMock(return_value=MOCK_TICKERS)
    exchange.fetch_perpetual_symbols = AsyncMock(
        return_value=list(MOCK_TICKERS.keys())
    )
    return exchange


@pytest.fixture
def ticker_service() -> TickerService:
    """Fresh TickerService instance."""
    return TickerService()


@pytest.fixture
def funding_monitor(
    mock_exchange: AsyncMock, ticker_service: TickerService
) -> FundingMonitor:
    """FundingMonitor with mocked exchange and fresh ticker service."""
    return FundingMonitor(
        exchange=mock_exchange,
        ticker_service=ticker_service,
        poll_interval=1.0,
    )


# ---------------------------------------------------------------------------
# TickerService tests
# ---------------------------------------------------------------------------


class TestTickerService:
    """Tests for the shared price cache."""

    @pytest.mark.asyncio
    async def test_update_and_get_price(self, ticker_service: TickerService) -> None:
        now = time.time()
        await ticker_service.update_price("BTC/USDT:USDT", Decimal("50000"), now)
        price = await ticker_service.get_price("BTC/USDT:USDT")
        assert price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_get_price_missing_returns_none(
        self, ticker_service: TickerService
    ) -> None:
        price = await ticker_service.get_price("NONEXISTENT")
        assert price is None

    @pytest.mark.asyncio
    async def test_price_age(self, ticker_service: TickerService) -> None:
        past = time.time() - 10.0
        await ticker_service.update_price("BTC/USDT:USDT", Decimal("50000"), past)
        age = await ticker_service.get_price_age("BTC/USDT:USDT")
        assert age is not None
        assert age >= 10.0

    @pytest.mark.asyncio
    async def test_price_age_missing_returns_none(
        self, ticker_service: TickerService
    ) -> None:
        age = await ticker_service.get_price_age("NONEXISTENT")
        assert age is None

    @pytest.mark.asyncio
    async def test_is_stale_missing_symbol(
        self, ticker_service: TickerService
    ) -> None:
        assert await ticker_service.is_stale("NONEXISTENT") is True

    @pytest.mark.asyncio
    async def test_is_stale_old_price(self, ticker_service: TickerService) -> None:
        old = time.time() - 120.0  # 2 minutes old
        await ticker_service.update_price("BTC/USDT:USDT", Decimal("50000"), old)
        assert await ticker_service.is_stale("BTC/USDT:USDT", max_age_seconds=60.0) is True

    @pytest.mark.asyncio
    async def test_is_not_stale_fresh_price(
        self, ticker_service: TickerService
    ) -> None:
        now = time.time()
        await ticker_service.update_price("BTC/USDT:USDT", Decimal("50000"), now)
        assert await ticker_service.is_stale("BTC/USDT:USDT", max_age_seconds=60.0) is False

    @pytest.mark.asyncio
    async def test_update_overwrites_previous(
        self, ticker_service: TickerService
    ) -> None:
        now = time.time()
        await ticker_service.update_price("BTC/USDT:USDT", Decimal("50000"), now)
        await ticker_service.update_price("BTC/USDT:USDT", Decimal("51000"), now + 1)
        price = await ticker_service.get_price("BTC/USDT:USDT")
        assert price == Decimal("51000")


# ---------------------------------------------------------------------------
# FundingMonitor tests
# ---------------------------------------------------------------------------


class TestFundingMonitorParsing:
    """Tests for ticker parsing and funding rate extraction."""

    @pytest.mark.asyncio
    async def test_poll_once_parses_funding_rates(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        rates = funding_monitor.get_all_funding_rates()
        assert len(rates) == 4

    @pytest.mark.asyncio
    async def test_funding_rate_is_decimal(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        rate = funding_monitor.get_funding_rate("BTC/USDT:USDT")
        assert rate is not None
        assert isinstance(rate.rate, Decimal)
        assert rate.rate == Decimal("0.0005")

    @pytest.mark.asyncio
    async def test_mark_price_extracted(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        rate = funding_monitor.get_funding_rate("BTC/USDT:USDT")
        assert rate is not None
        assert rate.mark_price == Decimal("50000.0")

    @pytest.mark.asyncio
    async def test_interval_hours_parsed(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        rate = funding_monitor.get_funding_rate("BTC/USDT:USDT")
        assert rate is not None
        assert rate.interval_hours == 8


class TestFundingMonitorSorting:
    """Tests for funding rate sorting and filtering."""

    @pytest.mark.asyncio
    async def test_get_all_sorted_descending(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        rates = funding_monitor.get_all_funding_rates()
        # SOL (0.001) > BTC (0.0005) > ETH (0.0001) > DOGE (-0.0002)
        assert rates[0].symbol == "SOL/USDT:USDT"
        assert rates[1].symbol == "BTC/USDT:USDT"
        assert rates[2].symbol == "ETH/USDT:USDT"
        assert rates[3].symbol == "DOGE/USDT:USDT"

    @pytest.mark.asyncio
    async def test_get_profitable_pairs_above_threshold(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        # Threshold 0.0003 should include SOL (0.001) and BTC (0.0005)
        profitable = funding_monitor.get_profitable_pairs(Decimal("0.0003"))
        assert len(profitable) == 2
        assert profitable[0].symbol == "SOL/USDT:USDT"
        assert profitable[1].symbol == "BTC/USDT:USDT"

    @pytest.mark.asyncio
    async def test_get_profitable_pairs_excludes_negative(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        # Even with threshold 0, DOGE (-0.0002) should be excluded
        profitable = funding_monitor.get_profitable_pairs(Decimal("0"))
        symbols = [p.symbol for p in profitable]
        assert "DOGE/USDT:USDT" not in symbols

    @pytest.mark.asyncio
    async def test_get_profitable_pairs_high_threshold_empty(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        profitable = funding_monitor.get_profitable_pairs(Decimal("0.01"))
        assert len(profitable) == 0


class TestFundingMonitorGetRate:
    """Tests for get_funding_rate method."""

    @pytest.mark.asyncio
    async def test_get_existing_rate(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor._poll_once()
        rate = funding_monitor.get_funding_rate("ETH/USDT:USDT")
        assert rate is not None
        assert rate.rate == Decimal("0.0001")

    @pytest.mark.asyncio
    async def test_get_missing_rate_returns_none(
        self, funding_monitor: FundingMonitor
    ) -> None:
        assert funding_monitor.get_funding_rate("FAKE/USDT:USDT") is None


class TestFundingMonitorPriceCache:
    """Tests for TickerService integration."""

    @pytest.mark.asyncio
    async def test_poll_updates_ticker_service(
        self, funding_monitor: FundingMonitor, ticker_service: TickerService
    ) -> None:
        await funding_monitor._poll_once()
        btc_price = await ticker_service.get_price("BTC/USDT:USDT")
        assert btc_price == Decimal("50000.0")

    @pytest.mark.asyncio
    async def test_all_prices_updated(
        self, funding_monitor: FundingMonitor, ticker_service: TickerService
    ) -> None:
        await funding_monitor._poll_once()
        for symbol in MOCK_TICKERS:
            price = await ticker_service.get_price(symbol)
            assert price is not None, f"Missing price for {symbol}"

    @pytest.mark.asyncio
    async def test_prices_are_not_stale(
        self, funding_monitor: FundingMonitor, ticker_service: TickerService
    ) -> None:
        await funding_monitor._poll_once()
        for symbol in MOCK_TICKERS:
            assert await ticker_service.is_stale(symbol) is False


class TestFundingMonitorLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_task(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor.start()
        assert funding_monitor._task is not None
        assert funding_monitor._running is True
        await funding_monitor.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor.start()
        await funding_monitor.stop()
        assert funding_monitor._running is False
        assert funding_monitor._task is None

    @pytest.mark.asyncio
    async def test_double_start_warns(
        self, funding_monitor: FundingMonitor
    ) -> None:
        await funding_monitor.start()
        # Second start should not crash
        await funding_monitor.start()
        assert funding_monitor._running is True
        await funding_monitor.stop()
