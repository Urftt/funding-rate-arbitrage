"""Signal analysis module for composite strategy mode.

Provides data models and computation functions for multi-dimensional
funding rate opportunity assessment.
"""

from bot.signals.models import CompositeOpportunityScore, CompositeSignal, TrendDirection

__all__ = [
    "CompositeOpportunityScore",
    "CompositeSignal",
    "TrendDirection",
]
