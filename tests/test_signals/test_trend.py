"""Tests for funding rate trend detection (SGNL-01).

All test values use Decimal (project convention). Tests cover EMA computation,
trend classification, edge cases, and precision management.
"""

from decimal import Decimal

import pytest

from bot.signals.models import TrendDirection
from bot.signals.trend import compute_ema, classify_trend


class TestComputeEma:
    """Tests for EMA computation."""

    def test_empty_list_returns_empty(self) -> None:
        """Empty input produces empty output."""
        assert compute_ema([], span=3) == []

    def test_single_value_returns_that_value(self) -> None:
        """Single value EMA is the value itself."""
        result = compute_ema([Decimal("0.0005")], span=3)
        assert len(result) == 1
        assert result[0] == Decimal("0.0005").quantize(Decimal("0.000000000001"))

    def test_known_values_span_3(self) -> None:
        """Verify EMA with known values for span=3.

        alpha = 2 / (3 + 1) = 0.5
        EMA[0] = 1
        EMA[1] = 0.5 * 2 + 0.5 * 1 = 1.5
        EMA[2] = 0.5 * 3 + 0.5 * 1.5 = 2.25
        EMA[3] = 0.5 * 4 + 0.5 * 2.25 = 3.125
        EMA[4] = 0.5 * 5 + 0.5 * 3.125 = 4.0625
        """
        values = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")]
        result = compute_ema(values, span=3)

        assert len(result) == 5
        assert result[0] == Decimal("1.000000000000")
        assert result[1] == Decimal("1.500000000000")
        assert result[2] == Decimal("2.250000000000")
        assert result[3] == Decimal("3.125000000000")
        assert result[4] == Decimal("4.062500000000")

    def test_constant_values_return_same(self) -> None:
        """EMA of constant series should equal the constant."""
        values = [Decimal("0.0003")] * 10
        result = compute_ema(values, span=6)

        for ema_val in result:
            assert ema_val == Decimal("0.000300000000")

    def test_ema_values_use_quantize(self) -> None:
        """All EMA results should have bounded precision (12 decimal places)."""
        values = [Decimal("0.00031"), Decimal("0.00029"), Decimal("0.00033")]
        result = compute_ema(values, span=3)

        for ema_val in result:
            # After quantize, the exponent should be -12
            assert ema_val.as_tuple().exponent == -12

    def test_output_length_matches_input(self) -> None:
        """Output list length should match input length."""
        values = [Decimal(str(i)) for i in range(20)]
        result = compute_ema(values, span=6)
        assert len(result) == 20

    def test_span_1_ema_equals_input(self) -> None:
        """With span=1, alpha=1, EMA should equal each input value."""
        values = [Decimal("1"), Decimal("2"), Decimal("3")]
        result = compute_ema(values, span=1)

        assert result[0] == Decimal("1.000000000000")
        assert result[1] == Decimal("2.000000000000")
        assert result[2] == Decimal("3.000000000000")


class TestClassifyTrend:
    """Tests for trend classification."""

    def test_rising_trend(self) -> None:
        """Steadily increasing rates should classify as RISING."""
        rates = [Decimal(str(i * Decimal("0.0001"))) for i in range(1, 15)]
        result = classify_trend(rates, span=6, stable_threshold=Decimal("0.00005"))
        assert result == TrendDirection.RISING

    def test_falling_trend(self) -> None:
        """Steadily decreasing rates should classify as FALLING."""
        rates = [Decimal(str(Decimal("0.002") - i * Decimal("0.0001"))) for i in range(14)]
        result = classify_trend(rates, span=6, stable_threshold=Decimal("0.00005"))
        assert result == TrendDirection.FALLING

    def test_stable_trend_flat_rates(self) -> None:
        """Flat rates should classify as STABLE."""
        rates = [Decimal("0.0003")] * 14
        result = classify_trend(rates, span=6, stable_threshold=Decimal("0.00005"))
        assert result == TrendDirection.STABLE

    def test_stable_when_insufficient_data(self) -> None:
        """Returns STABLE when data length < span + 1."""
        rates = [Decimal("0.0003")] * 5  # 5 < 6 + 1 = 7
        result = classify_trend(rates, span=6)
        assert result == TrendDirection.STABLE

    def test_stable_with_exactly_span_records(self) -> None:
        """Exactly span records (not span+1) still returns STABLE."""
        rates = [Decimal("0.0003")] * 6  # 6 == span, but need span+1=7
        result = classify_trend(rates, span=6)
        assert result == TrendDirection.STABLE

    def test_barely_enough_data_for_trend(self) -> None:
        """Exactly span+1 records should compute a trend."""
        # 7 rising rates: should detect rising trend
        rates = [Decimal(str(Decimal("0.0001") * (i + 1))) for i in range(7)]
        result = classify_trend(rates, span=6, stable_threshold=Decimal("0.00005"))
        assert result == TrendDirection.RISING

    def test_custom_threshold(self) -> None:
        """Very high threshold should make small changes STABLE."""
        rates = [Decimal(str(i * Decimal("0.0001"))) for i in range(1, 15)]
        result = classify_trend(rates, span=6, stable_threshold=Decimal("1.0"))
        assert result == TrendDirection.STABLE

    def test_empty_list_returns_stable(self) -> None:
        """Empty rates list returns STABLE (graceful degradation)."""
        result = classify_trend([], span=6)
        assert result == TrendDirection.STABLE
