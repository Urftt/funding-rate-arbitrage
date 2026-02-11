"""Configuration system using pydantic-settings with environment variable loading."""

from decimal import Decimal
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExchangeSettings(BaseSettings):
    """Bybit exchange connection settings."""

    model_config = SettingsConfigDict(env_prefix="BYBIT_")

    api_key: SecretStr = SecretStr("")
    api_secret: SecretStr = SecretStr("")
    testnet: bool = False
    demo_trading: bool = False


class TradingSettings(BaseSettings):
    """Trading strategy parameters."""

    model_config = SettingsConfigDict(env_prefix="TRADING_")

    mode: Literal["paper", "live"] = "paper"
    max_position_size_usd: Decimal = Decimal("1000")
    min_funding_rate: Decimal = Decimal("0.0003")  # 0.03%/8h minimum viable per research
    delta_drift_tolerance: Decimal = Decimal("0.02")  # 2% max
    order_timeout_seconds: float = 5.0


class FeeSettings(BaseSettings):
    """Bybit fee structure (Non-VIP base tier)."""

    model_config = SettingsConfigDict(env_prefix="FEES_")

    spot_taker: Decimal = Decimal("0.001")  # 0.1%
    spot_maker: Decimal = Decimal("0.001")  # 0.1%
    perp_taker: Decimal = Decimal("0.00055")  # 0.055%
    perp_maker: Decimal = Decimal("0.0002")  # 0.02%


class AppSettings(BaseSettings):
    """Root application settings, composing all sub-settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    log_level: str = "INFO"
    exchange: ExchangeSettings = ExchangeSettings()
    trading: TradingSettings = TradingSettings()
    fees: FeeSettings = FeeSettings()
