"""Live trading executor via exchange client.

Delegates all order operations to the ExchangeClient (ccxt wrapper).
All monetary values are converted through Decimal(str(value)) to avoid
float precision loss.

PAPR-02: Implements the same Executor ABC as PaperExecutor.
"""

import time
from decimal import Decimal

from bot.exceptions import PriceUnavailableError
from bot.exchange.client import ExchangeClient
from bot.execution.executor import Executor
from bot.logging import get_logger
from bot.models import OrderRequest, OrderResult, OrderSide

logger = get_logger(__name__)


class LiveExecutor(Executor):
    """Real order executor that delegates to an exchange client.

    Args:
        exchange_client: The exchange client to place real orders through.
    """

    def __init__(self, exchange_client: ExchangeClient) -> None:
        self._exchange_client = exchange_client

    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Place a real order on the exchange.

        1. Delegate to exchange_client.create_order().
        2. Parse ccxt order result into OrderResult.
        3. All amounts converted via Decimal(str(value)).

        Args:
            request: Order parameters.

        Returns:
            OrderResult from exchange fill.

        Raises:
            Exception: Any exchange errors propagated from ccxt.
        """
        params: dict = {"category": request.category}

        result = await self._exchange_client.create_order(
            symbol=request.symbol,
            order_type=request.order_type.value,
            side=request.side.value,
            amount=float(request.quantity),
            price=float(request.price) if request.price is not None else None,
            params=params,
        )

        # Parse ccxt order result -- all values through Decimal(str()) to avoid float
        order_id = str(result.get("id", ""))
        filled_qty = Decimal(str(result.get("filled", 0)))
        average_price = result.get("average") or result.get("price")
        filled_price = (
            Decimal(str(average_price)) if average_price else Decimal("0")
        )

        # Fee extraction from ccxt result
        fee_info = result.get("fee", {})
        fee_cost = fee_info.get("cost", 0) if fee_info else 0
        fee = Decimal(str(fee_cost)) if fee_cost else Decimal("0")

        timestamp = result.get("timestamp")
        ts = float(timestamp) / 1000.0 if timestamp else time.time()

        logger.info(
            "live_order_filled",
            order_id=order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=str(filled_qty),
            fill_price=str(filled_price),
            fee=str(fee),
            category=request.category,
        )

        return OrderResult(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            filled_qty=filled_qty,
            filled_price=filled_price,
            fee=fee,
            timestamp=ts,
            is_simulated=False,
        )

    async def cancel_order(
        self, order_id: str, symbol: str, category: str = "linear"
    ) -> bool:
        """Cancel an order on the exchange.

        Args:
            order_id: The exchange order ID.
            symbol: The trading pair symbol.
            category: Order category.

        Returns:
            True if cancellation succeeded, False otherwise.
        """
        try:
            await self._exchange_client.cancel_order(
                order_id=order_id,
                symbol=symbol,
                params={"category": category},
            )
            logger.info(
                "live_order_cancelled",
                order_id=order_id,
                symbol=symbol,
                category=category,
            )
            return True
        except Exception:
            logger.warning(
                "live_order_cancel_failed",
                order_id=order_id,
                symbol=symbol,
                category=category,
                exc_info=True,
            )
            return False
