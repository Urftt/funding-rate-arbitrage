"""Tests for composite signal aggregation (SGNL-03).

Tests verify:
- normalize_rate_level: below cap, at cap, above cap, negative rate
- compute_composite_score: equal weights, zero weights, dominant weight
"""

from decimal import Decimal

from bot.signals.composite import compute_composite_score, normalize_rate_level


class TestNormalizeRateLevel:
    """Tests for normalize_rate_level."""

    def test_rate_below_cap(self) -> None:
        """Rate below cap produces proportional score."""
        result = normalize_rate_level(Decimal("0.001"), cap=Decimal("0.003"))
        expected = Decimal("0.001") / Decimal("0.003")
        assert result == expected

    def test_rate_at_cap(self) -> None:
        """Rate at cap produces score of 1."""
        result = normalize_rate_level(Decimal("0.003"), cap=Decimal("0.003"))
        assert result == Decimal("1")

    def test_rate_above_cap(self) -> None:
        """Rate above cap is capped at 1."""
        result = normalize_rate_level(Decimal("0.005"), cap=Decimal("0.003"))
        assert result == Decimal("1")

    def test_negative_rate_uses_abs(self) -> None:
        """Negative rates produce same score as positive (abs)."""
        positive = normalize_rate_level(Decimal("0.001"), cap=Decimal("0.003"))
        negative = normalize_rate_level(Decimal("-0.001"), cap=Decimal("0.003"))
        assert positive == negative

    def test_zero_rate(self) -> None:
        """Zero rate produces score of 0."""
        result = normalize_rate_level(Decimal("0"), cap=Decimal("0.003"))
        assert result == Decimal("0")


class TestComputeCompositeScore:
    """Tests for compute_composite_score."""

    def test_equal_weights(self) -> None:
        """Equal weights with known sub-scores produce correct weighted sum."""
        weights = {
            "rate_level": Decimal("0.25"),
            "trend": Decimal("0.25"),
            "persistence": Decimal("0.25"),
            "basis": Decimal("0.25"),
        }
        result = compute_composite_score(
            rate_level=Decimal("1.0"),
            trend_score=Decimal("0.5"),
            persistence=Decimal("0.8"),
            basis_score=Decimal("0.2"),
            weights=weights,
        )
        # Expected: 0.25*1.0 + 0.25*0.5 + 0.25*0.8 + 0.25*0.2 = 0.625
        assert result == Decimal("0.625000")

    def test_zero_weights(self) -> None:
        """All zero weights produce score of 0."""
        weights = {
            "rate_level": Decimal("0"),
            "trend": Decimal("0"),
            "persistence": Decimal("0"),
            "basis": Decimal("0"),
        }
        result = compute_composite_score(
            rate_level=Decimal("1.0"),
            trend_score=Decimal("1.0"),
            persistence=Decimal("1.0"),
            basis_score=Decimal("1.0"),
            weights=weights,
        )
        assert result == Decimal("0.000000")

    def test_single_dominant_weight(self) -> None:
        """Single dominant weight (rate_level=1.0, rest=0) isolates that signal."""
        weights = {
            "rate_level": Decimal("1.0"),
            "trend": Decimal("0"),
            "persistence": Decimal("0"),
            "basis": Decimal("0"),
        }
        result = compute_composite_score(
            rate_level=Decimal("0.7"),
            trend_score=Decimal("1.0"),
            persistence=Decimal("1.0"),
            basis_score=Decimal("1.0"),
            weights=weights,
        )
        assert result == Decimal("0.700000")

    def test_default_weights_sum_to_one(self) -> None:
        """Default config weights sum to 1.0 producing score in 0-1 range."""
        from bot.config import SignalSettings

        settings = SignalSettings()
        weights = {
            "rate_level": settings.weight_rate_level,
            "trend": settings.weight_trend,
            "persistence": settings.weight_persistence,
            "basis": settings.weight_basis,
        }
        total_weight = sum(weights.values())
        assert total_weight == Decimal("1.00")

        # With all max sub-scores, composite should equal 1.0
        result = compute_composite_score(
            rate_level=Decimal("1.0"),
            trend_score=Decimal("1.0"),
            persistence=Decimal("1.0"),
            basis_score=Decimal("1.0"),
            weights=weights,
        )
        assert result == Decimal("1.000000")
