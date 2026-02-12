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
    strategy_mode: Literal["simple", "composite"] = "simple"  # Default preserves v1.0
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


class SignalSettings(BaseSettings):
    """Signal analysis configuration for composite strategy mode.

    Controls EMA trend detection, persistence scoring, basis spread weighting,
    volume trend filtering, composite weight allocation, and entry/exit thresholds.
    All fields configurable via SIGNAL_ environment variable prefix.
    """

    model_config = SettingsConfigDict(env_prefix="SIGNAL_")

    # EMA trend detection
    trend_ema_span: int = 6  # Number of funding periods for EMA
    trend_stable_threshold: Decimal = Decimal("0.00005")  # Min EMA diff for rising/falling

    # Persistence scoring
    persistence_threshold: Decimal = Decimal("0.0003")  # Rate threshold for "elevated"
    persistence_max_periods: int = 30  # Normalize count against this

    # Basis spread
    basis_weight_cap: Decimal = Decimal("0.01")  # Cap basis contribution at 1%

    # Volume trend
    volume_lookback_days: int = 7  # Days for recent volume average
    volume_decline_ratio: Decimal = Decimal("0.7")  # Flag if recent < 70% of prior

    # Composite weights (must sum to ~1.0)
    weight_rate_level: Decimal = Decimal("0.35")  # Rate level weight
    weight_trend: Decimal = Decimal("0.25")  # Trend weight
    weight_persistence: Decimal = Decimal("0.25")  # Persistence weight
    weight_basis: Decimal = Decimal("0.15")  # Basis weight

    # Entry/exit thresholds for composite score
    entry_threshold: Decimal = Decimal("0.5")  # Min composite score to enter
    exit_threshold: Decimal = Decimal("0.3")  # Close when score drops below

    # Rate normalization
    rate_normalization_cap: Decimal = Decimal("0.003")  # Cap for normalizing rate to 0-1


class BacktestSettings(BaseSettings):
    """Backtest engine configuration.

    Controls default parameters for backtest runs including initial capital,
    slippage simulation, and concurrency limits.
    All fields configurable via BACKTEST_ environment variable prefix.
    """

    model_config = SettingsConfigDict(env_prefix="BACKTEST_")

    default_initial_capital: Decimal = Decimal("10000")
    slippage_bps: Decimal = Decimal("5")  # 5 basis points = 0.05%
    max_concurrent_positions: int = 5


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
    signal: SignalSettings = SignalSettings()
    backtest: BacktestSettings = BacktestSettings()
