# Phase 11: Decision Context - Research

**Researched:** 2026-02-13
**Domain:** Decision support UI, rate percentile computation, signal score breakdown visualization, action label classification, glossary tooltips, summary page
**Confidence:** HIGH

## Summary

Phase 11 adds decision context features to the existing dashboard that answer "should I trade this pair?" with evidence-backed recommendations. This is a pure read-only presentation layer built on top of data already computed by the `PairAnalyzer` (Phase 8), `SignalEngine` (Phase 5), and `FundingMonitor` (Phase 1). The core work is (1) computing percentile rankings and trend indicators for current live funding rates, (2) surfacing the composite signal score breakdown that the `SignalEngine` already computes internally, (3) classifying opportunities into human-readable action labels based on evidence thresholds, (4) adding hover tooltips for metric explanations, and (5) building a dedicated "Should I Trade?" summary page that aggregates all evidence.

The implementation splits naturally into two plans matching the roadmap: Plan 11-01 covers the backend computation (a new `DecisionEngine` service that computes rate percentiles from historical data and produces structured decision context objects) plus the signal score breakdown UI on the pair detail panel. Plan 11-02 covers the action label classification logic, glossary tooltip system, and the standalone summary page. All computation uses existing `Decimal` arithmetic and existing data sources. Zero new Python dependencies. Zero new CDN additions. No trading engine changes.

The primary technical challenge is computing rate percentiles efficiently: for each live funding rate, determine what percentile it occupies relative to that pair's historical distribution. This requires cross-referencing real-time `FundingMonitor` data with historical rates from `HistoricalDataStore` via `PairAnalyzer`. The `PairAnalyzer` already fetches all historical rates for a symbol -- extending it with a `compute_percentile()` method that takes a current rate and a sorted list of historical rates is straightforward. The percentile computation is a simple sorted-insert position calculation using `bisect` (stdlib).

**Primary recommendation:** Build a `DecisionEngine` service under `src/bot/analytics/decision_engine.py` that combines `PairAnalyzer`, `SignalEngine`, and `FundingMonitor` data into a structured `DecisionContext` dataclass. Expose via new API endpoints. Enhance the funding rates panel with percentile badges and trend arrows. Add a new `/decision` or similar summary page. Use Tailwind CSS utility classes for tooltips (no tooltip library needed).

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | >=0.115 | New API endpoints for decision context data | Already the dashboard framework |
| Jinja2 | >=3.1 | Server-side template rendering for enhanced panels and summary page | Already used for all pages |
| Tailwind CSS | CDN | Styling for badges, tooltips, action labels, summary layout | Already used everywhere |
| Chart.js | @4 (CDN) | Signal breakdown visualization (radar/bar chart) | Already loaded on `/pairs` page |
| HTMX | 2.0.4 | Real-time updates to funding rates panel with decision context | Already in `base.html` |
| aiosqlite | >=0.22 | Historical rate queries for percentile computation | Already used by `HistoricalDataStore` |
| Decimal (stdlib) | N/A | All monetary/rate/percentile arithmetic | Project-wide convention |
| bisect (stdlib) | N/A | Efficient percentile computation via sorted insertion | Standard approach for percentile rank |
| `PairAnalyzer` | N/A | Historical rate statistics (avg, median, std dev) | Built in Phase 8, proven |
| `SignalEngine` | N/A | Composite signal score and sub-signal breakdown | Built in Phase 5, proven |
| `FundingMonitor` | N/A | Current live funding rate data | Built in Phase 1, proven |

### Supporting (no new additions needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | >=25.5 | Structured logging in DecisionEngine | Already project standard |
| pydantic-settings | >=2.12 | Configuration for decision thresholds | Already configured |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `bisect` for percentile | `statistics.percentile_at` | `bisect` is more explicit and works with Decimal lists; `statistics` module has limited Decimal support |
| Tailwind CSS tooltips | tippy.js or floating-ui | Would add another CDN; Tailwind's `group-hover` + absolute positioning is sufficient for static glossary text |
| Radar chart for signal breakdown | Stacked horizontal bar | Radar chart shows all sub-signals at once on familiar axes; bar chart is simpler but less intuitive for 4-5 dimensions |
| Server-side percentile in Python | SQLite PERCENT_RANK() window function | SQLite supports `PERCENT_RANK()` but it requires a window over the full dataset; Python-side with `bisect` on already-fetched data is simpler and consistent with existing `PairAnalyzer` pattern |

**Installation:** No new packages needed. No new CDN additions.

