"""Tests for funding rate persistence scoring (SGNL-02).

All test values use Decimal (project convention). Tests cover consecutive
counting, normalization, edge cases, and capping behavior.
"""

from decimal import Decimal

import pytest

from bot.signals.persistence import compute_persistence_score


class TestComputePersistenceScore:
    """Tests for persistence scoring."""

    def test_all_above_threshold(self) -> None:
        """All rates above threshold: persistence = count / max_periods."""
        rates = [Decimal("0.0005")] * 10
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        assert result == Decimal(10) / Decimal(30)

    def test_last_n_above_then_one_below(self) -> None:
        """Only last N rates above threshold, earlier below: consecutive = N."""
        rates = [Decimal("0.0001")] * 5 + [Decimal("0.0005")] * 8
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        # 8 consecutive above threshold from the end
        assert result == Decimal(8) / Decimal(30)

    def test_no_rates_above_threshold(self) -> None:
        """No rates above threshold: persistence = 0."""
        rates = [Decimal("0.0001")] * 10
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        assert result == Decimal("0")

    def test_empty_list_returns_zero(self) -> None:
        """Empty list returns Decimal('0')."""
        result = compute_persistence_score(
            [], threshold=Decimal("0.0003"), max_periods=30
        )
        assert result == Decimal("0")

    def test_capping_at_one(self) -> None:
        """When consecutive > max_periods, score caps at Decimal('1')."""
        rates = [Decimal("0.0005")] * 50
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        assert result == Decimal("1")

    def test_exactly_max_periods(self) -> None:
        """When consecutive == max_periods, score is exactly 1."""
        rates = [Decimal("0.0005")] * 30
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        assert result == Decimal("1")

    def test_single_rate_above(self) -> None:
        """Single rate above threshold: persistence = 1 / max_periods."""
        rates = [Decimal("0.0005")]
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        assert result == Decimal(1) / Decimal(30)

    def test_break_in_middle(self) -> None:
        """Break in the middle only counts from the end.

        [above, above, BELOW, above, above, above] -> consecutive = 3
        """
        rates = [
            Decimal("0.0005"),
            Decimal("0.0005"),
            Decimal("0.0001"),  # break
            Decimal("0.0005"),
            Decimal("0.0005"),
            Decimal("0.0005"),
        ]
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        assert result == Decimal(3) / Decimal(30)

    def test_exact_threshold_counts(self) -> None:
        """Rate exactly equal to threshold counts as elevated (>=)."""
        rates = [Decimal("0.0003")] * 5
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        assert result == Decimal(5) / Decimal(30)

    def test_result_is_decimal_type(self) -> None:
        """Result should always be a Decimal."""
        rates = [Decimal("0.0005")] * 5
        result = compute_persistence_score(
            rates, threshold=Decimal("0.0003"), max_periods=30
        )
        assert isinstance(result, Decimal)
