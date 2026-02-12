"""Signal engine orchestrating all sub-signals into composite scores (SGNL-06).

The SignalEngine is the top-level coordinator that:
1. Fetches historical data for each pair
2. Computes all sub-signals (trend, persistence, basis, volume)
3. Aggregates into a composite score
4. Logs the composite breakdown at INFO level
5. Returns ranked CompositeOpportunityScore objects

Graceful degradation: operates with partial or no historical data by
falling back to neutral defaults (STABLE trend, zero persistence, etc.).

CRITICAL: All computations use Decimal. Never use float for signal scores.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from bot.config import SignalSettings
from bot.logging import get_logger
from bot.models import FundingRateData, OpportunityScore
from bot.signals.basis import compute_basis_spread, normalize_basis_score
from bot.signals.composite import compute_composite_score, normalize_rate_level
from bot.signals.models import (
    CompositeOpportunityScore,
    CompositeSignal,
    TrendDirection,
)
from bot.signals.persistence import compute_persistence_score
from bot.signals.trend import classify_trend
from bot.signals.volume import compute_volume_trend

if TYPE_CHECKING:
    from bot.data.store import HistoricalDataStore
    from bot.market_data.funding_monitor import FundingMonitor
    from bot.market_data.ticker_service import TickerService

logger = get_logger(__name__)

#: Trend direction to numeric score mapping.
_TREND_SCORES: dict[TrendDirection, Decimal] = {
    TrendDirection.RISING: Decimal("1.0"),
    TrendDirection.STABLE: Decimal("0.5"),
    TrendDirection.FALLING: Decimal("0.0"),
}


def _derive_spot_symbol(perp_symbol: str, markets: dict) -> str | None:
    """Derive the spot symbol from a perpetual symbol using markets dict.

    Replicates OpportunityRanker._derive_spot_symbol logic to keep the
    signal module independent of the ranking module.

    Args:
        perp_symbol: Perpetual symbol (e.g., "BTC/USDT:USDT").
        markets: ccxt-style markets dict.

    Returns:
        Spot symbol string if valid active spot market exists, None otherwise.
    """
    perp_market = markets.get(perp_symbol)
    if perp_market is None:
        return None

    base = perp_market.get("base")
    quote = perp_market.get("quote")
    if not base or not quote:
        return None

    spot_symbol = f"{base}/{quote}"
    spot_market = markets.get(spot_symbol)
    if spot_market is None:
        return None

    if not spot_market.get("spot", False):
        return None
    if not spot_market.get("active", False):
        return None

    return spot_symbol


class SignalEngine:
    """Orchestrates all sub-signals into composite opportunity scores.

    Coordinates trend detection, persistence scoring, basis spread
    computation, and volume trend filtering to produce a single
    composite score for each funding rate opportunity.

    Args:
        signal_settings: Configuration for weights, thresholds, and lookbacks.
        data_store: Historical data store for funding rates and OHLCV candles.
            None = graceful degradation (neutral defaults).
        ticker_service: Shared price cache for spot/perp prices.
            None = no basis spread computation.
        funding_monitor: Funding rate monitor for index prices.
            None = no index price fallback.
    """

    def __init__(
        self,
        signal_settings: SignalSettings,
        data_store: HistoricalDataStore | None = None,
        ticker_service: TickerService | None = None,
        funding_monitor: FundingMonitor | None = None,
    ) -> None:
        self._settings = signal_settings
        self._data_store = data_store
        self._ticker_service = ticker_service
        self._funding_monitor = funding_monitor

    async def score_opportunities(
        self,
        funding_rates: list[FundingRateData],
        markets: dict,
    ) -> list[CompositeOpportunityScore]:
        """Score and rank all funding rate opportunities using composite signals.

        For each pair with a positive funding rate:
        1. Fetch historical data (if available)
        2. Compute all sub-signals
        3. Aggregate into composite score
        4. Log breakdown at INFO level (SGNL-06)
        5. Build CompositeOpportunityScore for orchestrator compatibility

        Args:
            funding_rates: Current funding rate snapshots for perpetual pairs.
            markets: ccxt-style markets dict for spot symbol derivation.

        Returns:
            List of CompositeOpportunityScore sorted by composite score descending.
        """
        weights = self._build_weights()
        results: list[CompositeOpportunityScore] = []

        for fr in funding_rates:
            if fr.rate <= 0:
                continue

            spot_symbol = _derive_spot_symbol(fr.symbol, markets)
            if spot_symbol is None:
                continue

            signal = await self._compute_signal(fr, spot_symbol, markets, weights)

            # Build v1.0-compatible OpportunityScore
            opportunity = OpportunityScore(
                spot_symbol=spot_symbol,
                perp_symbol=fr.symbol,
                funding_rate=fr.rate,
                funding_interval_hours=fr.interval_hours,
                volume_24h=fr.volume_24h,
                net_yield_per_period=fr.rate,  # Proxy; actual fee check in PositionManager
                annualized_yield=fr.rate * (Decimal("8760") / Decimal(str(fr.interval_hours))),
                passes_filters=signal.passes_entry,
            )

            results.append(
                CompositeOpportunityScore(opportunity=opportunity, signal=signal)
            )

            # SGNL-06: Log composite breakdown at INFO level
            logger.info(
                "composite_signal",
                symbol=signal.symbol,
                composite_score=str(signal.score),
                rate_level=str(signal.rate_level),
                trend=signal.trend.value,
                persistence=str(signal.persistence),
                basis_spread=str(signal.basis_spread),
                volume_ok=signal.volume_ok,
                passes_entry=signal.passes_entry,
            )

        results.sort(key=lambda cs: cs.signal.score, reverse=True)
        return results

    async def score_for_exit(
        self,
        symbols: list[str],
        funding_rates: list[FundingRateData],
        markets: dict,
    ) -> dict[str, CompositeSignal]:
        """Score specific symbols for exit decisions.

        Same computation as score_opportunities but filtered to the given
        symbols (currently open positions). Returns a dict for fast lookup.

        Args:
            symbols: Perpetual symbols to score (e.g., ["BTC/USDT:USDT"]).
            funding_rates: Current funding rate snapshots.
            markets: ccxt-style markets dict.

        Returns:
            Dict mapping perp symbol -> CompositeSignal.
        """
        weights = self._build_weights()
        result: dict[str, CompositeSignal] = {}
        symbol_set = set(symbols)

        # Build a lookup for funding rates by symbol
        rate_lookup = {fr.symbol: fr for fr in funding_rates}

        for symbol in symbol_set:
            fr = rate_lookup.get(symbol)
            if fr is None:
                continue

            spot_symbol = _derive_spot_symbol(symbol, markets)
            if spot_symbol is None:
                # Still compute signal but with limited data
                spot_symbol = symbol.split(":")[0] if ":" in symbol else symbol

            signal = await self._compute_signal(fr, spot_symbol, markets, weights)
            result[symbol] = signal

        return result

    async def _compute_signal(
        self,
        fr: FundingRateData,
        spot_symbol: str,
        markets: dict,
        weights: dict[str, Decimal],
    ) -> CompositeSignal:
        """Compute full composite signal for a single pair.

        Handles graceful degradation when historical data is unavailable.
        """
        # Defaults for graceful degradation
        trend = TrendDirection.STABLE
        persistence_score = Decimal("0")
        basis_spread = Decimal("0")
        basis_score_val = Decimal("0")
        volume_ok = True

        # --- Trend and Persistence (requires historical funding rates) ---
        if self._data_store is not None:
            try:
                lookback_periods = self._settings.trend_ema_span * 3
                historical_rates = await self._data_store.get_funding_rates(
                    symbol=fr.symbol,
                )
                # Take last N rates for trend computation
                rate_values = [r.funding_rate for r in historical_rates]
                if len(rate_values) >= self._settings.trend_ema_span + 1:
                    trend = classify_trend(
                        rate_values[-lookback_periods:] if len(rate_values) > lookback_periods else rate_values,
                        span=self._settings.trend_ema_span,
                        stable_threshold=self._settings.trend_stable_threshold,
                    )
                if rate_values:
                    persistence_score = compute_persistence_score(
                        rate_values,
                        threshold=self._settings.persistence_threshold,
                        max_periods=self._settings.persistence_max_periods,
                    )
            except Exception as e:
                logger.debug(
                    "historical_rates_unavailable",
                    symbol=fr.symbol,
                    error=str(e),
                )

        # --- Basis Spread (requires ticker_service for prices) ---
        if self._ticker_service is not None:
            try:
                spot_price = await self._ticker_service.get_price(spot_symbol)
                perp_price = await self._ticker_service.get_price(fr.symbol)
                if spot_price is not None and perp_price is not None:
                    basis_spread = compute_basis_spread(spot_price, perp_price)
                    basis_score_val = normalize_basis_score(
                        basis_spread, cap=self._settings.basis_weight_cap
                    )
            except Exception as e:
                logger.debug(
                    "basis_computation_failed",
                    symbol=fr.symbol,
                    error=str(e),
                )

        # --- Volume Trend (requires historical OHLCV candles) ---
        if self._data_store is not None:
            try:
                candles = await self._data_store.get_ohlcv_candles(
                    symbol=fr.symbol,
                )
                if candles:
                    volume_ok = compute_volume_trend(
                        candles,
                        lookback_days=self._settings.volume_lookback_days,
                        decline_ratio=self._settings.volume_decline_ratio,
                    )
            except Exception as e:
                logger.debug(
                    "volume_trend_unavailable",
                    symbol=fr.symbol,
                    error=str(e),
                )

        # --- Composite Score ---
        rate_level = normalize_rate_level(
            fr.rate, cap=self._settings.rate_normalization_cap
        )
        trend_score = _TREND_SCORES[trend]
        composite_score = compute_composite_score(
            rate_level=rate_level,
            trend_score=trend_score,
            persistence=persistence_score,
            basis_score=basis_score_val,
            weights=weights,
        )

        passes_entry = composite_score >= self._settings.entry_threshold and volume_ok

        return CompositeSignal(
            symbol=fr.symbol,
            score=composite_score,
            rate_level=rate_level,
            trend=trend,
            trend_score=trend_score,
            persistence=persistence_score,
            basis_spread=basis_spread,
            basis_score=basis_score_val,
            volume_ok=volume_ok,
            passes_entry=passes_entry,
        )

    def _build_weights(self) -> dict[str, Decimal]:
        """Build weights dict from settings."""
        return {
            "rate_level": self._settings.weight_rate_level,
            "trend": self._settings.weight_trend,
            "persistence": self._settings.weight_persistence,
            "basis": self._settings.weight_basis,
        }