## Architecture Patterns

### Recommended Project Structure
```
src/bot/
  analytics/
    decision_engine.py          # NEW: DecisionEngine service class (~200 lines)
    pair_analyzer.py             # MODIFY: add compute_percentile() helper method
  dashboard/
    routes/
      pages.py                   # MODIFY: add /decision route
      api.py                     # MODIFY: add /api/decision/{symbol} and /api/decision/summary endpoints
    templates/
      decision.html              # NEW: "Should I Trade?" summary page (extends base.html)
      partials/
        funding_rates.html       # MODIFY: add percentile badges, trend arrows, action labels
        signal_breakdown.html    # NEW: signal score breakdown partial for pair detail
        glossary_tooltip.html    # NEW: macro/include for reusable tooltip pattern
tests/
  test_decision_engine.py        # NEW: TDD tests for decision logic
```

### Pattern 1: Decision Engine Service (follow existing service class pattern)
**What:** `DecisionEngine` is a service that takes `PairAnalyzer`, `SignalEngine`, `FundingMonitor`, and `HistoricalDataStore`, and produces `DecisionContext` dataclass results for each pair. Follows the same pattern as `PairAnalyzer` (stateless service, typed returns, Decimal arithmetic).
**When to use:** All decision context computation.
**Example:**
```python
# Source: Pattern derived from src/bot/analytics/pair_analyzer.py

from dataclasses import dataclass
from decimal import Decimal
from bot.signals.models import TrendDirection

@dataclass
class RateContext:
    """Historical context for a current funding rate."""
    current_rate: Decimal
    percentile: Decimal           # 0-100, where current rate sits historically
    trend: TrendDirection         # RISING / STABLE / FALLING
    avg_rate: Decimal             # Historical average
    median_rate: Decimal          # Historical median
    std_dev: Decimal              # Historical standard deviation
    is_above_average: bool        # current_rate > avg_rate
    z_score: Decimal              # (current - avg) / std_dev


@dataclass
class SignalBreakdown:
    """Sub-signal contribution breakdown for display."""
    composite_score: Decimal      # 0-1 total score
    rate_level: Decimal           # 0-1 normalized rate contribution
    trend_score: Decimal          # 0-1 trend contribution
    persistence: Decimal          # 0-1 persistence contribution
    basis_score: Decimal          # 0-1 basis contribution
    volume_ok: bool               # Hard filter pass/fail
    weights: dict[str, Decimal]   # Weight configuration used


@dataclass
class ActionLabel:
    """Recommended action with confidence."""
    label: str                    # "Strong opportunity", "Moderate opportunity", "Below average", "Not recommended"
    confidence: str               # "high", "medium", "low"
    reasons: list[str]            # Evidence-based reasons


@dataclass
class DecisionContext:
    """Complete decision context for a single pair."""
    symbol: str
    rate_context: RateContext
    signal_breakdown: SignalBreakdown | None   # None if signal engine unavailable
    action: ActionLabel
    has_sufficient_data: bool
```

### Pattern 2: Percentile Computation with bisect
**What:** Compute where a current rate sits in the historical distribution using sorted insertion position.
**When to use:** Rate percentile calculation.
**Example:**
```python
# Source: Python stdlib bisect module
import bisect
from decimal import Decimal

def compute_rate_percentile(
    current_rate: Decimal,
    historical_rates: list[Decimal],  # Must be sorted ascending
) -> Decimal:
    """Compute the percentile rank of current_rate in historical distribution.

    Uses bisect_left for the insertion position, then converts to percentile.
    Returns value in 0-100 range.
    """
    if not historical_rates:
        return Decimal("50")  # Default to median when no history

    n = len(historical_rates)
    position = bisect.bisect_left(historical_rates, current_rate)
    percentile = (Decimal(position) / Decimal(n)) * Decimal("100")
    return percentile.quantize(Decimal("0.1"))
```

