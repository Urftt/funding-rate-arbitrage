"""Bybit exchange client implementation via ccxt async.

Wraps ccxt.async_support.bybit with proper initialization, market loading,
instrument info extraction, and async cleanup.
"""

from decimal import Decimal

import ccxt.async_support as ccxt_async

from bot.config import ExchangeSettings
from bot.exchange.client import ExchangeClient
from bot.exchange.types import InstrumentInfo
from bot.logging import get_logger

logger = get_logger(__name__)


class BybitClient(ExchangeClient):
    """Concrete Bybit exchange client using ccxt async."""

    def __init__(self, settings: ExchangeSettings) -> None:
        self._settings = settings

        config: dict = {
            "apiKey": settings.api_key.get_secret_value(),
            "secret": settings.api_secret.get_secret_value(),
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
            },
        }

        # Override URLs for Bybit Demo Trading API
        if settings.demo_trading:
            config["urls"] = {
                "api": {
                    "public": "https://api-demo.bybit.com",
                    "private": "https://api-demo.bybit.com",
                },
            }

        self._exchange = ccxt_async.bybit(config)
        self._markets: dict = {}

    @property
    def exchange(self) -> ccxt_async.bybit:
        """Access the underlying ccxt exchange instance."""
        return self._exchange

    async def connect(self) -> None:
        """Initialize connection by loading markets."""
        logger.info("connecting_to_bybit", demo=self._settings.demo_trading)
        self._markets = await self._exchange.load_markets()
        logger.info(
            "bybit_connected",
            market_count=len(self._markets),
            demo=self._settings.demo_trading,
        )

    async def close(self) -> None:
        """Clean up ccxt async resources. CRITICAL: must be called to avoid resource leaks."""
        logger.info("closing_bybit_connection")
        await self._exchange.close()
        logger.info("bybit_connection_closed")

    async def fetch_ticker(self, symbol: str) -> dict:
        """Fetch current ticker data for a single symbol."""
        return await self._exchange.fetch_ticker(symbol)

    async def fetch_tickers(
        self, symbols: list[str] | None = None, params: dict | None = None
    ) -> dict:
        """Fetch ticker data for multiple symbols."""
        return await self._exchange.fetch_tickers(symbols, params=params or {})

    async def fetch_perpetual_symbols(self) -> list[str]:
        """Return all linear perpetual swap symbols.

        Filters markets for those that are both linear and swap type,
        excluding spot, inverse, and option contracts.
        """
        if not self._markets:
            await self.load_markets()

        symbols = [
            symbol
            for symbol, market in self._markets.items()
            if market.get("linear") and market.get("swap")
        ]
        logger.debug("fetched_perpetual_symbols", count=len(symbols))
        return symbols

    async def get_instrument_info(self, symbol: str) -> InstrumentInfo:
        """Extract instrument constraints from cached market data.

        All numeric values are converted to Decimal for precision.
        """
        if not self._markets:
            await self.load_markets()

        market = self._markets.get(symbol)
        if not market:
            raise ValueError(f"Symbol {symbol} not found in loaded markets")

        limits = market.get("limits", {})
        precision = market.get("precision", {})
        amount_limits = limits.get("amount", {})
        cost_limits = limits.get("cost", {})

        return InstrumentInfo(
            symbol=symbol,
            min_qty=Decimal(str(amount_limits.get("min", 0))),
            max_qty=Decimal(str(amount_limits.get("max", 0))),
            qty_step=Decimal(str(precision.get("amount", 0))),
            min_notional=Decimal(str(cost_limits.get("min", 0) or 0)),
            tick_size=Decimal(str(precision.get("price", 0))),
        )

    async def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: float | None = None,
        params: dict | None = None,
    ) -> dict:
        """Place an order via ccxt."""
        logger.info(
            "creating_order",
            symbol=symbol,
            order_type=order_type,
            side=side,
            amount=amount,
        )
        return await self._exchange.create_order(
            symbol, order_type, side, amount, price, params=params or {}
        )

    async def cancel_order(
        self, order_id: str, symbol: str, params: dict | None = None
    ) -> dict:
        """Cancel an open order via ccxt."""
        logger.info("cancelling_order", order_id=order_id, symbol=symbol)
        return await self._exchange.cancel_order(order_id, symbol, params=params or {})

    async def fetch_balance(self) -> dict:
        """Fetch account balance via ccxt."""
        return await self._exchange.fetch_balance()

    async def load_markets(self) -> dict:
        """Load and cache market data from Bybit."""
        self._markets = await self._exchange.load_markets()
        return self._markets

    async def fetch_wallet_balance_raw(self) -> dict:
        """Fetch raw Bybit unified account wallet balance.

        Returns the first account entry from the Bybit wallet balance response,
        containing accountMMRate, totalMaintenanceMargin, totalEquity, and
        totalAvailableBalance fields.
        """
        balance = await self._exchange.fetch_balance(params={"type": "UNIFIED"})
        raw_info = balance.get("info", {})
        result_list = raw_info.get("result", {}).get("list", [])
        if result_list:
            return result_list[0]
        return {}

    def get_markets(self) -> dict:
        """Return cached markets dict loaded at connect() time."""
        return self._markets
