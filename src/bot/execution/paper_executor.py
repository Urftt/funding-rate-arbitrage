"""Paper trading executor with simulated fills.

Uses TickerService for current market prices and applies configurable
slippage and fee simulation. All fills are instant (market order simulation).

PAPR-01: Paper mode simulates realistic execution.
PAPR-02: Implements the same Executor ABC as LiveExecutor.
"""

import time
from decimal import Decimal
from uuid import uuid4

from bot.config import FeeSettings
from bot.exceptions import PriceUnavailableError
from bot.execution.executor import Executor
from bot.logging import get_logger
from bot.market_data.ticker_service import TickerService
from bot.models import OrderRequest, OrderResult, OrderSide

logger = get_logger(__name__)


def simulate_paper_margin(
    open_position_count: int,
    max_position_size_usd: Decimal,
    virtual_equity: Decimal,
) -> dict:
    """Simulate margin data for paper trading mode.

    Returns a dict mimicking fetch_wallet_balance_raw() shape so the
    RiskManager can evaluate margin conditions in paper mode without
    requiring a live exchange connection.

    Args:
        open_position_count: Number of currently open positions.
        max_position_size_usd: Maximum position size per pair in USD.
        virtual_equity: Total virtual equity for paper account.

    Returns:
        Dict with accountMMRate, totalMaintenanceMargin, totalEquity,
        and totalAvailableBalance as string values.
    """
    total_used = max_position_size_usd * Decimal(str(open_position_count))
    mm_rate = total_used / virtual_equity if virtual_equity > 0 else Decimal("0")
    return {
        "accountMMRate": str(mm_rate),
        "totalMaintenanceMargin": str(total_used * Decimal("0.05")),
        "totalEquity": str(virtual_equity),
        "totalAvailableBalance": str(virtual_equity - total_used),
    }


# Simulated slippage: 0.05% (5 basis points)
_SLIPPAGE = Decimal("0.0005")

# Maximum price age in seconds before considered stale
_MAX_PRICE_AGE_SECONDS = 60.0


class PaperExecutor(Executor):
    """Simulated order executor for paper trading.

    Fetches current prices from TickerService, applies slippage and fees,
    and tracks virtual balance changes. All results have is_simulated=True.

    Args:
        ticker_service: Shared price cache for current market prices.
        fee_settings: Fee rates for spot and perp taker fees.
    """

    def __init__(
        self, ticker_service: TickerService, fee_settings: FeeSettings
    ) -> None:
        self._ticker_service = ticker_service
        self._fee_settings = fee_settings
        self._virtual_balances: dict[str, Decimal] = {}

    def set_initial_balance(self, currency: str, amount: Decimal) -> None:
        """Set starting virtual balance for a currency.

        Args:
            currency: Currency code (e.g., "USDT").
            amount: Starting balance amount.
        """
        self._virtual_balances[currency] = amount

    def get_virtual_balance(self) -> dict[str, Decimal]:
        """Return current virtual balances.

        Returns:
            Dict mapping currency codes to Decimal balances.
        """
        return dict(self._virtual_balances)

    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Simulate order execution using current market prices.

        1. Fetch price from TickerService.
        2. Check staleness (>60s raises PriceUnavailableError).
        3. Apply slippage (higher for buys, lower for sells).
        4. Calculate fee using appropriate taker rate.
        5. Update virtual balances.
        6. Return OrderResult with is_simulated=True.

        Args:
            request: Order parameters.

        Returns:
            Simulated OrderResult.

        Raises:
            PriceUnavailableError: If price is None or stale.
        """
        price = await self._ticker_service.get_price(request.symbol)
        if price is None:
            raise PriceUnavailableError(
                f"No price available for {request.symbol}"
            )

        is_stale = await self._ticker_service.is_stale(
            request.symbol, max_age_seconds=_MAX_PRICE_AGE_SECONDS
        )
        if is_stale:
            raise PriceUnavailableError(
                f"Price for {request.symbol} is stale (>{_MAX_PRICE_AGE_SECONDS}s old)"
            )

        # Apply slippage
        if request.side == OrderSide.BUY:
            fill_price = price * (Decimal("1") + _SLIPPAGE)
        else:
            fill_price = price * (Decimal("1") - _SLIPPAGE)

        # Calculate fee
        if request.category == "spot":
            fee_rate = self._fee_settings.spot_taker
        else:
            fee_rate = self._fee_settings.perp_taker

        fee = request.quantity * fill_price * fee_rate

        # Update virtual balances (quote currency tracking)
        cost = request.quantity * fill_price + fee
        if request.side == OrderSide.BUY:
            # Buying: deduct cost from quote currency
            for currency in self._virtual_balances:
                self._virtual_balances[currency] -= cost
                break  # Deduct from first available currency
        else:
            # Selling: add proceeds minus fee to quote currency
            proceeds = request.quantity * fill_price - fee
            for currency in self._virtual_balances:
                self._virtual_balances[currency] += proceeds
                break

        order_id = f"paper_{uuid4().hex[:12]}"

        logger.info(
            "paper_order_filled",
            order_id=order_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=str(request.quantity),
            fill_price=str(fill_price),
            fee=str(fee),
            category=request.category,
        )

        return OrderResult(
            order_id=order_id,
            symbol=request.symbol,
            side=request.side,
            filled_qty=request.quantity,
            filled_price=fill_price,
            fee=fee,
            timestamp=time.time(),
            is_simulated=True,
        )

    async def cancel_order(
        self, order_id: str, symbol: str, category: str = "linear"
    ) -> bool:
        """Cancel a paper order (always succeeds since fills are instant).

        Args:
            order_id: The paper order ID.
            symbol: The trading pair symbol.
            category: Order category.

        Returns:
            Always True (paper orders are instant-fill market orders).
        """
        logger.info(
            "paper_order_cancelled",
            order_id=order_id,
            symbol=symbol,
            category=category,
        )
        return True
