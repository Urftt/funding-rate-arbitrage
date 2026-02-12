# Phase 5: Signal Analysis & Integration - Research

**Researched:** 2026-02-12
**Domain:** Funding rate signal analysis, composite scoring, orchestrator integration, feature flags
**Confidence:** HIGH

## Summary

This phase replaces the bot's simple threshold-based entry/exit logic (v1.0: "is funding rate > min_rate?") with a composite signal engine that considers funding rate trends, persistence, basis spread, and volume before making decisions. The composite signal is a weighted score computed from multiple sub-signals, each of which classifies one dimension of the opportunity quality. A feature flag (`strategy_mode: simple`) must preserve the v1.0 behavior unchanged, ensuring all existing tests continue to pass.

The primary technical challenge is not algorithmic complexity (the signal computations are straightforward EMA/counting/weighting) but **architectural integration**: the new signal engine must slot into the existing orchestrator scan cycle, replacing the `OpportunityRanker` as the entry/exit decision maker for composite mode while preserving the v1.0 path identically. The existing `HistoricalDataStore` from Phase 4 provides the historical funding rates and OHLCV data needed for trend detection and persistence scoring. The current `FundingMonitor` already caches live funding rates with `mark_price` and `volume_24h`, providing the real-time inputs. Basis spread requires comparing spot and perp prices, which are already available via the `TickerService` price cache (perp prices from `FundingMonitor`, spot prices need to be added or derived).

No external libraries are needed. All signal computations use Python's `Decimal` type and the standard library. The EMA calculation for trend detection is a simple recursive formula that operates on the last N historical funding rate values from the database. The composite signal is a weighted linear combination with configurable weights, producing a single `Decimal` score per pair per scan cycle.

**Primary recommendation:** Create a new `src/bot/signals/` module with three sub-components (trend detector, persistence scorer, composite signal aggregator), wire into the orchestrator via a `SignalEngine` that the orchestrator calls instead of/alongside the existing `OpportunityRanker`, and gate all new behavior behind a `strategy_mode` config field with `"simple"` and `"composite"` values.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `decimal` | stdlib | All signal score computations | Already used throughout codebase; Decimal precision required per project convention |
| `aiosqlite` | 0.22.1 (already installed) | Read historical data for trend/persistence | Already used by Phase 4 HistoricalDataStore |
| `structlog` | >=25.5 (already installed) | Signal logging and visibility | Already used throughout; required for SGNL-06 composite score visibility |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic-settings` | >=2.12 (already installed) | Signal configuration (weights, lookbacks, thresholds) | SignalSettings config class for new signal parameters |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual EMA in Decimal | pandas/numpy EMA | Overkill for single-series EMA on 10-50 data points; adds heavy dependencies; breaks Decimal precision |
| Weighted linear combination | sklearn/ML scoring | Massively over-engineered for 5 inputs; explicitly out of scope per REQUIREMENTS.md |
| New `signals/` module | Extending `market_data/opportunity_ranker.py` | Would bloat the ranker; signals are conceptually separate from opportunity ranking; ranker stays for v1.0 path |

**Installation:**
No new packages needed. All dependencies already in `pyproject.toml`.

## Architecture Patterns

### Recommended Project Structure
```
src/bot/
├── signals/                     # NEW: Signal analysis module
│   ├── __init__.py              # Public exports
│   ├── models.py                # Signal data models (TrendDirection, SignalScore, CompositeSignal)
│   ├── trend.py                 # SGNL-01: Funding rate trend detection (EMA-based)
│   ├── persistence.py           # SGNL-02: Persistence scoring (time above threshold)
│   ├── basis.py                 # SGNL-04: Spot-perp basis spread computation
│   ├── volume.py                # SGNL-05: Volume trend filtering
│   ├── composite.py             # SGNL-03: Weighted composite signal aggregator
│   └── engine.py                # SGNL-06: SignalEngine (orchestrates sub-signals, replaces ranker for composite mode)
├── config.py                    # MODIFIED: Add SignalSettings, strategy_mode field
├── orchestrator.py              # MODIFIED: Conditionally use SignalEngine vs OpportunityRanker
├── models.py                    # MODIFIED: Add CompositeOpportunityScore (extends OpportunityScore)
└── main.py                      # MODIFIED: Wire SignalEngine into component graph
```

### Pattern 1: Strategy Mode Feature Flag
**What:** A `strategy_mode` field in config controls whether the orchestrator uses the v1.0 simple-threshold path or the v1.1 composite-signal path.
**When to use:** Every entry/exit decision point in the orchestrator.
**Why:** Satisfies SGNL-05 (feature flag revert to v1.0) and Success Criteria #5.

```python
# In config.py
class TradingSettings(BaseSettings):
    # ... existing fields ...
    strategy_mode: Literal["simple", "composite"] = "simple"  # Default preserves v1.0