### Pattern 3: Action Label Classification (threshold-based)
**What:** Map composite evidence into human-readable action labels using configurable thresholds. This is pure business logic, not ML.
**When to use:** Generating the "Strong opportunity" / "Not recommended" labels.
**Example:**
```python
def classify_action(
    percentile: Decimal,
    composite_score: Decimal | None,
    has_sufficient_data: bool,
    trend: TrendDirection,
) -> ActionLabel:
    """Classify a pair into an action label based on evidence.

    Thresholds:
    - Strong: percentile >= 75 AND (composite_score >= 0.6 or None) AND trend != FALLING
    - Moderate: percentile >= 50 AND (composite_score >= 0.4 or None)
    - Below average: percentile >= 25
    - Not recommended: percentile < 25 OR trend == FALLING with low score
    """
    reasons = []

    if not has_sufficient_data:
        return ActionLabel(
            label="Insufficient data",
            confidence="low",
            reasons=["Less than 30 historical data points available"],
        )

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

    # Classify
    if (percentile >= Decimal("75")
            and trend != TrendDirection.FALLING
            and (composite_score is None or composite_score >= Decimal("0.5"))):
        return ActionLabel(label="Strong opportunity", confidence="high", reasons=reasons)

    if (percentile >= Decimal("50")
            and (composite_score is None or composite_score >= Decimal("0.4"))):
        return ActionLabel(label="Moderate opportunity", confidence="medium", reasons=reasons)

    if percentile >= Decimal("25"):
        return ActionLabel(label="Below average", confidence="medium", reasons=reasons)

    return ActionLabel(label="Not recommended", confidence="high", reasons=reasons)
```

### Pattern 4: Tailwind CSS Tooltip (no JS library needed)
**What:** Pure CSS tooltip using Tailwind's `group` and `group-hover` utilities. No tooltip library required.
**When to use:** Glossary tooltips for metric explanations.
**Example:**
```html
<!-- Reusable tooltip pattern for Jinja2 templates -->
{% macro tooltip(text, explanation) %}
<span class="relative group cursor-help">
  <span class="underline decoration-dotted decoration-gray-500">{{ text }}</span>
  <span class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 rounded bg-gray-800 text-xs text-gray-200 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50 border border-dash-border shadow-lg">
    {{ explanation }}
  </span>
</span>
{% endmacro %}

<!-- Usage in template -->
{{ tooltip("Ann. Yield", "Fee-adjusted annualized return extrapolated from per-period net yield") }}
{{ tooltip("Percentile", "Where the current rate sits in the historical distribution (P75 = top 25%)") }}
{{ tooltip("Composite Score", "Weighted combination of rate level, trend, persistence, and basis signals (0-1)") }}
```

### Pattern 5: Enhanced Funding Rates Panel with Decision Context
**What:** Extend the existing `funding_rates.html` partial to show percentile badges and trend arrows alongside each rate. The data comes from the WebSocket update loop (server-side rendered) so it refreshes in real time.
**When to use:** Enhancing the main dashboard funding rates panel.
**Example:**
```html
<!-- Enhanced row in funding_rates.html -->
<tr class="border-b border-dash-border/50">
  <td class="py-1.5 px-2 text-gray-200">{{ fr.symbol }}</td>
  <td class="py-1.5 px-2 text-right font-mono {{ rate_color }}">
    {{ "%.4f" | format(fr.rate | float * 100) }}%
  </td>
  <!-- NEW: Percentile badge -->
  <td class="py-1.5 px-2 text-right">
    {% if context and context.percentile is not none %}
      <span class="text-xs px-1.5 py-0.5 rounded {{ percentile_color_class(context.percentile) }}">
        P{{ context.percentile | int }}
      </span>
    {% endif %}
  </td>
  <!-- NEW: Trend arrow -->
  <td class="py-1.5 px-2 text-center">
    {% if context and context.trend %}
      {% if context.trend.value == 'rising' %}
        <span class="text-green-400 text-xs">&#9650;</span>
      {% elif context.trend.value == 'falling' %}
        <span class="text-red-400 text-xs">&#9660;</span>
      {% else %}
        <span class="text-gray-500 text-xs">&#9644;</span>
      {% endif %}
    {% endif %}
  </td>
  <!-- NEW: Action label -->
  <td class="py-1.5 px-2 text-right">
    {% if context and context.action %}
      <span class="text-xs px-1.5 py-0.5 rounded {{ action_color_class(context.action.label) }}">
        {{ context.action.label }}
      </span>
    {% endif %}
  </td>
</tr>
```

