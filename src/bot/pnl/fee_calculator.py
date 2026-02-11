"""Fee computation and profitability analysis for funding rate arbitrage.

All calculations use Decimal arithmetic exclusively -- no float conversions anywhere.

Fee rates are sourced from FeeSettings (Bybit Non-VIP base tier defaults):
  - Spot taker: 0.1% (0.001)
  - Perp taker: 0.055% (0.00055)

Bybit funding convention (Pitfall #1 from research):
  - Positive funding rate = longs pay shorts
  - Our strategy (long spot + short perp) COLLECTS when rate > 0
"""

from decimal import Decimal

from bot.config import FeeSettings


class FeeCalculator:
    """Calculates trading fees and determines trade profitability.

    Uses FeeSettings for maker/taker rates. All methods return Decimal
    values with full precision -- no rounding is applied.

    Args:
        fee_settings: Fee rate configuration (spot/perp maker/taker rates).
    """

    def __init__(self, fee_settings: FeeSettings) -> None:
        self._fees = fee_settings

    def calculate_entry_fee(
        self,
        quantity: Decimal,
        spot_price: Decimal,
        perp_price: Decimal,
    ) -> Decimal:
        """Calculate total fee for opening a delta-neutral position.

        Entry = buy spot (taker) + sell perp (taker).

        Args:
            quantity: Base asset quantity (e.g., 1.0 BTC).
            spot_price: Current spot price.
            perp_price: Current perpetual price.

        Returns:
            Total entry fee in quote currency (USDT).
        """
        spot_fee = quantity * spot_price * self._fees.spot_taker
        perp_fee = quantity * perp_price * self._fees.perp_taker
        return spot_fee + perp_fee

    def calculate_exit_fee(
        self,
        quantity: Decimal,
        spot_price: Decimal,
        perp_price: Decimal,
    ) -> Decimal:
        """Calculate total fee for closing a delta-neutral position.

        Exit = sell spot (taker) + buy-to-close perp (taker).

        Args:
            quantity: Base asset quantity.
            spot_price: Current spot price at exit.
            perp_price: Current perpetual price at exit.

        Returns:
            Total exit fee in quote currency (USDT).
        """
        spot_fee = quantity * spot_price * self._fees.spot_taker
        perp_fee = quantity * perp_price * self._fees.perp_taker
        return spot_fee + perp_fee

    def calculate_round_trip_fee(
        self,
        quantity: Decimal,
        spot_entry_price: Decimal,
        perp_entry_price: Decimal,
        spot_exit_price: Decimal,
        perp_exit_price: Decimal,
    ) -> Decimal:
        """Calculate total fees for a complete open + close cycle.

        Args:
            quantity: Base asset quantity.
            spot_entry_price: Spot price at entry.
            perp_entry_price: Perp price at entry.
            spot_exit_price: Spot price at exit.
            perp_exit_price: Perp price at exit.

        Returns:
            Total round-trip fee in quote currency (USDT).
        """
        entry = self.calculate_entry_fee(quantity, spot_entry_price, perp_entry_price)
        exit_ = self.calculate_exit_fee(quantity, spot_exit_price, perp_exit_price)
        return entry + exit_

    def min_funding_rate_for_breakeven(
        self,
        quantity: Decimal,
        entry_price: Decimal,
        round_trip_fee: Decimal,
        funding_periods: int,
    ) -> Decimal:
        """Calculate the minimum 8h funding rate needed to break even.

        Answers: "What minimum funding rate per period do I need to
        recover round_trip_fee over funding_periods?"

        Formula: rate = round_trip_fee / (quantity * entry_price * periods)

        Args:
            quantity: Base asset quantity.
            entry_price: Position entry price (used as position value proxy).
            round_trip_fee: Total fees to recover.
            funding_periods: Number of funding periods (each 8h on Bybit).

        Returns:
            Minimum funding rate per period as a Decimal.
        """
        position_value = quantity * entry_price
        return round_trip_fee / (position_value * Decimal(str(funding_periods)))

    def is_profitable(
        self,
        funding_rate: Decimal,
        quantity: Decimal,
        entry_price: Decimal,
        min_periods: int,
    ) -> bool:
        """Determine if a trade is worth entering given fees and expected funding.

        Compares expected total funding income over min_periods against
        the estimated round-trip fee (using entry_price for both legs,
        as a conservative approximation).

        Args:
            funding_rate: Current 8h funding rate.
            quantity: Base asset quantity.
            entry_price: Position entry price.
            min_periods: Minimum number of funding periods to hold.

        Returns:
            True if expected funding income exceeds estimated round-trip fees.
        """
        position_value = quantity * entry_price
        expected_funding = position_value * funding_rate * Decimal(str(min_periods))

        # Estimate round-trip fee using entry_price for both legs (conservative)
        estimated_round_trip = self.calculate_round_trip_fee(
            quantity=quantity,
            spot_entry_price=entry_price,
            perp_entry_price=entry_price,
            spot_exit_price=entry_price,
            perp_exit_price=entry_price,
        )

        return expected_funding > estimated_round_trip

    def calculate_funding_payment(
        self,
        position_qty: Decimal,
        mark_price: Decimal,
        funding_rate: Decimal,
        is_short: bool,
    ) -> Decimal:
        """Calculate funding payment for a single funding period.

        BYBIT CONVENTION (verified in research, Pitfall #1):
        Positive funding rate = longs pay shorts.
        - Short + positive rate = RECEIVE payment (positive return)
        - Short + negative rate = PAY payment (negative return)
        - Long + positive rate = PAY payment (negative return)
        - Long + negative rate = RECEIVE payment (positive return)

        Args:
            position_qty: Absolute position quantity.
            mark_price: Current mark price.
            funding_rate: Current funding rate (signed).
            is_short: True if this is a short perp position.

        Returns:
            Funding payment amount. Positive = income, negative = expense.
        """
        position_value = position_qty * mark_price
        raw_payment = position_value * funding_rate

        if is_short:
            # Short: positive rate = longs pay us (income)
            return raw_payment
        else:
            # Long: positive rate = we pay shorts (expense)
            return -raw_payment