# In orchestrator._autonomous_cycle():
if self._settings.trading.strategy_mode == "composite" and self._signal_engine is not None:
    opportunities = self._signal_engine.score_opportunities(
        funding_rates=all_rates,
        markets=markets,
        data_store=self._data_store,
    )
else:
    # v1.0 path: unchanged
    opportunities = self._ranker.rank_opportunities(
        funding_rates=all_rates,
        markets=markets,
        min_rate=self._settings.trading.min_funding_rate,
        min_volume_24h=self._settings.risk.min_volume_24h,
        min_holding_periods=self._settings.risk.min_holding_periods,
    )
```

### Pattern 2: EMA-Based Trend Detection (SGNL-01)
**What:** Compute a short-window Exponential Moving Average over the last N historical funding rates, then classify trend as `rising`, `falling`, or `stable` based on the slope of recent EMA values.
**When to use:** Computing the trend sub-signal for each pair on each scan cycle.
**Why:** EMA reacts faster to recent changes than SMA, appropriate for funding rates that change every 4-8 hours.

```python
from decimal import Decimal
from enum import Enum

class TrendDirection(str, Enum):
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"

def compute_ema(values: list[Decimal], span: int) -> list[Decimal]:
    """Compute EMA over a list of Decimal values.

    Uses the standard recursive formula:
    EMA_t = alpha * value_t + (1 - alpha) * EMA_{t-1}
    where alpha = 2 / (span + 1)
    """
    if not values:
        return []
    alpha = Decimal("2") / (Decimal(span) + Decimal("1"))
    one_minus_alpha = Decimal("1") - alpha
    ema = [values[0]]
    for v in values[1:]:
        ema.append(alpha * v + one_minus_alpha * ema[-1])
    return ema

def classify_trend(
    funding_rates: list[Decimal],
    span: int = 6,
    stable_threshold: Decimal = Decimal("0.00005"),
) -> TrendDirection:
    """Classify funding rate trend from historical data.

    Computes EMA, then compares last EMA vs EMA from `span` periods ago.
    If the difference exceeds stable_threshold, trend is rising or falling.
    """
    if len(funding_rates) < span + 1:
        return TrendDirection.STABLE  # Not enough data

    ema = compute_ema(funding_rates, span)
    recent = ema[-1]
    earlier = ema[-span]
    diff = recent - earlier

    if diff > stable_threshold:
        return TrendDirection.RISING
    elif diff < -stable_threshold:
        return TrendDirection.FALLING
    return TrendDirection.STABLE
```

### Pattern 3: Persistence Scoring (SGNL-02)
**What:** Count consecutive historical funding rate periods where the rate stayed above a threshold. Normalize to a 0-1 score.
**When to use:** Evaluating how reliable a funding rate opportunity is (longer persistence = higher confidence).

```python
def compute_persistence_score(
    funding_rates: list[Decimal],
    threshold: Decimal,
    max_periods: int = 30,
) -> Decimal:
    """Score how long the funding rate has stayed above threshold.

    Walks backward from most recent, counting consecutive periods >= threshold.
    Returns count / max_periods, capped at Decimal("1").
    """
    consecutive = 0
    for rate in reversed(funding_rates):
        if rate >= threshold:
            consecutive += 1
        else:
            break
    return min(Decimal(consecutive) / Decimal(max_periods), Decimal("1"))