### Anti-Patterns to Avoid
- **Coupling decision logic to UI code:** Keep all classification thresholds and percentile computation in `DecisionEngine`, not in Jinja2 templates or JavaScript. Templates only render pre-computed labels and colors.
- **Using float for percentile computation:** The project mandates Decimal throughout. Use `Decimal` for percentile rank, z-score, and all threshold comparisons.
- **Fetching all historical data on every dashboard refresh:** The WebSocket update loop fires every 5 seconds. Computing percentiles for 30+ pairs against full historical data each cycle would be expensive. Cache the `DecisionContext` per pair with a reasonable TTL (e.g., 60 seconds or per funding period).
- **Hard-coding tooltip text in JavaScript:** Use server-side rendered tooltips via Jinja2 macros. This keeps the glossary centralized and avoids duplicating text between JS and HTML.
- **Overcomplicating the action label logic:** The labels should be simple threshold-based classification, not ML or complex scoring. Users need clear, defensible reasons they can verify.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Percentile rank computation | Custom sorting + counting | `bisect.bisect_left` on sorted list | One-liner, correct edge cases, O(log n) |
| Trend direction | New trend algorithm | `classify_trend()` from `bot.signals.trend` | Already built, tested, uses EMA |
| Composite signal scoring | Re-implement scoring | `SignalEngine._compute_signal()` | Already computes all sub-signals, returns `CompositeSignal` |
| CSS tooltips | tippy.js or custom JS tooltip | Tailwind `group-hover` + absolute positioning | No new dependencies, works with server-side rendering |
| Percentile color mapping | Custom color logic | Simple threshold map function | Three thresholds, four colors -- a dict lookup suffices |

**Key insight:** Phase 11 is primarily a **presentation and classification layer** on top of data that already exists. The `PairAnalyzer` has historical stats, the `SignalEngine` has composite scores, and the `FundingMonitor` has live rates. The new `DecisionEngine` bridges these three data sources and produces display-ready context.

## Common Pitfalls

### Pitfall 1: Performance -- Computing Percentiles on Every WS Update
**What goes wrong:** The WebSocket update loop fires every 5 seconds. If each cycle computes percentiles for 30 pairs by fetching all historical rates from SQLite, it creates unnecessary load.
**Why it happens:** Naive integration of percentile computation into the update loop.
**How to avoid:** Cache `DecisionContext` results per pair with a TTL of 60-300 seconds. Historical percentiles change very slowly (only when new funding payments arrive every 8 hours). The cache key is `(symbol, range)`. Invalidate on new funding data arrival.
**Warning signs:** Dashboard becoming sluggish, high CPU on SQLite reads during update loop.

### Pitfall 2: Stale Signal Data When SignalEngine is Unavailable
**What goes wrong:** The `SignalEngine` requires live market data (`FundingMonitor`, `TickerService`, `HistoricalDataStore`). If any dependency is unavailable (e.g., no OHLCV data, exchange API down), the composite signal breakdown will be empty.
**Why it happens:** Phase 11 depends on Phase 5 signal infrastructure which has graceful degradation paths.
**How to avoid:** Make `SignalBreakdown` optional in `DecisionContext`. When unavailable, the action label classification should fall back to percentile + trend only (which come from historical data, not live signals). Display "Signal data unavailable" in the UI instead of empty/broken sections.
**Warning signs:** UI showing empty signal breakdown cards, action labels inconsistent with visible data.

### Pitfall 3: Misleading Percentiles for Pairs with Little History
**What goes wrong:** A pair with only 10 historical rates can produce misleading percentiles (e.g., "P95" based on just 10 data points gives false precision).
**Why it happens:** Percentile rank calculation works on any list, but its statistical meaning requires sufficient sample size.
**How to avoid:** Reuse the existing `has_sufficient_data` flag from `PairStats` (requires MIN_RECORDS = 30). When insufficient, show percentile as "N/A" or with a "Low data" warning badge (same pattern already used in pairs page ranking table). Set the action label to "Insufficient data" with low confidence.
**Warning signs:** New pairs showing "Strong opportunity" labels despite having almost no historical data.

### Pitfall 4: Tooltip Overflow on Mobile/Small Screens
**What goes wrong:** Absolute-positioned tooltips overflow the viewport on narrow screens, becoming unreadable or causing horizontal scroll.
**Why it happens:** CSS tooltips with `whitespace-nowrap` and fixed positioning relative to the trigger element.
**How to avoid:** Limit tooltip max-width (e.g., `max-w-xs`), use `whitespace-normal` for longer explanations, and add `left-0` instead of centered positioning for elements near screen edges. Test on 375px viewport width.
**Warning signs:** Tooltips truncated or causing horizontal scroll on mobile.

### Pitfall 5: Inconsistent Color Semantics Across Dashboard
**What goes wrong:** The existing dashboard uses green/red for positive/negative rates. If the new action labels use green for "Strong opportunity" and the rate is actually negative, the color signals conflict.
**Why it happens:** Action labels represent recommendation quality, not rate direction. The color systems serve different purposes.
**How to avoid:** Use distinct color palettes for different semantic domains: green/red for rate values (existing), blue/purple/amber/gray for action labels (new). Document the color system. Use blue tones for decision-context-specific UI to visually separate from rate-value colors.
**Warning signs:** Users seeing green "Strong opportunity" next to a red negative rate and being confused.

