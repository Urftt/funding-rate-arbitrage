"""Custom exceptions for the funding rate arbitrage bot.

All execution-layer and position-management exceptions live here
to avoid circular imports between modules.
"""


class BotError(Exception):
    """Base exception for all bot errors."""


class PriceUnavailableError(BotError):
    """Raised when a price is unavailable or stale for order execution."""


class DeltaHedgeTimeout(BotError):
    """Raised when simultaneous spot+perp order placement times out."""


class DeltaHedgeError(BotError):
    """Raised when one leg of a delta hedge fails (partial fill)."""


class DeltaDriftExceeded(BotError):
    """Raised when spot/perp fill quantities drift beyond tolerance."""


class InsufficientSizeError(BotError):
    """Raised when calculated position size is below exchange minimums."""
