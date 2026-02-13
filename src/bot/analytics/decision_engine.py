"""Decision engine for computing rate percentiles, signal breakdowns, and action labels.

Bridges PairAnalyzer (historical stats), SignalEngine (composite signals),
and FundingMonitor (live rates) into structured DecisionContext objects.
Used by the dashboard decision context API endpoints (Phase 11).

Core flow:
  1. Fetch historical rates and pair stats for a symbol
  2. Get current live funding rate from FundingMonitor
  3. Compute percentile rank via bisect on sorted historical rates
  4. Classify trend via EMA analysis
  5. Optionally include pre-computed signal breakdown
  6. Classify action label from evidence thresholds
  7. Cache result with TTL to avoid redundant computation

CRITICAL: All computations use Decimal. Never use float for rate/score values.
"""

from __future__ import annotations

import bisect
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from bot.signals.models import CompositeSignal, TrendDirection
from bot.signals.trend import classify_trend

if TYPE_CHECKING:
    from bot.analytics.pair_analyzer import PairAnalyzer
    from bot.data.store import HistoricalDataStore
    from bot.market_data.funding_monitor import FundingMonitor
    from bot.signals.engine import SignalEngine

logger = structlog.get_logger(__name__)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_QUANTIZE_1DP = Decimal("0.1")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RateContext:
    """Historical context for a current funding rate.

    Provides statistical positioning of the current rate relative to
    historical observations: percentile rank, trend direction, z-score,
    and comparison to average/median.
    """

    current_rate: Decimal
    percentile: Decimal
    trend: TrendDirection
    avg_rate: Decimal
    median_rate: Decimal
    std_dev: Decimal
    is_above_average: bool
    z_score: Decimal

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict with Decimal values as strings."""
        return {
            "current_rate": str(self.current_rate),
            "percentile": str(self.percentile),
            "trend": self.trend.value,
            "avg_rate": str(self.avg_rate),
            "median_rate": str(self.median_rate),
            "std_dev": str(self.std_dev),
            "is_above_average": self.is_above_average,
            "z_score": str(self.z_score),
        }


@dataclass
class SignalBreakdown:
    """Sub-signal contribution breakdown for display.

    Mirrors the CompositeSignal fields from the SignalEngine, structured
    for direct rendering in the dashboard UI.
    """

    composite_score: Decimal
    rate_level: Decimal
    trend_score: Decimal
    persistence: Decimal
    basis_score: Decimal
    volume_ok: bool
    weights: dict[str, str]

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict with Decimal values as strings."""
        return {
            "composite_score": str(self.composite_score),
            "rate_level": str(self.rate_level),
            "trend_score": str(self.trend_score),
            "persistence": str(self.persistence),
            "basis_score": str(self.basis_score),
            "volume_ok": self.volume_ok,
            "weights": self.weights,
        }


@dataclass
class ActionLabel:
    """Recommended action with confidence level and evidence-based reasons.

    Labels: "Strong opportunity", "Moderate opportunity", "Below average",
    "Not recommended", or "Insufficient data".
    """

    label: str
    confidence: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        return {
            "label": self.label,
            "confidence": self.confidence,
            "reasons": self.reasons,
        }


@dataclass
class DecisionContext:
    """Complete decision context for a single trading pair.

    Combines rate context, optional signal breakdown, and action label
    into a single structure for API transport and UI rendering.
    """

    symbol: str
    rate_context: RateContext
    signal_breakdown: SignalBreakdown | None
    action: ActionLabel
    has_sufficient_data: bool

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        return {
            "symbol": self.symbol,
            "rate_context": self.rate_context.to_dict(),
            "signal_breakdown": self.signal_breakdown.to_dict() if self.signal_breakdown else None,
            "action": self.action.to_dict(),
            "has_sufficient_data": self.has_sufficient_data,
        }


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------


def compute_rate_percentile(
    current_rate: Decimal,
    sorted_rates: list[Decimal],
) -> Decimal:
    """Compute the percentile rank of current_rate in sorted historical rates.

    Uses bisect_left for O(log n) insertion point lookup, then converts
    the position to a 0-100 percentile value.

    Args:
        current_rate: The current live funding rate.
        sorted_rates: Historical funding rates sorted ascending.

    Returns:
        Percentile as Decimal in [0, 100] range, quantized to 1 decimal place.
        Returns 50.0 if sorted_rates is empty.
    """
    if not sorted_rates:
        return Decimal("50.0")

    n = len(sorted_rates)
    position = bisect.bisect_left(sorted_rates, current_rate)
    percentile = (Decimal(position) / Decimal(n)) * _HUNDRED
    return percentile.quantize(_QUANTIZE_1DP)


