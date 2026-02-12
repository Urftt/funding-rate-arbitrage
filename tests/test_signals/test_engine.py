"""Tests for the SignalEngine orchestrator (SGNL-06).

Tests verify:
- Full graceful degradation (all dependencies None)
- Results sorted by composite score descending
- score_for_exit returns dict keyed by symbol
- passes_entry False when volume_ok is False
- passes_entry True when score >= threshold AND volume_ok
- Integration with mocked data_store and ticker_service
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import SignalSettings
from bot.data.models import HistoricalFundingRate, OHLCVCandle
from bot.models import FundingRateData
from bot.signals.engine import SignalEngine
from bot.signals.models import TrendDirection


def _make_funding_rate(
    symbol: str = "BTC/USDT:USDT",
    rate: Decimal = Decimal("0.001"),
    volume: Decimal = Decimal("5000000"),
) -> FundingRateData:
    """Create a test FundingRateData."""
    return FundingRateData(
        symbol=symbol,
        rate=rate,
        next_funding_time=0,
        interval_hours=8,
        mark_price=Decimal("50000"),
        volume_24h=volume,
    )


def _make_markets() -> dict:
    """Create a minimal markets dict for spot symbol derivation."""
    return {
        "BTC/USDT:USDT": {
            "base": "BTC",
            "quote": "USDT",
            "spot": False,
            "active": True,
        },
        "BTC/USDT": {
            "base": "BTC",
            "quote": "USDT",
            "spot": True,
            "active": True,
        },
        "ETH/USDT:USDT": {
            "base": "ETH",
            "quote": "USDT",
            "spot": False,
            "active": True,
        },
        "ETH/USDT": {
            "base": "ETH",
            "quote": "USDT",
            "spot": True,
            "active": True,
        },
    }


@pytest.fixture
def signal_settings() -> SignalSettings:
    """Default signal settings."""
    return SignalSettings()


class TestGracefulDegradation:
    """Tests for graceful degradation with all dependencies as None."""

    @pytest.mark.asyncio
    async def test_all_deps_none(self, signal_settings: SignalSettings) -> None:
        """Full graceful degradation: trend=STABLE, persistence=0, volume_ok=True."""
        engine = SignalEngine(
            signal_settings=signal_settings,
            data_store=None,
            ticker_service=None,
            funding_monitor=None,
        )

        rates = [_make_funding_rate()]
        markets = _make_markets()

        results = await engine.score_opportunities(rates, markets)

        assert len(results) == 1
        signal = results[0].signal
        assert signal.trend == TrendDirection.STABLE
        assert signal.persistence == Decimal("0")
        assert signal.volume_ok is True
        assert signal.basis_spread == Decimal("0")
        assert signal.basis_score == Decimal("0")
        assert signal.score > Decimal("0")

    @pytest.mark.asyncio
    async def test_negative_rate_skipped(self, signal_settings: SignalSettings) -> None:
        """Pairs with rate <= 0 are skipped."""
        engine = SignalEngine(signal_settings=signal_settings)
        rates = [_make_funding_rate(rate=Decimal("-0.001"))]
        markets = _make_markets()

        results = await engine.score_opportunities(rates, markets)
        assert len(results) == 0


class TestScoreOpportunitiesSorting:
    """Tests for score_opportunities result ordering."""

    @pytest.mark.asyncio
    async def test_sorted_by_composite_score_descending(
        self, signal_settings: SignalSettings
    ) -> None:
        """Results are sorted by composite score descending."""
        engine = SignalEngine(signal_settings=signal_settings)

        rates = [
            _make_funding_rate(symbol="ETH/USDT:USDT", rate=Decimal("0.0005")),
            _make_funding_rate(symbol="BTC/USDT:USDT", rate=Decimal("0.002")),
        ]
        markets = _make_markets()

        results = await engine.score_opportunities(rates, markets)

        assert len(results) == 2
        # Higher rate -> higher composite score (with degradation defaults)
        assert results[0].signal.score >= results[1].signal.score
        assert results[0].opportunity.perp_symbol == "BTC/USDT:USDT"


class TestScoreForExit:
    """Tests for score_for_exit."""

    @pytest.mark.asyncio
    async def test_returns_dict_keyed_by_symbol(
        self, signal_settings: SignalSettings
    ) -> None:
        """score_for_exit returns dict mapping symbol to CompositeSignal."""
        engine = SignalEngine(signal_settings=signal_settings)

        rates = [
            _make_funding_rate(symbol="BTC/USDT:USDT", rate=Decimal("0.001")),
            _make_funding_rate(symbol="ETH/USDT:USDT", rate=Decimal("0.0005")),
        ]
        markets = _make_markets()

        result = await engine.score_for_exit(
            symbols=["BTC/USDT:USDT"],
            funding_rates=rates,
            markets=markets,
        )

        assert isinstance(result, dict)
        assert "BTC/USDT:USDT" in result
        # Only requested symbol should be in result
        assert "ETH/USDT:USDT" not in result
        assert result["BTC/USDT:USDT"].symbol == "BTC/USDT:USDT"


class TestPassesEntry:
    """Tests for passes_entry logic."""

    @pytest.mark.asyncio
    async def test_passes_entry_false_when_volume_not_ok(
        self, signal_settings: SignalSettings
    ) -> None:
        """passes_entry is False when volume_ok is False even if score is high."""
        # Create a mock data_store that returns enough candles to trigger volume decline
        mock_store = AsyncMock()
        mock_store.get_funding_rates.return_value = []

        # Create candles showing declining volume
        # Need 2 * 7 * 24 = 336 candles
        # Prior period: high volume; Recent period: low volume
        candles_per_period = 7 * 24
        prior_candles = [
            OHLCVCandle(
                symbol="BTC/USDT:USDT",
                timestamp_ms=i * 3600000,
                open=Decimal("50000"),
                high=Decimal("50100"),
                low=Decimal("49900"),
                close=Decimal("50050"),
                volume=Decimal("1000"),  # High volume
            )
            for i in range(candles_per_period)
        ]
        recent_candles = [
            OHLCVCandle(
                symbol="BTC/USDT:USDT",
                timestamp_ms=(candles_per_period + i) * 3600000,
                open=Decimal("50000"),
                high=Decimal("50100"),
                low=Decimal("49900"),
                close=Decimal("50050"),
                volume=Decimal("100"),  # Low volume (10% of prior)
            )
            for i in range(candles_per_period)
        ]
        mock_store.get_ohlcv_candles.return_value = prior_candles + recent_candles

        engine = SignalEngine(
            signal_settings=signal_settings,
            data_store=mock_store,
        )

        rates = [_make_funding_rate(rate=Decimal("0.003"))]  # High rate -> high score
        markets = _make_markets()

        results = await engine.score_opportunities(rates, markets)

        assert len(results) == 1
        assert results[0].signal.volume_ok is False
        assert results[0].signal.passes_entry is False

    @pytest.mark.asyncio
    async def test_passes_entry_true_when_score_and_volume_ok(
        self, signal_settings: SignalSettings
    ) -> None:
        """passes_entry is True when score >= entry_threshold AND volume_ok."""
        # Lower entry threshold so degradation defaults can pass
        # With degradation: rate_level=1.0, trend=STABLE(0.5), persistence=0, basis=0
        # score = 0.35*1.0 + 0.25*0.5 + 0 + 0 = 0.475
        low_threshold_settings = SignalSettings(entry_threshold=Decimal("0.4"))
        engine = SignalEngine(signal_settings=low_threshold_settings)

        rates = [_make_funding_rate(rate=Decimal("0.003"))]
        markets = _make_markets()

        results = await engine.score_opportunities(rates, markets)

        assert len(results) == 1
        signal = results[0].signal
        assert signal.volume_ok is True
        assert signal.score >= low_threshold_settings.entry_threshold
        assert signal.passes_entry is True


class TestWithMockedDependencies:
    """Tests with mocked data_store and ticker_service."""

    @pytest.mark.asyncio
    async def test_with_historical_data(
        self, signal_settings: SignalSettings
    ) -> None:
        """Engine uses historical data for trend and persistence when available."""
        mock_store = AsyncMock()
        # Return enough historical rates for trend classification.
        # Use a large enough increment (0.0001 per step) so the EMA diff
        # exceeds the stable_threshold (0.00005) over span=6 periods.
        historical_rates = [
            HistoricalFundingRate(
                symbol="BTC/USDT:USDT",
                timestamp_ms=i * 28800000,
                funding_rate=Decimal("0.0003") + Decimal(str(i)) * Decimal("0.0001"),
            )
            for i in range(20)
        ]
        mock_store.get_funding_rates.return_value = historical_rates
        mock_store.get_ohlcv_candles.return_value = []  # No candles -> volume_ok=True

        mock_ticker = AsyncMock()
        mock_ticker.get_price.side_effect = lambda symbol: (
            Decimal("50000") if symbol == "BTC/USDT" else Decimal("50050")
        )

        engine = SignalEngine(
            signal_settings=signal_settings,
            data_store=mock_store,
            ticker_service=mock_ticker,
        )

        rates = [_make_funding_rate()]
        markets = _make_markets()

        results = await engine.score_opportunities(rates, markets)

        assert len(results) == 1
        signal = results[0].signal
        # With strongly increasing rates, trend should be RISING
        assert signal.trend == TrendDirection.RISING
        # Persistence should be > 0 (all rates above threshold)
        assert signal.persistence > Decimal("0")
        # Basis should be computed
        assert signal.basis_spread != Decimal("0")

    @pytest.mark.asyncio
    async def test_score_for_exit_with_data(
        self, signal_settings: SignalSettings
    ) -> None:
        """score_for_exit computes signals for requested symbols."""
        mock_store = AsyncMock()
        mock_store.get_funding_rates.return_value = []
        mock_store.get_ohlcv_candles.return_value = []

        engine = SignalEngine(
            signal_settings=signal_settings,
            data_store=mock_store,
        )

        rates = [
            _make_funding_rate(symbol="BTC/USDT:USDT", rate=Decimal("0.001")),
        ]
        markets = _make_markets()

        result = await engine.score_for_exit(
            symbols=["BTC/USDT:USDT"],
            funding_rates=rates,
            markets=markets,
        )

        assert "BTC/USDT:USDT" in result
        signal = result["BTC/USDT:USDT"]
        assert signal.score > Decimal("0")
