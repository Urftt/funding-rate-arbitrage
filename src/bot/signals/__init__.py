"""Signal analysis module for composite strategy mode.

Provides data models and computation functions for multi-dimensional
funding rate opportunity assessment. Includes sub-signal modules (trend,
persistence, basis, volume), the composite aggregator, and the SignalEngine
that orchestrates all sub-signals into ranked composite scores.
"""

from bot.signals.basis import compute_basis_spread, normalize_basis_score
from bot.signals.composite import compute_composite_score, normalize_rate_level
from bot.signals.engine import SignalEngine
from bot.signals.models import CompositeOpportunityScore, CompositeSignal, TrendDirection
from bot.signals.persistence import compute_persistence_score
from bot.signals.trend import classify_trend, compute_ema
from bot.signals.volume import compute_volume_trend

__all__ = [
    "CompositeOpportunityScore",
    "CompositeSignal",
    "SignalEngine",
    "TrendDirection",
    "classify_trend",
    "compute_basis_spread",
    "compute_composite_score",
    "compute_ema",
    "compute_persistence_score",
    "compute_volume_trend",
    "normalize_basis_score",
    "normalize_rate_level",
]
