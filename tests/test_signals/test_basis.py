"""Tests for basis spread computation module."""

from decimal import Decimal

from bot.signals.basis import compute_basis_spread, normalize_basis_score


class TestComputeBasisSpread:
    """Tests for compute_basis_spread."""

    def test_positive_basis_perp_above_spot(self) -> None:
        """Positive basis when perp trades at a premium."""
        spot = Decimal("100")
        perp = Decimal("101")
        result = compute_basis_spread(spot, perp)
        assert result == Decimal("0.01")

    def test_negative_basis_perp_below_spot(self) -> None:
        """Negative basis when perp trades at a discount."""
        spot = Decimal("100")
        perp = Decimal("99")
        result = compute_basis_spread(spot, perp)
        assert result == Decimal("-0.01")

    def test_zero_spot_price_returns_zero(self) -> None:
        """Zero spot price should return zero (avoid division by zero)."""
        result = compute_basis_spread(Decimal("0"), Decimal("100"))
        assert result == Decimal("0")

    def test_negative_spot_price_returns_zero(self) -> None:
        """Negative spot price should return zero (invalid input)."""
        result = compute_basis_spread(Decimal("-5"), Decimal("100"))
        assert result == Decimal("0")

    def test_equal_prices_zero_basis(self) -> None:
        """Equal prices should produce zero basis."""
        result = compute_basis_spread(Decimal("50000"), Decimal("50000"))
        assert result == Decimal("0")

    def test_large_premium(self) -> None:
        """Large premium produces large positive basis."""
        spot = Decimal("1000")
        perp = Decimal("1050")
        result = compute_basis_spread(spot, perp)
        assert result == Decimal("0.05")

    def test_result_is_decimal(self) -> None:
        """Result should always be Decimal type."""
        result = compute_basis_spread(Decimal("100"), Decimal("101"))
        assert isinstance(result, Decimal)


class TestNormalizeBasisScore:
    """Tests for normalize_basis_score."""

    def test_small_spread_below_cap(self) -> None:
        """Spread below cap should produce proportional score."""
        # 0.005 / 0.01 = 0.5
        result = normalize_basis_score(Decimal("0.005"))
        assert result == Decimal("0.5")

    def test_spread_at_cap(self) -> None:
        """Spread at cap should produce score of 1."""
        result = normalize_basis_score(Decimal("0.01"))
        assert result == Decimal("1")

    def test_large_spread_clamped_to_one(self) -> None:
        """Spread above cap should be clamped to 1."""
        result = normalize_basis_score(Decimal("0.05"))
        assert result == Decimal("1")

    def test_negative_spread_uses_abs(self) -> None:
        """Negative spread should use absolute value."""
        result = normalize_basis_score(Decimal("-0.005"))
        assert result == Decimal("0.5")

    def test_zero_spread(self) -> None:
        """Zero spread should produce zero score."""
        result = normalize_basis_score(Decimal("0"))
        assert result == Decimal("0")

    def test_custom_cap(self) -> None:
        """Custom cap should be respected."""
        # 0.005 / 0.005 = 1.0
        result = normalize_basis_score(Decimal("0.005"), cap=Decimal("0.005"))
        assert result == Decimal("1")

    def test_result_is_decimal(self) -> None:
        """Result should always be Decimal type."""
        result = normalize_basis_score(Decimal("0.003"))
        assert isinstance(result, Decimal)
