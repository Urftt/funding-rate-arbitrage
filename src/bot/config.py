"""Configuration system using pydantic-settings with environment variable loading."""

from dataclasses import dataclass
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
    scan_interval: int = 60  # seconds between autonomous scan cycles


class RiskSettings(BaseSettings):
    """Risk management parameters for Phase 2 multi-pair intelligence."""

    model_config = SettingsConfigDict(env_prefix="RISK_")

    max_position_size_per_pair: Decimal = Decimal("1000")  # USD per pair
    max_simultaneous_positions: int = 5
    exit_funding_rate: Decimal = Decimal("0.0001")  # 0.01%/period -- close below this
    margin_alert_threshold: Decimal = Decimal("0.8")  # alert at 80% MMR
    margin_critical_threshold: Decimal = Decimal("0.9")  # emergency at 90% MMR
    min_volume_24h: Decimal = Decimal("1000000")  # $1M minimum
    min_holding_periods: int = 3  # minimum funding periods to hold
    paper_virtual_equity: Decimal = Decimal("10000")  # for paper mode margin simulation


class FeeSettings(BaseSettings):
    """Bybit fee structure (Non-VIP base tier)."""

    model_config = SettingsConfigDict(env_prefix="FEES_")

    spot_taker: Decimal = Decimal("0.001")  # 0.1%
    spot_maker: Decimal = Decimal("0.001")  # 0.1%
    perp_taker: Decimal = Decimal("0.00055")  # 0.055%
    perp_maker: Decimal = Decimal("0.0002")  # 0.02%


class DashboardSettings(BaseSettings):
    """Dashboard server configuration."""

    model_config = SettingsConfigDict(env_prefix="DASHBOARD_")

    host: str = "0.0.0.0"
    port: int = 8080
    enabled: bool = True
    update_interval: int = 5  # seconds between WebSocket pushes


class HistoricalDataSettings(BaseSettings):
    """Historical data collection configuration.

    Controls data fetching behavior, storage location, and pair selection.
    All fields configurable via HISTORICAL_ environment variable prefix.
    """

    model_config = SettingsConfigDict(env_prefix="HISTORICAL_")

    enabled: bool = True
    db_path: str = "data/historical.db"
    lookback_days: int = 365
    ohlcv_interval: str = "1h"
    top_pairs_count: int = 20
    pair_reeval_interval_hours: int = 168  # weekly
    max_retries: int = 5
    retry_base_delay: float = 1.0
    fetch_batch_delay: float = 0.1


@dataclass
class RuntimeConfig:
    """Mutable runtime config overlay. Non-None fields override BaseSettings values.

    Used by the dashboard to update strategy parameters without restarting.
    Changes are applied at the start of each orchestrator cycle.
    """

    min_funding_rate: Decimal | None = None
    max_position_size_usd: Decimal | None = None
    exit_funding_rate: Decimal | None = None
    max_simultaneous_positions: int | None = None
    max_position_size_per_pair: Decimal | None = None
    min_volume_24h: Decimal | None = None
    scan_interval: int | None = None


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
    risk: RiskSettings = RiskSettings()
    dashboard: DashboardSettings = DashboardSettings()
    historical: HistoricalDataSettings = HistoricalDataSettings()
