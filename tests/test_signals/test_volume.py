"""Tests for volume trend detection module."""

from decimal import Decimal

from bot.data.models import OHLCVCandle
from bot.signals.volume import compute_volume_trend


def _make_candles(
    volumes: list[Decimal],
    symbol: str = "BTC/USDT:USDT",
    start_ms: int = 1_700_000_000_000,
    interval_ms: int = 3_600_000,  # 1 hour
) -> list[OHLCVCandle]:
    """Create a list of OHLCVCandle objects with controllable volumes.

    Generates candles with ascending timestamps and the given volumes.
    Price fields are set to a constant since volume tests don't use them.

    Args:
        volumes: List of volume values for each candle.
        symbol: Trading pair symbol.
        start_ms: Starting timestamp in milliseconds.
        interval_ms: Time between candles in milliseconds (default 1h).

    Returns:
        List of OHLCVCandle sorted by timestamp ascending.
    """
    price = Decimal("50000")
    return [
        OHLCVCandle(
            symbol=symbol,
            timestamp_ms=start_ms + i * interval_ms,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=v,
        )
        for i, v in enumerate(volumes)
    ]


class TestComputeVolumeTrend:
    """Tests for compute_volume_trend."""

    def test_volume_ok_recent_above_threshold(self) -> None:
        """Volume OK when recent period average >= 70% of prior period average."""
        # 7 days * 24 hours = 168 candles per period, 336 total
        prior_volumes = [Decimal("1000")] * 168
        recent_volumes = [Decimal("800")] * 168  # 80% of prior -- above 70% threshold
        candles = _make_candles(prior_volumes + recent_volumes)
        assert compute_volume_trend(candles) is True

    def test_volume_declining_below_threshold(self) -> None:
        """Volume declining when recent < 70% of prior."""
        prior_volumes = [Decimal("1000")] * 168
        recent_volumes = [Decimal("600")] * 168  # 60% of prior -- below 70% threshold
        candles = _make_candles(prior_volumes + recent_volumes)
        assert compute_volume_trend(candles) is False

    def test_insufficient_data_returns_true(self) -> None:
        """Insufficient data for both periods should return True (graceful degradation)."""
        # Only 100 candles, need 336 for two 7-day periods
        candles = _make_candles([Decimal("1000")] * 100)
        assert compute_volume_trend(candles) is True

    def test_empty_candles_returns_true(self) -> None:
        """Empty candle list should return True (graceful degradation)."""
        assert compute_volume_trend([]) is True

    def test_sufficient_recent_insufficient_prior_returns_true(self) -> None:
        """If only enough candles for one period but not two, return True."""
        # 200 candles: enough for recent (168) but not for prior + recent (336)
        candles = _make_candles([Decimal("1000")] * 200)
        assert compute_volume_trend(candles) is True

    def test_all_zero_volumes_returns_true(self) -> None:
        """All-zero volumes should return True (no trend signal, prior_avg == 0)."""
        candles = _make_candles([Decimal("0")] * 336)
        assert compute_volume_trend(candles) is True

    def test_exact_threshold_boundary(self) -> None:
        """Volume exactly at 70% threshold should return True (>= comparison)."""
        prior_volumes = [Decimal("1000")] * 168
        recent_volumes = [Decimal("700")] * 168  # exactly 70%
        candles = _make_candles(prior_volumes + recent_volumes)
        assert compute_volume_trend(candles) is True

    def test_custom_lookback_days(self) -> None:
        """Custom lookback_days parameter should be respected."""
        # 3 days * 24 = 72 candles per period, 144 total
        prior_volumes = [Decimal("1000")] * 72
        recent_volumes = [Decimal("500")] * 72  # 50% -- below 70%
        candles = _make_candles(prior_volumes + recent_volumes)
        assert compute_volume_trend(candles, lookback_days=3) is False

    def test_custom_decline_ratio(self) -> None:
        """Custom decline_ratio should be respected."""
        prior_volumes = [Decimal("1000")] * 168
        recent_volumes = [Decimal("600")] * 168  # 60%
        candles = _make_candles(prior_volumes + recent_volumes)
        # With decline_ratio=0.5 (50%), 60% should be OK
        assert compute_volume_trend(candles, decline_ratio=Decimal("0.5")) is True

    def test_result_is_bool(self) -> None:
        """Result should always be a boolean."""
        candles = _make_candles([Decimal("1000")] * 336)
        result = compute_volume_trend(candles)
        assert isinstance(result, bool)