def classify_action(
    percentile: Decimal,
    composite_score: Decimal | None,
    has_sufficient_data: bool,
    trend: TrendDirection,
) -> ActionLabel:
    """Classify a pair into an action label based on evidence.

    Thresholds (standard quartile boundaries):
    - Strong: percentile >= 75 AND trend != FALLING AND (score >= 0.5 or None)
    - Moderate: percentile >= 50 AND (score >= 0.4 or None)
    - Below average: percentile >= 25
    - Not recommended: percentile < 25

    Args:
        percentile: Rate percentile rank (0-100).
        composite_score: Composite signal score (0-1), or None if unavailable.
        has_sufficient_data: Whether minimum historical data threshold is met.
        trend: Current trend direction.

    Returns:
        ActionLabel with label, confidence, and evidence-based reasons.
    """
    if not has_sufficient_data:
        return ActionLabel(
            label="Insufficient data",
            confidence="low",
            reasons=["Less than 30 historical data points available"],
        )

    reasons: list[str] = []

    # Build reasons from evidence
    if percentile >= Decimal("75"):
        reasons.append(f"Current rate is in the top {100 - int(percentile)}% historically")
    elif percentile >= Decimal("50"):
        reasons.append(f"Current rate is above the historical median (P{int(percentile)})")
    else:
        reasons.append(f"Current rate is below historical median (P{int(percentile)})")

    if trend == TrendDirection.RISING:
        reasons.append("Funding rate trend is rising")
    elif trend == TrendDirection.FALLING:
        reasons.append("Funding rate trend is falling")

    if composite_score is not None:
        if composite_score >= Decimal("0.6"):
            reasons.append(f"Strong composite signal score ({composite_score})")
        elif composite_score >= Decimal("0.4"):
            reasons.append(f"Moderate composite signal score ({composite_score})")
        else:
            reasons.append(f"Weak composite signal score ({composite_score})")

    # Classify using threshold tiers
    if (
        percentile >= Decimal("75")
        and trend != TrendDirection.FALLING
        and (composite_score is None or composite_score >= Decimal("0.5"))
    ):
        return ActionLabel(label="Strong opportunity", confidence="high", reasons=reasons)

    if percentile >= Decimal("50") and (
        composite_score is None or composite_score >= Decimal("0.4")
    ):
        return ActionLabel(label="Moderate opportunity", confidence="medium", reasons=reasons)

    if percentile >= Decimal("25"):
        return ActionLabel(label="Below average", confidence="medium", reasons=reasons)

    return ActionLabel(label="Not recommended", confidence="high", reasons=reasons)


# ---------------------------------------------------------------------------
# DecisionEngine service
# ---------------------------------------------------------------------------