```

### Pattern 4: Basis Spread Computation (SGNL-04)
**What:** Compute `(perp_price - spot_price) / spot_price` as a measure of market premium/discount. Positive basis = perp trading at premium (consistent with positive funding rate).
**When to use:** As an additional confirming signal -- wide basis + high funding rate = stronger signal.

```python
def compute_basis_spread(
    spot_price: Decimal,
    perp_price: Decimal,
) -> Decimal:
    """Compute basis spread as (perp - spot) / spot.

    Positive = perp premium (consistent with positive funding).
    Returns Decimal("0") if spot_price is zero.
    """
    if spot_price == Decimal("0"):
        return Decimal("0")
    return (perp_price - spot_price) / spot_price
```

### Pattern 5: Weighted Composite Signal (SGNL-03)
**What:** Combine sub-signals (rate level, trend, persistence, basis, volume) into a single score using configurable weights.
**When to use:** Final scoring step for each pair before entry/exit decisions.

```python
@dataclass
class CompositeSignal:
    """Complete composite signal with sub-signal breakdown."""
    symbol: str
    score: Decimal              # Weighted composite (0-1 range)
    rate_level: Decimal         # Normalized current rate
    trend: TrendDirection       # Rising/falling/stable
    trend_score: Decimal        # Numeric trend contribution (0-1)
    persistence: Decimal        # Persistence score (0-1)
    basis_spread: Decimal       # Raw basis spread
    basis_score: Decimal        # Normalized basis contribution (0-1)
    volume_ok: bool             # Passes volume filter
    passes_entry: bool          # Score >= entry threshold

def compute_composite_score(
    rate_level: Decimal,        # Normalized 0-1
    trend_score: Decimal,       # 0-1
    persistence: Decimal,       # 0-1
    basis_score: Decimal,       # 0-1
    weights: SignalWeights,
) -> Decimal:
    """Weighted linear combination of sub-signals."""
    return (
        weights.rate_level * rate_level
        + weights.trend * trend_score
        + weights.persistence * persistence
        + weights.basis * basis_score
    )
```

### Pattern 6: Optional Injection (v1.1 Convention)
**What:** The `SignalEngine` is injected into the orchestrator as `| None = None`, consistent with the Phase 4 pattern for `HistoricalDataFetcher` and `HistoricalDataStore`.
**When to use:** When the `strategy_mode` is `"composite"` and historical data is available.

```python
class Orchestrator:
    def __init__(
        self,
        # ... existing params ...
        signal_engine: SignalEngine | None = None,  # NEW: v1.1 composite signals
    ) -> None:
        self._signal_engine = signal_engine
