"""Shared data models for the funding rate arbitrage bot.

CRITICAL: All monetary values use Decimal. Never use float for prices, quantities, or fees.
See: .planning/phases/01-core-trading-engine/01-RESEARCH.md (Anti-Patterns)
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class OrderSide(str, Enum):
    """Order direction."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"


class PositionSide(str, Enum):
    """Position direction."""

    LONG = "long"
    SHORT = "short"


@dataclass
class FundingRateData:
    """Snapshot of funding rate data for a single perpetual pair."""

    symbol: str
    rate: Decimal
    next_funding_time: int  # Unix milliseconds
    interval_hours: int = 8
    mark_price: Decimal = Decimal("0")
    volume_24h: Decimal = Decimal("0")
    updated_at: float = field(default_factory=time.time)


@dataclass
class OrderRequest:
    """Request to place an order."""

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    category: str = "linear"  # "spot" or "linear"


@dataclass
class OrderResult:
    """Result of an executed order."""

    order_id: str
    symbol: str
    side: OrderSide
    filled_qty: Decimal
    filled_price: Decimal
    fee: Decimal
    timestamp: float
    is_simulated: bool = False


@dataclass
class Position:
    """A delta-neutral position (spot + perp pair)."""

    id: str
    spot_symbol: str
    perp_symbol: str
    side: PositionSide
    quantity: Decimal
    spot_entry_price: Decimal
    perp_entry_price: Decimal
    spot_order_id: str
    perp_order_id: str
    opened_at: float
    entry_fee_total: Decimal


@dataclass
class DeltaStatus:
    """Delta neutrality check result for a position."""

    position_id: str
    spot_qty: Decimal
    perp_qty: Decimal
    drift_pct: Decimal
    is_within_tolerance: bool
    checked_at: float


@dataclass
class OpportunityScore:
    """Ranked funding rate arbitrage opportunity for a single pair.

    Used by OpportunityRanker to evaluate and compare pairs for autonomous
    position entry. Net yield accounts for round-trip trading fees.
    """

    spot_symbol: str
    perp_symbol: str
    funding_rate: Decimal  # raw per-period rate
    funding_interval_hours: int  # 4 or 8
    volume_24h: Decimal
    net_yield_per_period: Decimal  # rate minus amortized round-trip fee
    annualized_yield: Decimal  # net_yield * periods_per_year
    passes_filters: bool  # volume, rate, spot-availability checks