class DecisionEngine:
    """Produces decision context by combining PairAnalyzer, SignalEngine, and FundingMonitor.

    Bridges three data sources into structured DecisionContext objects:
    - PairAnalyzer: historical statistics (avg, median, std dev, data sufficiency)
    - FundingMonitor: current live funding rates
    - SignalEngine: composite signal scores (optional, via set_latest_signals)
    - HistoricalDataStore: raw historical rates for percentile computation

    Results are cached with a configurable TTL to avoid redundant computation
    during frequent dashboard update cycles.

    Args:
        pair_analyzer: Service for historical pair statistics.
        signal_engine: Composite signal engine (optional).
        funding_monitor: Live funding rate monitor (optional).
        data_store: Historical data store for raw rate queries (optional).
        cache_ttl_seconds: Cache time-to-live in seconds (default 120).
    """

    def __init__(
        self,
        pair_analyzer: PairAnalyzer,
        signal_engine: SignalEngine | None = None,
        funding_monitor: FundingMonitor | None = None,
        data_store: HistoricalDataStore | None = None,
        cache_ttl_seconds: int = 120,
    ) -> None:
        self._pair_analyzer = pair_analyzer
        self._signal_engine = signal_engine
        self._funding_monitor = funding_monitor
        self._data_store = data_store
        self._cache: dict[str, tuple[float, DecisionContext]] = {}
        self._ttl = cache_ttl_seconds
        self._latest_signals: dict[str, CompositeSignal] = {}

    def set_latest_signals(self, signals: dict[str, CompositeSignal]) -> None:
        """Update the latest pre-computed signal data.

        Called by the update loop to provide fresh CompositeSignal objects
        without requiring the DecisionEngine to call the SignalEngine directly
        (which would need a markets dict and add coupling).

        Args:
            signals: Dict mapping perp symbol to CompositeSignal.
        """
        self._latest_signals = signals

    async def get_decision_context(
        self,
        symbol: str,
        since_ms: int | None = None,
    ) -> DecisionContext:
        """Compute or retrieve cached decision context for a single pair.

        Steps:
        1. Check cache; return if fresh
        2. Fetch pair stats and historical rates
        3. Get current live rate (or fall back to avg_rate)
        4. Compute percentile, trend, z-score
        5. Build optional signal breakdown from pre-computed signals
        6. Classify action label
        7. Cache and return

        Args:
            symbol: Trading pair symbol (e.g., "BTC/USDT:USDT").
            since_ms: Optional start timestamp filter for historical data.

        Returns:
            DecisionContext with rate context, optional signal breakdown, and action label.
        """
        cache_key = f"{symbol}:{since_ms}"
        now = time.time()

        if cache_key in self._cache:
            cached_time, cached_ctx = self._cache[cache_key]
            if now - cached_time < self._ttl:
                return cached_ctx

        context = await self._compute_context(symbol, since_ms)
        self._cache[cache_key] = (now, context)
        return context

    async def get_all_decision_contexts(
        self,
        since_ms: int | None = None,
    ) -> dict[str, DecisionContext]:
        """Compute decision contexts for all pairs with live funding rates.

        Gets the list of live funding rates from FundingMonitor and computes
        a DecisionContext for each (up to 30 pairs). Errors on individual
        pairs are logged and skipped.

        Args:
            since_ms: Optional start timestamp filter for historical data.

        Returns:
            Dict mapping symbol to DecisionContext.
        """
        if self._funding_monitor is None:
            logger.warning("decision_engine_no_funding_monitor")
            return {}

        live_rates = self._funding_monitor.get_all_funding_rates()
        results: dict[str, DecisionContext] = {}

        for fr in live_rates[:30]:
            try:
                ctx = await self.get_decision_context(fr.symbol, since_ms)
                results[fr.symbol] = ctx
            except Exception as e:
                logger.debug(
                    "decision_context_error",
                    symbol=fr.symbol,
                    error=str(e),
                )

        return results

    async def _compute_context(
        self,
        symbol: str,
        since_ms: int | None,
    ) -> DecisionContext:
        """Compute a fresh DecisionContext for a symbol.

        Handles graceful degradation when dependencies are unavailable.
        """
        # 1. Get pair stats (avg, median, std_dev, has_sufficient_data)
        pair_detail = await self._pair_analyzer.get_pair_stats(symbol, since_ms=since_ms)
        stats = pair_detail.stats

        # 2. Get sorted historical rates for percentile computation
        sorted_rates: list[Decimal] = []
        if self._data_store is not None:
            raw_rates = await self._data_store.get_funding_rates(symbol, since_ms)
            sorted_rates = sorted(r.funding_rate for r in raw_rates)

        # 3. Get current live rate (fall back to avg_rate if unavailable)
        current_rate = stats.avg_rate
        if self._funding_monitor is not None:
            fr_data = self._funding_monitor.get_funding_rate(symbol)
            if fr_data is not None:
                current_rate = fr_data.rate

        # 4. Compute percentile
        percentile = compute_rate_percentile(current_rate, sorted_rates)

        # 5. Classify trend from recent rate values
        trend = TrendDirection.STABLE
        if self._data_store is not None:
            try:
                raw_rates_for_trend = await self._data_store.get_funding_rates(symbol, since_ms)
                rate_values = [r.funding_rate for r in raw_rates_for_trend]
                if len(rate_values) >= 7:  # Need at least span+1 for classify_trend
                    recent = rate_values[-30:] if len(rate_values) > 30 else rate_values
                    trend = classify_trend(recent)
            except Exception as e:
                logger.debug("trend_classification_failed", symbol=symbol, error=str(e))

        # 6. Compute z-score
        z_score = _ZERO
        if stats.std_dev > _ZERO:
            z_score = (current_rate - stats.avg_rate) / stats.std_dev

        # 7. Build RateContext
        rate_context = RateContext(
            current_rate=current_rate,
            percentile=percentile,
            trend=trend,
            avg_rate=stats.avg_rate,
            median_rate=stats.median_rate,
            std_dev=stats.std_dev,
            is_above_average=current_rate > stats.avg_rate,
            z_score=z_score,
        )

        # 8. Build optional SignalBreakdown from pre-computed signals
        signal_breakdown: SignalBreakdown | None = None
        cs = self._latest_signals.get(symbol)
        if cs is not None:
            signal_breakdown = SignalBreakdown(
                composite_score=cs.score,
                rate_level=cs.rate_level,
                trend_score=cs.trend_score,
                persistence=cs.persistence,
                basis_score=cs.basis_score,
                volume_ok=cs.volume_ok,
                weights={},  # Weights not stored on CompositeSignal; empty dict
            )

        # 9. Classify action
        composite_score = cs.score if cs is not None else None
        action = classify_action(
            percentile=percentile,
            composite_score=composite_score,
            has_sufficient_data=stats.has_sufficient_data,
            trend=trend,
        )

        return DecisionContext(
            symbol=symbol,
            rate_context=rate_context,
            signal_breakdown=signal_breakdown,
            action=action,
            has_sufficient_data=stats.has_sufficient_data,
        )