```

### Anti-Patterns to Avoid
- **Using float for any signal computation:** Breaks the project's Decimal convention; introduces floating-point drift in score comparisons.
- **Modifying OpportunityRanker for composite signals:** The ranker is the v1.0 path and must remain unchanged. Build the composite path alongside it, not on top of it.
- **Hardcoding signal weights:** All weights and thresholds must be configurable via `SignalSettings` so backtesting (Phase 6) can sweep over them.
- **Making HistoricalDataStore a hard dependency:** The signal engine must degrade gracefully if no historical data is available (e.g., return `TrendDirection.STABLE` and persistence=0).
- **Logging composite scores only at DEBUG level:** SGNL-06 requires visibility. Log the composite breakdown at INFO level on each scan cycle.
- **Changing the `OpportunityScore` dataclass itself:** Add a new `CompositeOpportunityScore` that extends or wraps `OpportunityScore` rather than modifying the existing one, which would break v1.0 consumers.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Historical data access | Direct SQL queries in signal code | `HistoricalDataStore.get_funding_rates()` | Store already provides typed query methods; keeps SQL isolated |
| Real-time price cache | Separate price fetch for basis spread | `TickerService.get_price()` | Already provides cached spot/perp prices from FundingMonitor polling |
| Configuration validation | Manual range checks on weights | `pydantic-settings` with `Field(ge=0, le=1)` validators | Already used; provides declarative validation with env var loading |
| Structured logging | Custom log formatters for signal scores | `structlog` with keyword args | Already configured; just pass signal fields as kwargs |
| Decimal math precision | Custom rounding functions | Python `Decimal` with explicit context | Stdlib; project already uses this everywhere |

**Key insight:** Phase 4 already built the data infrastructure (HistoricalDataStore with `get_funding_rates()` and `get_ohlcv_candles()`). Phase 5 is a pure consumer of that data. The signal module reads data, computes scores, and returns them. No new data storage or fetching is needed.

## Common Pitfalls

### Pitfall 1: EMA with Decimal Division Precision
**What goes wrong:** Decimal division in EMA (alpha = 2/(span+1)) can produce very long decimal representations that slow down repeated multiplication.
**Why it happens:** Python Decimal preserves full precision by default, so `Decimal("2") / Decimal("7")` produces a very long result.
**How to avoid:** Use `quantize()` to limit EMA intermediate results to a reasonable precision (e.g., 12 decimal places). Funding rates are typically expressed with 4-6 significant digits, so 12 decimal places in EMA computation is more than sufficient.
**Warning signs:** Slow signal computation or memory growth from very long Decimal strings.

### Pitfall 2: Insufficient Historical Data for Trend Detection
**What goes wrong:** On first startup or for newly-tracked pairs, there may not be enough historical funding rate records to compute a meaningful EMA/trend.
**Why it happens:** A 6-period EMA lookback requires at least 7 records. For 8h funding intervals, that is 56 hours (~2.3 days) of data. New pairs or fresh database will have fewer.
**How to avoid:** When data is insufficient, return `TrendDirection.STABLE` and `persistence_score = 0`. Document this graceful degradation in the engine. Do NOT block or raise errors.
**Warning signs:** Errors or `None` returns from trend/persistence functions when data is sparse.

### Pitfall 3: Basis Spread Requires Both Spot and Perp Prices
**What goes wrong:** The `TickerService` currently only receives perp prices from `FundingMonitor._poll_once()`. Spot prices are not systematically cached.
**Why it happens:** The `FundingMonitor` fetches linear tickers (perpetuals only). Spot prices are only fetched when placing orders via `PaperExecutor` or from the exchange.
**How to avoid:** Either (a) extend `FundingMonitor._poll_once()` to also fetch spot tickers for tracked pairs, or (b) compute basis from OHLCV close prices in the database as a proxy, or (c) use the perp mark_price vs index_price from the ticker info dict. Option (c) is preferred because Bybit tickers already include `indexPrice` in the `info` dict which represents the spot index -- no extra API calls needed. Just extract it during the existing polling loop.
**Warning signs:** Basis spread always returning `0` or `None` because spot prices are unavailable.

### Pitfall 4: Feature Flag Not Covering Exit Decisions
**What goes wrong:** Implementing `strategy_mode` only for entry decisions but forgetting that exit decisions (`_close_unprofitable_positions`) also need to be gated.
**Why it happens:** The current exit logic checks `rate_data.rate < self._settings.risk.exit_funding_rate` -- a simple threshold. In composite mode, the exit decision should also use the composite signal (e.g., "close when composite score drops below exit threshold").
**How to avoid:** The strategy mode flag must control BOTH entry and exit decision paths. Map out all decision points in the orchestrator before implementing.
**Warning signs:** Composite mode for entry but simple threshold for exit creates inconsistent behavior.

### Pitfall 5: Breaking Existing Tests by Modifying Shared Types
**What goes wrong:** Changing the `OpportunityScore` dataclass or `OpportunityRanker` signature breaks existing tests that depend on the current interface.
**Why it happens:** Tests create `OpportunityScore` instances directly and mock `OpportunityRanker.rank_opportunities()`.
**How to avoid:** Do NOT modify `OpportunityScore` or `OpportunityRanker`. Create new types (`CompositeOpportunityScore`, `SignalEngine`) and new methods. The orchestrator branches to the appropriate path based on `strategy_mode`. Existing tests all run in "simple" mode by default.
**Warning signs:** Test failures in `test_orchestrator.py` or `test_opportunity_ranker.py` after Phase 5 changes.

### Pitfall 6: Async vs Sync Mismatch in Signal Computations
**What goes wrong:** Signal computations need historical data from the async `HistoricalDataStore`, making the entire signal scoring pipeline async, which complicates the orchestrator integration.
**Why it happens:** `HistoricalDataStore.get_funding_rates()` is async (aiosqlite). The signal engine must be async too.
**How to avoid:** Make `SignalEngine.score_opportunities()` an `async` method. The orchestrator already runs in an async context, so this is straightforward. Keep pure computation functions (EMA, persistence count, basis calc) synchronous and only make the data-fetching orchestration async.
**Warning signs:** `RuntimeWarning: coroutine was never awaited` errors.

### Pitfall 7: Volume Trend Requires Time-Series OHLCV Data
**What goes wrong:** SGNL-05 requires detecting declining volume trends, not just checking a 24h volume snapshot. A single `volume_24h` value cannot show a trend.
**Why it happens:** The current `FundingRateData.volume_24h` is a single point-in-time value.
**How to avoid:** Use historical OHLCV candle volumes from Phase 4 data. Compare recent average volume (e.g., last 7 days) vs prior period average volume. If recent volume is significantly lower (e.g., <70% of prior), flag the pair as having declining volume.
**Warning signs:** Volume filter only checking `volume_24h > threshold` instead of detecting a trend.

## Code Examples

### Signal Configuration
```python
# Source: Project convention from config.py
class SignalSettings(BaseSettings):
    """Signal analysis configuration for composite strategy mode."""

    model_config = SettingsConfigDict(env_prefix="SIGNAL_")

    # EMA trend detection
    trend_ema_span: int = 6                          # Number of funding periods for EMA
    trend_stable_threshold: Decimal = Decimal("0.00005")  # Min EMA diff to call rising/falling

    # Persistence scoring
    persistence_threshold: Decimal = Decimal("0.0003")    # Rate threshold for "elevated"
    persistence_max_periods: int = 30                      # Normalize count against this

    # Basis spread
    basis_weight_cap: Decimal = Decimal("0.01")           # Cap basis contribution at 1%

    # Volume trend
    volume_lookback_days: int = 7                         # Days for recent volume average
    volume_decline_ratio: Decimal = Decimal("0.7")        # Flag if recent < 70% of prior

    # Composite weights (must sum to ~1.0)
    weight_rate_level: Decimal = Decimal("0.35")
    weight_trend: Decimal = Decimal("0.25")
    weight_persistence: Decimal = Decimal("0.25")
    weight_basis: Decimal = Decimal("0.15")

    # Entry/exit thresholds for composite score
    entry_threshold: Decimal = Decimal("0.5")             # Min composite score to enter
    exit_threshold: Decimal = Decimal("0.3")              # Close when score drops below this
