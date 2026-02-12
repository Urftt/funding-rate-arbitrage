"""Signal analysis data models for composite strategy mode.

CRITICAL: All score and rate values use Decimal. Never use float for signal computations.
See: .planning/phases/01-core-trading-engine/01-RESEARCH.md (Anti-Patterns)
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from bot.models import OpportunityScore


class TrendDirection(str, Enum):
    """Funding rate trend classification from EMA analysis."""

    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"


@dataclass
class CompositeSignal:
    """Complete composite signal with sub-signal breakdown for a single pair.

    Each field represents one dimension of the opportunity quality assessment.
    The composite score is a weighted combination of the sub-signals.
    """

    symbol: str
    score: Decimal  # Weighted composite score (0-1 range)
    rate_level: Decimal  # Normalized current funding rate (0-1)
    trend: TrendDirection  # Direction classification
    trend_score: Decimal  # Numeric trend contribution (0-1)
    persistence: Decimal  # Persistence score (0-1)
    basis_spread: Decimal  # Raw basis spread value
    basis_score: Decimal  # Normalized basis contribution (0-1)
    volume_ok: bool  # Passes volume filter
    passes_entry: bool  # composite score >= entry threshold AND volume_ok


@dataclass
class CompositeOpportunityScore:
    """Wraps OpportunityScore with composite signal data for orchestrator compatibility.

    Allows the orchestrator's _open_profitable_positions to access
    .opportunity.spot_symbol, .opportunity.perp_symbol, etc. while also
    having the composite signal breakdown.
    """

    opportunity: OpportunityScore  # The v1.0-compatible score
    signal: CompositeSignal  # The composite signal breakdown
