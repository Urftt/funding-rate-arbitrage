"""Abstract executor interface.

Defines the contract for order execution. Both PaperExecutor and LiveExecutor
implement this ABC, ensuring strategy code is identical regardless of trading
mode (PAPR-02 requirement).
"""

from abc import ABC, abstractmethod

from bot.models import OrderRequest, OrderResult


class Executor(ABC):
    """Abstract base class for order executors.

    All strategy and position management code depends ONLY on this interface.
    The concrete executor (paper or live) is injected at startup based on
    TradingSettings.mode.
    """

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Execute an order and return the fill result.

        Args:
            request: Order parameters (symbol, side, type, quantity, category).

        Returns:
            OrderResult with fill details (price, qty, fee, order_id).

        Raises:
            PriceUnavailableError: If current price cannot be determined.
        """
        ...

    @abstractmethod
    async def cancel_order(
        self, order_id: str, symbol: str, category: str = "linear"
    ) -> bool:
        """Attempt to cancel an open order.

        Args:
            order_id: The exchange order ID to cancel.
            symbol: The trading pair symbol.
            category: Order category ("spot" or "linear").

        Returns:
            True if cancellation succeeded, False otherwise.
        """
        ...