```

### SignalEngine Orchestration
```python
class SignalEngine:
    """Orchestrates sub-signal computation and produces composite scores.

    Called by the orchestrator in composite mode. Reads historical data,
    computes sub-signals, aggregates into composite scores, and returns
    ranked opportunities.
    """

    def __init__(
        self,
        signal_settings: SignalSettings,
        data_store: HistoricalDataStore | None = None,
        ticker_service: TickerService | None = None,
    ) -> None:
        self._settings = signal_settings
        self._data_store = data_store
        self._ticker_service = ticker_service

    async def score_opportunities(
        self,
        funding_rates: list[FundingRateData],
        markets: dict,
    ) -> list[CompositeOpportunityScore]:
        """Score all pairs using composite signals.

        For each pair:
        1. Compute trend from historical funding rates
        2. Compute persistence from historical funding rates
        3. Compute basis spread from current spot/perp prices
        4. Check volume trend from historical OHLCV
        5. Aggregate into composite score
        6. Log composite breakdown (SGNL-06)

        Returns list sorted by composite score descending.
        """
        # Implementation fetches historical data per pair and computes signals
        ...
```

### Orchestrator Integration with Strategy Mode
```python
# In orchestrator._autonomous_cycle():

# DECIDE: Use appropriate strategy
if self._settings.trading.strategy_mode == "composite" and self._signal_engine is not None:
    composite_scores = await self._signal_engine.score_opportunities(
        funding_rates=all_rates,
        markets=markets,
    )
    await self._close_unprofitable_positions_composite(composite_scores)
    await self._open_profitable_positions_composite(composite_scores)
