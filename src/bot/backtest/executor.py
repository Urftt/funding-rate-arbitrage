"""Backtest executor with historical price fills.

Implements the Executor ABC for backtest mode. Instead of reading prices from
TickerService, maintains an internal price dict that the backtest engine
updates at each simulated timestamp. Applies configurable slippage and
fee simulation identical to PaperExecutor.

BKTS-02: Reuse production FeeCalculator/PnLTracker/PositionManager by
implementing the same Executor interface.
"""

import time
from decimal import Decimal
from uuid import uuid4

from bot.config import FeeSettings
from bot.execution.executor import Executor
from bot.logging import get_logger
from bot.models import OrderRequest, OrderResult, OrderSide

logger = get_logger(__name__)


class BacktestExecutor(Executor):
    """Simulated order executor for backtesting with historical prices.

    Prices are injected via set_prices() before each simulated timestamp,
    rather than fetched from a live TickerService. This allows PositionManager
    and other production components to operate identically in backtest mode.

    Args:
        fee_settings: Fee rates for spot and perp taker fees.
        slippage_bps: Slippage in basis points (default 5 = 0.05%).
    """

    def __init__(
        self,
        fee_settings: FeeSettings,
        slippage_bps: Decimal = Decimal("5"),
    ) -> None:
        self._fee_settings = fee_settings
        self._slippage = slippage_bps / Decimal("10000")  # Convert bps to ratio
        self._current_prices: dict[str, Decimal] = {}
        self._current_time: float = time.time()
        self._fill_count: int = 0

    def set_prices(self, prices: dict[str, Decimal]) -> None:
        """Update the current price snapshot for all symbols.

        Called by the backtest engine before processing each timestamp.

        Args:
            prices: Dict mapping symbol to current price at this timestamp.
        """
        self._current_prices.update(prices)

    def set_current_time(self, timestamp: float) -> None:
        """Set the current simulated timestamp.

        Used for OrderResult.timestamp and logging.

        Args:
            timestamp: Unix timestamp in seconds for the current backtest step.
        """
        self._current_time = timestamp

    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Fill an order at the current historical price with slippage.

        Uses the price set via set_prices() for the requested symbol.
        Applies slippage in the same direction as PaperExecutor (higher for
        buys, lower for sells). Fee calculation matches PaperExecutor.

        Args:
            request: Order parameters (symbol, side, type, quantity, category).

        Returns:
            OrderResult with historical fill details and is_simulated=True.

        Raises:
            KeyError: If no price has been set for the requested symbol.
        """
        price = self._current_prices.get(request.symbol)
        if price is None:
            raise KeyError(
                f"No price set for {request.symbol}. "
                f"Call set_prices() before placing orders."
            )

        # Apply slippage (same model as PaperExecutor)
        if request.side == OrderSide.BUY:
            fill_price = price * (Decimal("1") + self._slippage)
        else:
            fill_price = price * (Decimal("1") - self._slippage)

        # Calculate fee (same model as PaperExecutor)
        if request.category == "spot":
            fee_rate = self._fee_settings.spot_taker
        else:
            fee_rate = self._fee_settings.perp_taker

        fee = request.quantity * fill_price * fee_rate

        order_id = f"bt_{uuid4().hex[:12]}"
        self._fill_count += 1

        logger.debug(
            "backtest_order_filled",
            order_id=order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=str(request.quantity),
            fill_price=str(fill_price),
            fee=str(fee),
            category=request.category,
            sim_time=self._current_time,
        )

        return OrderResult(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            filled_qty=request.quantity,
            filled_price=fill_price,
            fee=fee,
            timestamp=self._current_time,
            is_simulated=True,
        )

    async def cancel_order(
        self, order_id: str, symbol: str, category: str = "linear"
    ) -> bool:
        """Cancel a backtest order (always succeeds since fills are instant).

        Args:
            order_id: The backtest order ID.
            symbol: The trading pair symbol.
            category: Order category.

        Returns:
            Always True (backtest orders are instant-fill).
        """
        return True
