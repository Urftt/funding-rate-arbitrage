"""P&L tracking with funding fee simulation for paper trading.

Tracks realized P&L, unrealized P&L, and cumulative funding payments per position.
Simulates funding fee settlement every 8 hours for paper trading positions.

PAPR-03: P&L tracking including fees and funding payments.

Bybit funding convention (from research):
  - Positive funding rate = longs pay shorts
  - Our strategy (long spot + short perp) COLLECTS when rate > 0
  - Positive payment = income, negative = expense
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal

from bot.config import FeeSettings
from bot.logging import get_logger
from bot.market_data.ticker_service import TickerService
from bot.models import FundingRateData, Position
from bot.pnl.fee_calculator import FeeCalculator

logger = get_logger(__name__)


@dataclass
class FundingPayment:
    """Record of a single funding payment for a position."""

    amount: Decimal
    rate: Decimal
    mark_price: Decimal
    timestamp: float


@dataclass
class PositionPnL:
    """P&L tracking state for a single delta-neutral position."""

    position_id: str
    entry_fee: Decimal
    exit_fee: Decimal = Decimal("0")
    funding_payments: list[FundingPayment] = field(default_factory=list)
    spot_entry_price: Decimal = Decimal("0")
    perp_entry_price: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    opened_at: float = 0.0
    closed_at: float | None = None
    spot_exit_price: Decimal = Decimal("0")
    perp_exit_price: Decimal = Decimal("0")
    perp_symbol: str = ""


class PnLTracker:
    """Tracks P&L across all open and closed positions.

    Computes realized P&L, unrealized P&L, and cumulative funding
    payments. Simulates funding fee settlement on an 8h schedule
    for paper trading positions.

    Args:
        fee_calculator: For computing funding payment amounts.
        ticker_service: Shared price cache for unrealized P&L calculations.
        fee_settings: Fee rate configuration.
    """

    def __init__(
        self,
        fee_calculator: FeeCalculator,
        ticker_service: TickerService,
        fee_settings: FeeSettings,
    ) -> None:
        self._fee_calculator = fee_calculator
        self._ticker_service = ticker_service
        self._fee_settings = fee_settings
        self._position_pnl: dict[str, PositionPnL] = {}

    def record_open(self, position: Position, entry_fee: Decimal) -> None:
        """Initialize P&L tracking for a newly opened position.

        Args:
            position: The opened Position object.
            entry_fee: Total entry fee for both legs.
        """
        pnl = PositionPnL(
            position_id=position.id,
            entry_fee=entry_fee,
            spot_entry_price=position.spot_entry_price,
            perp_entry_price=position.perp_entry_price,
            quantity=position.quantity,
            opened_at=position.opened_at,
            perp_symbol=position.perp_symbol,
        )
        self._position_pnl[position.id] = pnl

        logger.info(
            "pnl_record_open",
            position_id=position.id,
            entry_fee=str(entry_fee),
            quantity=str(position.quantity),
            spot_entry_price=str(position.spot_entry_price),
            perp_entry_price=str(position.perp_entry_price),
        )

    def record_close(
        self,
        position_id: str,
        spot_exit_price: Decimal,
        perp_exit_price: Decimal,
        exit_fee: Decimal,
    ) -> None:
        """Finalize P&L tracking for a closed position.

        Args:
            position_id: ID of the position being closed.
            spot_exit_price: Spot price at exit (not used for fee -- fee is pre-computed).
            perp_exit_price: Perp price at exit (not used for fee -- fee is pre-computed).
            exit_fee: Total exit fee for both legs.

        Raises:
            KeyError: If position_id is not tracked.
        """
        pnl = self._position_pnl[position_id]
        pnl.exit_fee = exit_fee
        pnl.spot_exit_price = spot_exit_price
        pnl.perp_exit_price = perp_exit_price
        pnl.closed_at = time.time()

        logger.info(
            "pnl_record_close",
            position_id=position_id,
            exit_fee=str(exit_fee),
            total_funding_payments=len(pnl.funding_payments),
        )

    def record_funding_payment(
        self,
        position_id: str,
        funding_rate: Decimal,
        mark_price: Decimal,
        quantity: Decimal,
    ) -> None:
        """Record a funding payment for a position.

        Calculates the payment amount using FeeCalculator and appends
        it to the position's funding payment history.

        Args:
            position_id: ID of the position receiving funding.
            funding_rate: Current funding rate (signed).
            mark_price: Current mark price for position value calculation.
            quantity: Position quantity.

        Raises:
            KeyError: If position_id is not tracked.
        """
        payment_amount = self._fee_calculator.calculate_funding_payment(
            position_qty=quantity,
            mark_price=mark_price,
            funding_rate=funding_rate,
            is_short=True,  # Our strategy is always short perp
        )

        payment = FundingPayment(
            amount=payment_amount,
            rate=funding_rate,
            mark_price=mark_price,
            timestamp=time.time(),
        )

        pnl = self._position_pnl[position_id]
        pnl.funding_payments.append(payment)

        logger.info(
            "funding_payment_recorded",
            position_id=position_id,
            amount=str(payment_amount),
            rate=str(funding_rate),
            mark_price=str(mark_price),
            total_payments=len(pnl.funding_payments),
        )

    def simulate_funding_settlement(
        self,
        positions: list[Position],
        funding_rates: dict[str, FundingRateData],
    ) -> None:
        """Simulate funding fee settlement for all open positions.

        Called by the orchestrator on schedule (every 8h simulated).
        For each position, looks up the current funding rate and records
        the payment.

        Args:
            positions: List of currently open positions.
            funding_rates: Dict mapping perp_symbol to FundingRateData.
        """
        for position in positions:
            rate_data = funding_rates.get(position.perp_symbol)
            if rate_data is None:
                logger.warning(
                    "no_funding_rate_for_position",
                    position_id=position.id,
                    perp_symbol=position.perp_symbol,
                )
                continue

            if position.id not in self._position_pnl:
                logger.warning(
                    "position_not_tracked",
                    position_id=position.id,
                )
                continue

            self.record_funding_payment(
                position_id=position.id,
                funding_rate=rate_data.rate,
                mark_price=rate_data.mark_price,
                quantity=position.quantity,
            )

        logger.info(
            "funding_settlement_simulated",
            position_count=len(positions),
        )

    async def get_unrealized_pnl(self, position_id: str) -> Decimal:
        """Calculate unrealized P&L from price movements (excluding fees/funding).

        Spot P&L: (current_spot - entry_spot) * quantity (we're long spot)
        Perp P&L: (entry_perp - current_perp) * quantity (we're short perp)
        Total = spot_pnl + perp_pnl (should be near zero for delta-neutral)

        NOTE: This excludes fees and funding -- those are tracked separately.

        Args:
            position_id: ID of the position.

        Returns:
            Unrealized P&L from price movements.

        Raises:
            KeyError: If position_id is not tracked.
        """
        pnl = self._position_pnl[position_id]

        # Get current prices from ticker service
        # Use perp symbol price for both (they should be very close)
        current_spot_price = await self._ticker_service.get_price(
            pnl.spot_entry_price.__class__.__name__  # placeholder
        )
        current_perp_price = await self._ticker_service.get_price(
            pnl.perp_entry_price.__class__.__name__  # placeholder
        )

        # If no current prices available, use entry prices (unrealized = 0)
        if current_spot_price is None:
            current_spot_price = pnl.spot_entry_price
        if current_perp_price is None:
            current_perp_price = pnl.perp_entry_price

        # Spot P&L: long position, profit when price goes up
        spot_pnl = (current_spot_price - pnl.spot_entry_price) * pnl.quantity

        # Perp P&L: short position, profit when price goes down
        perp_pnl = (pnl.perp_entry_price - current_perp_price) * pnl.quantity

        return spot_pnl + perp_pnl

    async def get_unrealized_pnl_with_prices(
        self,
        position_id: str,
        current_spot_price: Decimal,
        current_perp_price: Decimal,
    ) -> Decimal:
        """Calculate unrealized P&L with explicitly provided prices.

        Useful for testing and when caller already has prices cached.

        Args:
            position_id: ID of the position.
            current_spot_price: Current spot price.
            current_perp_price: Current perp price.

        Returns:
            Unrealized P&L from price movements.

        Raises:
            KeyError: If position_id is not tracked.
        """
        pnl = self._position_pnl[position_id]

        spot_pnl = (current_spot_price - pnl.spot_entry_price) * pnl.quantity
        perp_pnl = (pnl.perp_entry_price - current_perp_price) * pnl.quantity

        return spot_pnl + perp_pnl

    def get_total_pnl(
        self,
        position_id: str,
        unrealized_pnl: Decimal = Decimal("0"),
    ) -> dict:
        """Return full P&L breakdown for a position.

        Returns dict with:
        - unrealized_pnl: Price movement P&L (passed in or 0)
        - total_funding: Sum of all funding payments
        - total_fees: entry_fee + exit_fee
        - net_pnl: unrealized + funding - fees

        Args:
            position_id: ID of the position.
            unrealized_pnl: Pre-calculated unrealized P&L (from get_unrealized_pnl).

        Returns:
            Dict with P&L breakdown.

        Raises:
            KeyError: If position_id is not tracked.
        """
        pnl = self._position_pnl[position_id]

        total_funding = sum(
            (fp.amount for fp in pnl.funding_payments),
            Decimal("0"),
        )
        total_fees = pnl.entry_fee + pnl.exit_fee
        net_pnl = unrealized_pnl + total_funding - total_fees

        return {
            "unrealized_pnl": unrealized_pnl,
            "total_funding": total_funding,
            "total_fees": total_fees,
            "net_pnl": net_pnl,
        }

    def get_portfolio_summary(self) -> dict:
        """Aggregate P&L across all tracked positions.

        Returns:
            Dict with:
            - total_unrealized: Always 0 (requires async price lookup).
            - total_funding_collected: Sum of positive funding payments.
            - total_fees_paid: Sum of all fees.
            - net_portfolio_pnl: funding - fees (excluding unrealized).
            - position_count: Number of tracked positions.
        """
        total_funding = Decimal("0")
        total_fees = Decimal("0")

        for pnl in self._position_pnl.values():
            position_funding = sum(
                (fp.amount for fp in pnl.funding_payments),
                Decimal("0"),
            )
            total_funding += position_funding
            total_fees += pnl.entry_fee + pnl.exit_fee

        net_pnl = total_funding - total_fees

        return {
            "total_unrealized": Decimal("0"),
            "total_funding_collected": total_funding,
            "total_fees_paid": total_fees,
            "net_portfolio_pnl": net_pnl,
            "position_count": len(self._position_pnl),
        }

    def get_position_pnl(self, position_id: str) -> PositionPnL | None:
        """Get the raw PositionPnL tracking state for a position.

        Args:
            position_id: ID of the position.

        Returns:
            PositionPnL if tracked, None otherwise.
        """
        return self._position_pnl.get(position_id)

    def get_closed_positions(self) -> list[PositionPnL]:
        """Return closed positions sorted by close time (most recent first).

        Used by DASH-03 trade history display.

        Returns:
            List of PositionPnL with closed_at set, sorted descending.
        """
        closed = [p for p in self._position_pnl.values() if p.closed_at is not None]
        closed.sort(key=lambda p: p.closed_at, reverse=True)  # type: ignore[arg-type]
        return closed

    def get_open_position_pnls(self) -> list[PositionPnL]:
        """Return P&L records for currently open positions.

        Returns:
            List of PositionPnL where closed_at is None.
        """
        return [p for p in self._position_pnl.values() if p.closed_at is None]

    def get_all_position_pnls(self) -> list[PositionPnL]:
        """Return all position P&L records (open and closed).

        Used by analytics (Plan 03) for Sharpe ratio and drawdown calculations.

        Returns:
            List of all PositionPnL records.
        """
        return list(self._position_pnl.values())
