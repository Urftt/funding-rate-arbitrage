"""Entry point for the funding rate arbitrage bot."""

import asyncio

from bot.config import AppSettings
from bot.logging import get_logger, setup_logging


async def run() -> None:
    """Run the funding rate arbitrage bot."""
    settings = AppSettings()
    setup_logging(settings.log_level)
    logger = get_logger("bot.main")
    logger.info("funding_rate_arbitrage_starting", mode=settings.trading.mode)
    # Orchestrator will be wired here in Plan 05
    logger.info("funding_rate_arbitrage_stopped")


def main() -> None:
    """Synchronous entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
