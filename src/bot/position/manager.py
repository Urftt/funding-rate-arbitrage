"""Position lifecycle management for delta-neutral arbitrage.

EXEC-01: Opens delta-neutral positions with simultaneous spot+perp execution.
Uses asyncio.gather for atomic order placement with timeout and rollback.

Position flow:
1. Calculate quantity via PositionSizer
2. Place spot BUY + perp SELL simultaneously (asyncio.gather)
3. Validate delta neutrality after fills
4. Track position in memory
5. Close with reverse orders (spot SELL + perp BUY)
"""

import asyncio
import time
from decimal import Decimal
from uuid import uuid4

from bot.config import TradingSettings
from bot.exceptions import (
    DeltaDriftExceeded,
    DeltaHedgeError,
    DeltaHedgeTimeout,
    InsufficientSizeError,
    PriceUnavailableError,
)
from bot.exchange.types import InstrumentInfo
from bot.execution.executor import Executor
from bot.logging import get_logger
from bot.market_data.ticker_service import TickerService
from bot.models import OrderRequest, OrderResult, OrderSide, OrderType, Position, PositionSide
from bot.pnl.fee_calculator import FeeCalculator
from bot.position.delta_validator import DeltaValidator
from bot.position.sizing import PositionSizer

logger = get_logger(__name__)