## Code Examples

Verified patterns from the existing codebase:

### Extending PairAnalyzer with Percentile Method
```python
# Source: Pattern from src/bot/analytics/pair_analyzer.py
import bisect
from decimal import Decimal

def compute_rate_percentile(
    current_rate: Decimal,
    sorted_rates: list[Decimal],
) -> Decimal:
    """Compute percentile rank (0-100) of current_rate in sorted historical rates.

    Uses bisect_left for O(log n) insertion point lookup.

    Args:
        current_rate: The current live funding rate.
        sorted_rates: Historical funding rates sorted ascending.

    Returns:
        Percentile as Decimal in [0, 100] range, quantized to 1 decimal place.
    """
    if not sorted_rates:
        return Decimal("50.0")

    n = len(sorted_rates)
    pos = bisect.bisect_left(sorted_rates, current_rate)
    return (Decimal(pos) / Decimal(n) * Decimal("100")).quantize(Decimal("0.1"))
```

### Signal Breakdown API Response Pattern
```python
# Source: Pattern from src/bot/dashboard/routes/api.py
@router.get("/decision/{symbol:path}")
async def get_decision_context(
    request: Request, symbol: str, range: str = "all"
) -> JSONResponse:
    """Phase 11: Get decision context for a single pair.

    Returns percentile, trend, signal breakdown, and action label.
    """
    decision_engine = getattr(request.app.state, "decision_engine", None)
    if decision_engine is None:
        return JSONResponse(
            content={"error": "Decision engine not available"}, status_code=501
        )
    since_ms = _range_to_since_ms(range)
    try:
        context = await decision_engine.get_decision_context(symbol, since_ms=since_ms)
        return JSONResponse(content=context.to_dict())
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

### Glossary Content Dictionary
```python
# Source: Centralized glossary for tooltip content
GLOSSARY: dict[str, str] = {
    "funding_rate": "The periodic payment between long and short positions. Positive = longs pay shorts. We collect when rate > 0.",
    "percentile": "Where the current rate sits historically. P75 means the rate is higher than 75% of historical observations.",
    "trend": "Direction of recent funding rate movement based on EMA analysis. Rising/Stable/Falling.",
    "composite_score": "Weighted combination of rate level (35%), trend (25%), persistence (25%), and basis spread (15%).",
    "persistence": "How long the rate has stayed above a threshold. Higher = more consistent opportunity.",
    "basis_spread": "Premium/discount of perpetual price vs spot. Positive basis supports positive funding rates.",
    "annualized_yield": "Fee-adjusted per-period yield extrapolated to one year. Assumes rate stays constant (which it won't).",
    "net_yield": "Average funding rate minus amortized round-trip trading fees (entry + exit).",
    "action_label": "Evidence-based recommendation derived from percentile rank, trend direction, and composite signal score.",
    "confidence": "How much historical data supports the recommendation. High = 90+ data points, Medium = 30-90, Low = <30.",
}
```

### Caching Pattern for Decision Context
```python
# Source: Pattern from src/bot/data/market_cap.py (TTL cache)
import time

class DecisionEngine:
    """Produces decision context by combining PairAnalyzer, SignalEngine, and FundingMonitor."""

    def __init__(
        self,
        pair_analyzer,
        signal_engine=None,
        funding_monitor=None,
        cache_ttl_seconds: int = 120,
    ):
        self._pair_analyzer = pair_analyzer
        self._signal_engine = signal_engine
        self._funding_monitor = funding_monitor
        self._cache: dict[str, tuple[float, DecisionContext]] = {}
        self._ttl = cache_ttl_seconds

    async def get_decision_context(
        self, symbol: str, since_ms: int | None = None
    ) -> DecisionContext:
        cache_key = f"{symbol}:{since_ms}"
        now = time.time()

        if cache_key in self._cache:
            cached_time, cached_ctx = self._cache[cache_key]
            if now - cached_time < self._ttl:
                return cached_ctx

        # Compute fresh context
        context = await self._compute_context(symbol, since_ms)
        self._cache[cache_key] = (now, context)
        return context
```

### Enhanced Funding Rates Panel with WebSocket Updates
```python
# Source: Pattern from src/bot/dashboard/update_loop.py
# In the update loop, compute decision contexts alongside funding rate data