else:
    # v1.0 path: UNCHANGED
    opportunities = self._ranker.rank_opportunities(
        funding_rates=all_rates,
        markets=markets,
        min_rate=self._settings.trading.min_funding_rate,
        min_volume_24h=self._settings.risk.min_volume_24h,
        min_holding_periods=self._settings.risk.min_holding_periods,
    )
    await self._close_unprofitable_positions()
    await self._open_profitable_positions(opportunities)
```

### Extracting Index Price for Basis Spread
```python
# In FundingMonitor._poll_once(), the Bybit ticker info dict contains indexPrice:
# Source: Bybit API v5 Tickers response (info.indexPrice field)

for symbol, ticker in tickers.items():
    info = ticker.get("info", {})
    # ... existing rate extraction ...

    # NEW: Extract index price for basis spread computation
    index_price_raw = info.get("indexPrice")
    if index_price_raw is not None:
        try:
            index_price = Decimal(str(index_price_raw))
            # Store as spot proxy for basis computation
            spot_symbol = self._derive_spot_symbol(symbol)
            if spot_symbol and index_price > 0:
                await self._ticker_service.update_price(
                    spot_symbol, index_price, now
                )
        except (ValueError, ArithmeticError):
            pass
```

### Logging Composite Scores (SGNL-06)
```python
# Each scan cycle, log the composite breakdown for all scored pairs
for signal in composite_scores:
    logger.info(
        "composite_signal",
        symbol=signal.symbol,
        composite_score=str(signal.score),
        rate_level=str(signal.rate_level),
        trend=signal.trend.value,
        trend_score=str(signal.trend_score),
        persistence=str(signal.persistence),
        basis_spread=str(signal.basis_spread),
        basis_score=str(signal.basis_score),
        volume_ok=signal.volume_ok,
        passes_entry=signal.passes_entry,
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Simple funding rate threshold | Composite signal scoring (trend + persistence + basis + volume) | Phase 5 (this work) | Replaces single-dimension filter with multi-dimensional scoring |
| Static entry/exit thresholds | Configurable composite score thresholds | Phase 5 | Enables backtesting (Phase 6) to sweep over signal parameters |
| OpportunityRanker as sole decision maker | Strategy mode branch: simple (ranker) vs composite (signal engine) | Phase 5 | v1.0 preserved, v1.1 adds intelligence |

**Deprecated/outdated:**
- No deprecations. This phase adds new functionality. The v1.0 path (`OpportunityRanker`, simple threshold) remains unchanged and is the default.

## Key Design Decisions for Planner

### 1. How CompositeOpportunityScore Relates to OpportunityScore
The composite path should produce a `CompositeOpportunityScore` that includes all fields from the existing `OpportunityScore` (for compatibility with the orchestrator's `_open_profitable_positions` and risk manager) PLUS the composite signal breakdown. Use composition (wrap an `OpportunityScore`) or inheritance (extend it). Either works; inheritance is simpler.

### 2. Where the Strategy Mode Branch Lives
The branch MUST be in the orchestrator's `_autonomous_cycle()` method, not deeper. The orchestrator is the decision maker. The signal engine is a pure scoring service. The ranker is the v1.0 scoring service. The orchestrator chooses which to call.

### 3. Basis Spread: Index Price vs Separate Spot Fetch
Bybit's perpetual ticker response includes `indexPrice` in the `info` dict. This is the composite index price that represents the spot market. Using this avoids a separate API call for spot tickers. The `FundingMonitor` already processes the `info` dict -- just extract one more field. Store it in `TickerService` under the derived spot symbol.

### 4. Historical Data Lookback for Signals
Trend detection needs ~6-10 recent funding rate periods. Persistence scoring looks back up to 30 periods. Volume trend needs ~14 days of OHLCV. The Phase 4 data store has up to 365 days of data, so lookbacks are well within range. Each scan cycle queries a small subset of the stored data.

### 5. Exit Decision in Composite Mode
In simple mode, exit is `rate < exit_funding_rate`. In composite mode, exit should be `composite_score < exit_threshold`. This means the signal engine must also score pairs that already have open positions, not just new opportunities. The orchestrator must pass the list of open position symbols to the signal engine.

## Open Questions

1. **Exact index price field name in Bybit ticker info dict**
   - What we know: Bybit v5 tickers response includes index price for perpetual contracts. The `FundingMonitor` already extracts `fundingRate`, `nextFundingTime`, `fundingIntervalHour`, and `volume24h` from `info`.
   - What's unclear: The exact field name may be `indexPrice` or `index_price` depending on ccxt normalization vs raw Bybit response. The `info` dict contains raw Bybit fields.
   - Recommendation: Check the actual `info` dict content during implementation by logging a sample ticker response. HIGH confidence it is `indexPrice` based on Bybit v5 API docs.
   - **Confidence:** MEDIUM (needs runtime verification)

2. **Optimal default signal weights**
   - What we know: Weights should emphasize rate level (most directly correlated with profit) and trend (predictive of future rate).
   - What's unclear: Exact optimal values -- these are inherently empirical.
   - Recommendation: Use reasonable defaults (rate: 0.35, trend: 0.25, persistence: 0.25, basis: 0.15) and mark them as tunable for Phase 6 backtesting. The weights are configurable, not hardcoded.
   - **Confidence:** LOW (optimal values require backtesting in Phase 6)

3. **Whether volume trend should be a filter or a scoring component**
   - What we know: SGNL-05 says "filter opportunities by volume trend (avoid high-rate pairs with declining volume)". This suggests a binary filter, not a weighted score component.
   - What's unclear: Whether declining volume should set `passes_entry = False` (hard filter) or reduce the composite score (soft penalty).
   - Recommendation: Implement as a hard filter (volume_ok boolean). A pair with declining volume gets `passes_entry = False` regardless of composite score. This is simpler and matches the requirement wording ("filter" not "score").
   - **Confidence:** HIGH (matches requirement language)

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/bot/orchestrator.py` -- current entry/exit decision logic, scan cycle structure
- Existing codebase: `src/bot/market_data/opportunity_ranker.py` -- current ranking formula, v1.0 interface
- Existing codebase: `src/bot/data/store.py` -- Phase 4 HistoricalDataStore query API
- Existing codebase: `src/bot/data/models.py` -- HistoricalFundingRate, OHLCVCandle data models
- Existing codebase: `src/bot/models.py` -- FundingRateData, OpportunityScore interfaces
- Existing codebase: `src/bot/config.py` -- Settings pattern, RuntimeConfig pattern
- Existing codebase: `src/bot/main.py` -- Component wiring, optional injection pattern
- Existing codebase: `src/bot/market_data/funding_monitor.py` -- Ticker info dict parsing
- Existing codebase: `tests/test_orchestrator.py` -- Current test patterns, fixtures, v1.0 test expectations
- REQUIREMENTS.md: SGNL-01 through SGNL-06 requirement specifications
- ROADMAP.md: Phase 5 success criteria

### Secondary (MEDIUM confidence)
- Bybit API v5 Tickers: `indexPrice` field in perpetual ticker response (based on Bybit API docs)
- EMA formula: Standard exponential moving average computation (mathematical definition)

### Tertiary (LOW confidence)
- Optimal signal weight defaults (0.35/0.25/0.25/0.15): Reasonable starting point, requires backtesting validation in Phase 6

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries needed; all computation in Decimal with existing deps
- Architecture: HIGH -- follows established project patterns (optional injection, config-driven, module per concern)
- Signal algorithms: HIGH -- EMA, persistence counting, basis spread, weighted scoring are well-defined
- Integration points: HIGH -- orchestrator scan cycle, config, main.py wiring are fully understood from code review
- Default parameters: LOW -- signal weights and thresholds are empirical, need backtesting
- Pitfalls: HIGH -- identified from code review (async data access, existing test preservation, spot price availability)

**Research date:** 2026-02-12
**Valid until:** 2026-03-12 (30 days -- codebase is stable, no external dependency changes expected)