class PositionManager:
    """Manages the lifecycle of delta-neutral positions.

    Responsible for opening, tracking, and closing delta-neutral positions
    consisting of a spot buy and perp sell leg (or vice versa for closing).

    Uses asyncio.gather for simultaneous order placement with timeout.
    Implements rollback logic for partial failures.

    Args:
        executor: The order executor (paper or live).
        position_sizer: Calculates matching quantities for spot+perp legs.
        fee_calculator: Computes trading fees.
        delta_validator: Validates delta neutrality after fills.
        ticker_service: Shared price cache for current prices.
        settings: Trading settings (order timeout, etc.).
    """

    def __init__(
        self,
        executor: Executor,
        position_sizer: PositionSizer,
        fee_calculator: FeeCalculator,
        delta_validator: DeltaValidator,
        ticker_service: TickerService,
        settings: TradingSettings | None = None,
    ) -> None:
        self._executor = executor
        self._position_sizer = position_sizer
        self._fee_calculator = fee_calculator
        self._delta_validator = delta_validator
        self._ticker_service = ticker_service
        self._settings = settings or TradingSettings()
        self._positions: dict[str, Position] = {}
        self._lock = asyncio.Lock()

    async def open_position(
        self,
        spot_symbol: str,
        perp_symbol: str,
        available_balance: Decimal,
        spot_instrument: InstrumentInfo,
        perp_instrument: InstrumentInfo,
    ) -> Position:
        """Open a delta-neutral position with simultaneous spot+perp orders.

        Steps:
        1. Get price from TickerService
        2. Calculate matching quantity via PositionSizer
        3. Place spot BUY + perp SELL simultaneously with asyncio.gather
        4. Handle timeout and partial failures with rollback
        5. Validate delta neutrality
        6. Create and store Position

        Args:
            spot_symbol: Spot trading pair (e.g., "BTC/USDT").
            perp_symbol: Perp trading pair (e.g., "BTC/USDT:USDT").
            available_balance: Available quote currency balance.
            spot_instrument: Spot instrument constraints.
            perp_instrument: Perp instrument constraints.

        Returns:
            The created Position object.

        Raises:
            PriceUnavailableError: If price cannot be fetched.
            InsufficientSizeError: If quantity is below exchange minimums.
            DeltaHedgeTimeout: If order placement times out.
            DeltaHedgeError: If one leg fails and rollback is attempted.
            DeltaDriftExceeded: If fill quantities drift beyond tolerance.
        """
        async with self._lock:
            # 1. Get current price
            price = await self._ticker_service.get_price(perp_symbol)
            if price is None:
                price = await self._ticker_service.get_price(spot_symbol)
            if price is None:
                raise PriceUnavailableError(
                    f"No price available for {perp_symbol} or {spot_symbol}"
                )

            # 2. Calculate quantity
            quantity = self._position_sizer.calculate_matching_quantity(
                price=price,
                available_balance=available_balance,
                spot_instrument=spot_instrument,
                perp_instrument=perp_instrument,
            )
            if quantity is None:
                raise InsufficientSizeError(
                    f"Calculated quantity below exchange minimums for "
                    f"{spot_symbol}/{perp_symbol} at price {price}"
                )

            # 3. Create order requests
            spot_order = OrderRequest(
                symbol=spot_symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=quantity,
                category="spot",
            )
            perp_order = OrderRequest(
                symbol=perp_symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=quantity,
                category="linear",
            )

            # 4. Execute simultaneously with timeout
            spot_result: OrderResult | None = None
            perp_result: OrderResult | None = None

            try:
                spot_result, perp_result = await asyncio.wait_for(
                    asyncio.gather(
                        self._executor.place_order(spot_order),
                        self._executor.place_order(perp_order),
                    ),
                    timeout=self._settings.order_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "delta_hedge_timeout",
                    spot_symbol=spot_symbol,
                    perp_symbol=perp_symbol,
                    timeout=self._settings.order_timeout_seconds,
                )
                # Attempt to cancel any pending orders
                raise DeltaHedgeTimeout(
                    f"Order placement timed out after "
                    f"{self._settings.order_timeout_seconds}s for "
                    f"{spot_symbol}/{perp_symbol}"
                )
            except Exception as exc:
                # Partial failure: one leg may have succeeded
                logger.error(
                    "delta_hedge_partial_failure",
                    spot_symbol=spot_symbol,
                    perp_symbol=perp_symbol,
                    error=str(exc),
                )
                # Attempt rollback if one result exists
                if spot_result is not None and perp_result is None:
                    await self._rollback_leg(
                        spot_result, spot_symbol, "spot", OrderSide.SELL
                    )
                elif perp_result is not None and spot_result is None:
                    await self._rollback_leg(
                        perp_result, perp_symbol, "linear", OrderSide.BUY
                    )
                raise DeltaHedgeError(
                    f"Partial failure during delta hedge for "
                    f"{spot_symbol}/{perp_symbol}: {exc}"
                ) from exc

            # 5. Validate delta
            delta_status = self._delta_validator.validate(
                spot_qty=spot_result.filled_qty,
                perp_qty=perp_result.filled_qty,
            )
            if not delta_status.is_within_tolerance:
                logger.error(
                    "delta_drift_exceeded_on_open",
                    drift_pct=str(delta_status.drift_pct),
                    spot_qty=str(spot_result.filled_qty),
                    perp_qty=str(perp_result.filled_qty),
                )
                # Close both legs immediately
                await self._close_legs(
                    spot_symbol, perp_symbol,
                    spot_result.filled_qty, perp_result.filled_qty,
                )
                raise DeltaDriftExceeded(
                    f"Delta drift {delta_status.drift_pct} exceeds tolerance "
                    f"{self._settings.delta_drift_tolerance}"
                )

            # 6. Create position
            entry_fee = spot_result.fee + perp_result.fee
            position_id = uuid4().hex[:16]
            position = Position(
                id=position_id,
                spot_symbol=spot_symbol,
                perp_symbol=perp_symbol,
                side=PositionSide.SHORT,  # short perp + long spot
                quantity=spot_result.filled_qty,
                spot_entry_price=spot_result.filled_price,
                perp_entry_price=perp_result.filled_price,
                spot_order_id=spot_result.order_id,
                perp_order_id=perp_result.order_id,
                opened_at=time.time(),
                entry_fee_total=entry_fee,
            )
            self._positions[position_id] = position

            logger.info(
                "position_opened",
                position_id=position_id,
                spot_symbol=spot_symbol,
                perp_symbol=perp_symbol,
                quantity=str(position.quantity),
                spot_price=str(spot_result.filled_price),
                perp_price=str(perp_result.filled_price),
                entry_fee=str(entry_fee),
            )

            return position

    async def close_position(
        self, position_id: str
    ) -> tuple[OrderResult, OrderResult]:
        """Close a delta-neutral position by reversing both legs.

        Spot SELL + perp BUY (close short) executed simultaneously.

        Args:
            position_id: ID of the position to close.

        Returns:
            Tuple of (spot_result, perp_result) from closing orders.

        Raises:
            KeyError: If position_id not found.
            DeltaHedgeTimeout: If closing orders time out.
        """
        async with self._lock:
            position = self._positions.pop(position_id)

            spot_order = OrderRequest(
                symbol=position.spot_symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=position.quantity,
                category="spot",
            )
            perp_order = OrderRequest(
                symbol=position.perp_symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=position.quantity,
                category="linear",
            )

            try:
                spot_result, perp_result = await asyncio.wait_for(
                    asyncio.gather(
                        self._executor.place_order(spot_order),
                        self._executor.place_order(perp_order),
                    ),
                    timeout=self._settings.order_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # Put position back since close failed
                self._positions[position_id] = position
                raise DeltaHedgeTimeout(
                    f"Close order timed out for position {position_id}"
                )

            logger.info(
                "position_closed",
                position_id=position_id,
                spot_symbol=position.spot_symbol,
                perp_symbol=position.perp_symbol,
                quantity=str(position.quantity),
            )

            return spot_result, perp_result

    def get_open_positions(self) -> list[Position]:
        """Return list of all currently open positions.

        Returns:
            List of Position objects.
        """
        return list(self._positions.values())

    def get_position(self, position_id: str) -> Position | None:
        """Get a specific position by ID.

        Args:
            position_id: The position ID to look up.

        Returns:
            Position if found, None otherwise.
        """
        return self._positions.get(position_id)

    async def _rollback_leg(
        self,
        result: OrderResult,
        symbol: str,
        category: str,
        reverse_side: OrderSide,
    ) -> None:
        """Attempt to reverse a filled leg after partial failure.

        Args:
            result: The filled order result to reverse.
            symbol: Trading pair symbol.
            category: Order category ("spot" or "linear").
            reverse_side: The side for the reversal order.
        """
        try:
            reverse_order = OrderRequest(
                symbol=symbol,
                side=reverse_side,
                order_type=OrderType.MARKET,
                quantity=result.filled_qty,
                category=category,
            )
            await self._executor.place_order(reverse_order)
            logger.info(
                "rollback_success",
                original_order_id=result.order_id,
                symbol=symbol,
                category=category,
            )
        except Exception:
            logger.error(
                "rollback_failed",
                original_order_id=result.order_id,
                symbol=symbol,
                category=category,
                exc_info=True,
            )

    async def _close_legs(
        self,
        spot_symbol: str,
        perp_symbol: str,
        spot_qty: Decimal,
        perp_qty: Decimal,
    ) -> None:
        """Emergency close both legs (used when delta drift exceeds tolerance).

        Args:
            spot_symbol: Spot trading pair.
            perp_symbol: Perp trading pair.
            spot_qty: Spot quantity to sell.
            perp_qty: Perp quantity to buy back.
        """
        try:
            spot_close = OrderRequest(
                symbol=spot_symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=spot_qty,
                category="spot",
            )
            perp_close = OrderRequest(
                symbol=perp_symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=perp_qty,
                category="linear",
            )
            await asyncio.gather(
                self._executor.place_order(spot_close),
                self._executor.place_order(perp_close),
            )
            logger.info(
                "emergency_close_success",
                spot_symbol=spot_symbol,
                perp_symbol=perp_symbol,
            )
        except Exception:
            logger.error(
                "emergency_close_failed",
                spot_symbol=spot_symbol,
                perp_symbol=perp_symbol,
                exc_info=True,
            )
