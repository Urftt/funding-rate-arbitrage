"""Shared test fixtures for the funding rate arbitrage bot."""

import pytest

from bot.config import AppSettings, ExchangeSettings, FeeSettings, TradingSettings


@pytest.fixture
def mock_settings() -> AppSettings:
    """Return AppSettings with test defaults (paper mode, dummy API keys)."""
    return AppSettings(
        log_level="DEBUG",
        exchange=ExchangeSettings(
            api_key="test-api-key",  # type: ignore[arg-type]
            api_secret="test-api-secret",  # type: ignore[arg-type]
            testnet=True,
            demo_trading=False,
        ),
        trading=TradingSettings(
            mode="paper",
        ),
        fees=FeeSettings(),
    )