# After gathering funding_rates:
decision_engine = getattr(app.state, "decision_engine", None)
decision_contexts = {}
if decision_engine is not None:
    for fr in funding_rates[:30]:
        try:
            ctx = await decision_engine.get_decision_context(fr.symbol)
            decision_contexts[fr.symbol] = ctx
        except Exception:
            pass  # Graceful degradation

# Render enhanced template
tpl = env.get_template("partials/funding_rates.html")
html = tpl.render(
    funding_rates=funding_rates,
    decision_contexts=decision_contexts,
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw funding rate only | Rate + historical context | Phase 11 | Users can see if current rate is historically good or bad |
| Internal signal scores | User-visible signal breakdown | Phase 11 | Transparency into what drives recommendations |
| No guidance | Action labels with evidence | Phase 11 | Users get clear "should I trade?" answers |
| Unlabeled metrics | Glossary tooltips | Phase 11 | Lowers learning curve for new users |

**Deprecated/outdated:**
- None. This phase builds new features on stable foundations.

## Open Questions

1. **Action label thresholds: what exact percentile and score cutoffs?**
   - What we know: The classification needs 4 levels (Strong, Moderate, Below average, Not recommended). Percentile is 0-100, composite score is 0-1.
   - What's unclear: The exact threshold values (e.g., P75/P50/P25 vs P80/P60/P40) should ideally be validated against historical data.
   - Recommendation: Start with P75/P50/P25 thresholds as sensible defaults matching standard quartile boundaries. Make thresholds configurable via `DecisionSettings` (pydantic-settings) so they can be tuned without code changes.

2. **Should the summary page show ALL pairs or only pairs with live rates?**
   - What we know: The funding rates panel only shows pairs with current live funding data from the exchange. The pair explorer shows all tracked pairs from historical data.
   - What's unclear: Whether the summary page should include pairs that have historical data but no current live funding rate.
   - Recommendation: Show only pairs with current live funding rates (from `FundingMonitor`), since the decision context requires a current rate to contextualize. Pairs without live data get no decision context.

3. **Should decision contexts update in real-time via WebSocket or on-demand via fetch?**
   - What we know: The existing funding rates panel updates every 5 seconds via WebSocket OOB swaps. The pairs page uses on-demand fetch() calls.
   - What's unclear: Whether the enhanced funding rates panel (with percentile badges) should be part of the WS update loop or fetched separately.
   - Recommendation: Include decision contexts in the existing WS update loop (same as funding rates panel now), using cached DecisionContext with 60-120 second TTL to avoid recomputing percentiles every 5 seconds. The summary page uses on-demand fetch() since it's a separate page visit.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `src/bot/analytics/pair_analyzer.py` -- PairStats computation, _compute_stats pattern
- Codebase analysis: `src/bot/signals/engine.py` -- SignalEngine._compute_signal(), CompositeSignal structure
- Codebase analysis: `src/bot/signals/composite.py` -- compute_composite_score() weights and formula
- Codebase analysis: `src/bot/signals/models.py` -- CompositeSignal dataclass with all sub-signal fields
- Codebase analysis: `src/bot/signals/trend.py` -- classify_trend() with EMA, TrendDirection enum
- Codebase analysis: `src/bot/dashboard/update_loop.py` -- WebSocket OOB swap pattern for real-time updates
- Codebase analysis: `src/bot/dashboard/templates/partials/funding_rates.html` -- Current panel structure to enhance
- Codebase analysis: `src/bot/dashboard/templates/pairs.html` -- Pair explorer JS patterns, Chart.js usage
- Codebase analysis: `src/bot/data/market_cap.py` -- TTL cache pattern (MarketCapService)
- Python stdlib: `bisect` module for sorted-list percentile computation

### Secondary (MEDIUM confidence)
- Tailwind CSS tooltip patterns -- `group-hover` + absolute positioning approach is well-documented in Tailwind docs

### Tertiary (LOW confidence)
- None. All patterns are derived from existing codebase analysis or Python stdlib.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- zero new dependencies, all libraries already in project
- Architecture: HIGH -- follows established service class + API + template patterns from Phases 8/10
- Pitfalls: HIGH -- derived from actual codebase analysis of data flow and performance characteristics
- Decision logic: MEDIUM -- action label thresholds are sensible defaults but not validated against real historical data

**Research date:** 2026-02-13
**Valid until:** 2026-03-13 (stable domain, no external dependency changes expected)
