# Architecture Patterns

**Domain:** Strategy Discovery features for existing Funding Rate Arbitrage Bot (v1.2)
**Researched:** 2026-02-13
**Mode:** Integration architecture for Pair Explorer, Trade Replay, Strategy Builder, Decision View

## Executive Summary

The v1.2 features are **analysis and visualization layers** that sit on top of existing infrastructure. They do not modify the trading loop, signal engine, or execution path. The primary integration points are:

1. **HistoricalDataStore** -- all new queries read from the existing SQLite database (50K+ records)
2. **BacktestEngine** -- enhanced to emit trade-level detail (currently only emits equity curve + aggregate metrics)
3. **Dashboard routes/templates** -- new pages following the established HTMX partial pattern
4. **Market cap data** -- new external data source (CoinGecko or Bybit volume proxy)

The architecture principle is **additive, not invasive**: new modules compose with existing ones rather than modifying them. This is consistent with the `Component | None = None` optional dependency injection pattern established in v1.1.

---

## Context: Existing Architecture (v1.0 + v1.1)

The system already has a well-structured architecture:

```
Dashboard (FastAPI + HTMX + Chart.js)
    |
    v
Orchestrator (scan -> rank -> signal -> size -> decide -> execute -> monitor)
    |
    +-- FundingMonitor (rate scanning, 30s polling)
    +-- SignalEngine (composite signals: trend, persistence, basis, volume)
    +-- DynamicSizer (conviction-based position sizing)
    +-- PositionManager / Executor (ABC: Paper, Live, Backtest)
    +-- PnLTracker (per-position P&L tracking)
    +-- RiskManager (exposure limits, emergency stop)
    |
    v
HistoricalDataStore (aiosqlite / SQLite WAL)
    |
    v
ExchangeClient (ccxt / Bybit)
```

**Dashboard architecture:** Jinja2 templates with HTMX partials, Chart.js for visualization, WebSocket for real-time updates, JSON API endpoints for data. Two pages: `/` (live dashboard, 8 panels) and `/backtest` (backtesting with equity curve and heatmap).

**Key patterns to preserve:**
1. Orchestrator pattern with dependency injection
2. Executor ABC for backtest/paper/live mode switching
3. HTMX partials for dashboard sections (server-renders HTML fragments)
4. Chart.js CDN for all client-side visualization
5. Decimal for all monetary math
6. aiosqlite for all persistence
7. `Component | None = None` optional injection for feature flags
8. Background task pattern with polling for long-running operations

---

## v1.2 Architecture: Analysis & Visualization Layer

v1.2 adds a **read-only analysis layer** on top of the existing data store. It does NOT modify the trading engine, signal engine, or execution path. All new components are dashboard-facing only.

```
                     EXISTING (unchanged)                    NEW (v1.2)
                    +-------------------+
                    |   Orchestrator    |
                    | (trading loop)    |
                    +-------------------+
                            |
              +-------------+-------------+
              |             |             |
    +----------------+ +---------+ +------------+
    | SignalEngine   | | PnL     | | Position   |
    | (composite     | | Tracker | | Manager    |
    |  scoring)      | |         | |            |
    +----------------+ +---------+ +------------+
              |
    +-------------------+                +---------------------+
    | HistoricalData    |<----- reads ---| PairAnalyticsService|  <-- NEW
    | Store (SQLite)    |                | (stats, rankings,   |
    +-------------------+                |  distributions)     |
              |                          +---------------------+
              |                                   |
    +-------------------+                +---------------------+
    | BacktestEngine    |---enhances-->  | TradeLog            |  <-- NEW
    | (event replay)    |                | (per-trade details) |
    +-------------------+                +---------------------+
                                                  |
    +-------------------+                +---------------------+
    | Dashboard App     |---new pages--> | Explorer/Builder/   |  <-- NEW
    | (FastAPI+HTMX)    |                | Decision pages      |
    +-------------------+                +---------------------+
                                                  |
                                         +---------------------+
                                         | MarketCapProvider   |  <-- NEW
                                         | (ranking source)    |
                                         +---------------------+
```

### Component Boundaries

| Component | Responsibility | Communicates With | Change Type |
|-----------|---------------|-------------------|-------------|
| `PairAnalyticsService` | Compute funding rate statistics, distributions, net yield per pair | `HistoricalDataStore` (reads), Dashboard routes (serves data) | **NEW** |
| `MarketCapProvider` | Rank pairs by market cap or volume proxy | `HistoricalDataStore.get_tracked_pairs()`, optional CoinGecko API | **NEW** |
| `TradeLog` (dataclass) | Per-trade detail: entry/exit timestamps, prices, reasons, fees, P&L | `BacktestEngine` (produces), Dashboard routes (renders) | **NEW** |
| `BacktestResult` | Extended with `trades: list[TradeLog]` field | BacktestEngine (produces), API routes (serializes) | **EXTENDED** |
| `BacktestEngine` | Add trade recording instrumentation in open/close blocks | `HistoricalDataStore`, `PnLTracker`, `PositionManager` | **MINOR CHANGE** |
| `HistoricalDataStore` | Add pair-level aggregate query methods | SQLite database (existing tables + indexes) | **EXTENDED** |
| Dashboard pages | 4 new pages: `/explore`, `/explore/{symbol}`, `/strategy`, `/decision` | All services via `app.state` | **NEW** |
| Dashboard API routes | New JSON endpoints for pair analytics, enhanced backtest results | `PairAnalyticsService`, `BacktestEngine` | **NEW** |
| Dashboard templates | New page templates + HTMX partials for each feature | Jinja2 rendering, Chart.js CDN | **NEW** |

---

## New Components: Detailed Design

### 1. PairAnalyticsService

**Purpose:** Compute analytical views over historical data that the dashboard consumes. Pure read-only analysis -- no trading decisions, no side effects.

**Why a separate service:** The existing `analytics/metrics.py` computes per-position metrics (Sharpe, drawdown, win rate) from `PositionPnL` objects. The pair analytics service computes per-pair metrics from raw funding rate data. Different input type, different output type, different use case. Routes should be thin -- they fetch data from services and render templates.

```python
# src/bot/analytics/pair_analytics.py

@dataclass
class PairSummary:
    symbol: str
    avg_funding_rate: Decimal
    median_funding_rate: Decimal
    std_funding_rate: Decimal
    min_funding_rate: Decimal
    max_funding_rate: Decimal
    positive_rate_pct: Decimal           # % of periods with positive rate
    percentile_25: Decimal
    percentile_75: Decimal
    total_periods: int
    data_coverage_days: int
    earliest_ms: int
    latest_ms: int
    est_annualized_yield: Decimal        # avg_rate * 3 * 365 - est_fees
    current_streak: int                  # consecutive periods above threshold
    last_volume_24h: Decimal | None

@dataclass
class PairRanking:
    symbol: str
    avg_rate: Decimal
    median_rate: Decimal
    rate_consistency: Decimal             # lower std = more consistent
    est_net_yield: Decimal
    data_coverage_days: int
    volume_24h: Decimal | None
    market_cap_tier: str                  # "mega", "large", "mid", "small", "unknown"
    rank: int

@dataclass
class DistributionBin:
    bin_start: Decimal
    bin_end: Decimal
    count: int
    percentage: Decimal


class PairAnalyticsService:
    """Computes pair-level analytics from historical data.

    Stateless service -- all data comes from HistoricalDataStore queries.
    Results are computed on-demand (no caching needed for ~20 pairs at current scale).
    """

    def __init__(
        self,
        data_store: HistoricalDataStore,
        market_cap_provider: MarketCapProvider | None = None,
    ) -> None:
        self._store = data_store
        self._market_cap = market_cap_provider

    async def get_pair_summary(self, symbol: str) -> PairSummary:
        """Compute funding rate stats for a single pair."""
        ...

    async def get_pair_distribution(
        self, symbol: str, bins: int = 20
    ) -> list[DistributionBin]:
        """Histogram of funding rates for Chart.js rendering.

        Computes bins in Python from fetched rates (SQLite lacks
        histogram functions). Typically ~2500 rates per pair for
        1 year of data -- fast to process.
        """
        ...

    async def get_all_pair_rankings(self) -> list[PairRanking]:
        """All tracked pairs ranked by estimated net yield."""
        ...

    async def get_funding_rate_timeseries(
        self, symbol: str, since_ms: int | None = None
    ) -> list[dict]:
        """Time series of funding rates for Chart.js line chart."""
        ...
```

**Integration point:** Injected into `app.state` during startup. Dashboard routes access via `request.app.state.pair_analytics`.

### 2. TradeLog and Enhanced BacktestResult

**Purpose:** The existing `BacktestEngine` tracks trades via `PnLTracker` but only exposes aggregate metrics and equity curve. Trade Replay needs per-trade detail.

**Design decision: Capture in engine, not reconstruct from PnLTracker.** The engine already has all the information at the moment of open/close decisions (entry reason, exit reason, signal scores). Recording a `TradeLog` at each decision point is simpler and captures decision context that `PnLTracker` does not store.

```python
# src/bot/backtest/models.py (extended)

@dataclass
class TradeLog:
    """A single simulated trade in a backtest."""
    trade_id: int                    # Sequential trade number
    symbol: str                      # Perp symbol

    # Entry
    entry_timestamp_ms: int
    entry_price: Decimal
    entry_reason: str                # "rate_above_threshold", "composite_signal_0.72"
    quantity: Decimal

    # Exit
    exit_timestamp_ms: int
    exit_price: Decimal
    exit_reason: str                 # "rate_below_exit", "composite_below_0.2", "backtest_end"

    # P&L breakdown
    entry_fee: Decimal
    exit_fee: Decimal
    total_funding: Decimal
    funding_payments_count: int
    net_pnl: Decimal                 # funding - fees + price_pnl

    # Derived
    holding_periods: int             # Number of funding settlements
    holding_hours: int               # Total hours held
    annualized_return: Decimal | None

    def to_dict(self) -> dict:
        """Serialize for JSON, converting Decimals to strings."""
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_timestamp_ms": self.entry_timestamp_ms,
            "exit_timestamp_ms": self.exit_timestamp_ms,
            "entry_price": str(self.entry_price),
            "exit_price": str(self.exit_price),
            "entry_reason": self.entry_reason,
            "exit_reason": self.exit_reason,
            "quantity": str(self.quantity),
            "entry_fee": str(self.entry_fee),
            "exit_fee": str(self.exit_fee),
            "total_funding": str(self.total_funding),
            "funding_payments_count": self.funding_payments_count,
            "net_pnl": str(self.net_pnl),
            "holding_periods": self.holding_periods,
            "holding_hours": self.holding_hours,
            "annualized_return": str(self.annualized_return) if self.annualized_return else None,
        }
```

**BacktestResult extension (backward compatible):**

```python
@dataclass
class BacktestResult:
    config: BacktestConfig
    equity_curve: list[EquityPoint]
    metrics: BacktestMetrics
    trades: list[TradeLog] = field(default_factory=list)  # NEW -- default empty

    def to_dict(self) -> dict:
        result = {
            "config": self.config.to_dict(),
            "equity_curve": [...],
            "metrics": {...},
        }
        if self.trades:  # Only include when populated
            result["trades"] = [t.to_dict() for t in self.trades]
        return result
```

**Engine modification scope:** The `BacktestEngine.run()` method in `engine.py` (lines ~307-384) already has open/close logic. Trade log recording adds approximately 30-40 lines:

1. Add `self._trades: list[TradeLog] = []` and `self._trade_counter = 0` in `__init__`
2. After successful `open_position()` (~line 363): store entry details in a pending trade dict
3. After successful `close_position()` (~line 310): construct `TradeLog` from pending + exit details + PnLTracker funding data
4. Include `trades=self._trades` in the returned `BacktestResult`

The existing decision flow is unchanged. The `ParameterSweep` class already discards equity curves for non-best results (`sweep.py:143-151`) -- the same pattern naturally applies to trade logs.

**Alternative considered and rejected:** Reconstructing trades from `PnLTracker.get_closed_positions()` in `_compute_metrics()`. This is simpler but loses the entry/exit reason strings (PnLTracker does not store why a position was opened or closed). The entry reason is valuable for understanding strategy behavior.

**Confidence:** HIGH.

### 3. MarketCapProvider

**Purpose:** Rank the ~20 tracked pairs by market cap for the Pair Explorer.

**Design decision: Use Bybit volume as primary proxy, CoinGecko as optional enrichment.**

Rationale:
- Bybit volume data is **already available** in `tracked_pairs.last_volume_24h` -- zero API calls needed
- CoinGecko free tier has **30 calls/min, 10K calls/month** -- sufficient but adds external dependency
- Volume and market cap are strongly correlated for top-20 crypto assets on Bybit
- Market cap rankings change slowly (daily at most)

```python
# src/bot/data/market_cap.py

class MarketCapProvider:
    """Provides market cap rankings for tracked pairs.

    Primary: Bybit 24h volume from tracked_pairs table (zero API calls).
    Optional: CoinGecko enrichment for true market cap data.
    Follows Component | None = None pattern.
    """

    def __init__(
        self,
        data_store: HistoricalDataStore,
        coingecko_enabled: bool = False,
        refresh_interval_hours: int = 6,
    ) -> None:
        self._store = data_store
        self._coingecko_enabled = coingecko_enabled
        self._refresh_interval = refresh_interval_hours * 3600
        self._cache: dict[str, Decimal] | None = None
        self._cache_time: float = 0

    async def get_rankings(self) -> list[dict]:
        """Return pairs ranked by market cap (or volume proxy)."""
        ...

    def get_tier(self, base_symbol: str) -> str:
        """Classify: mega (>$50B), large (>$10B), mid (>$1B), small (>$100M), micro."""
        ...
```

**Integration:** Created at startup, stored on `app.state.market_cap_provider`. Optional dependency of `PairAnalyticsService`.

**Confidence:** HIGH for volume proxy, MEDIUM for CoinGecko enrichment (symbol mapping needs validation).

### 4. Dashboard Pages and Routes

**Pattern reuse:** The existing dashboard follows a well-established pattern:
- `routes/pages.py`: full-page GET routes returning `TemplateResponse`
- `routes/api.py`: JSON API endpoints for HTMX partial updates and background tasks
- `templates/`: Jinja2 with `base.html` inheritance and `partials/` for HTMX fragments
- Background task pattern with task_id polling for long-running operations

**New pages:**

| Route | Template | Purpose | Data Sources |
|-------|----------|---------|--------------|
| `GET /explore` | `explore.html` | Pair rankings table with stats | `PairAnalyticsService.get_all_pair_rankings()` |
| `GET /explore/{symbol}` | `explore_detail.html` | Single pair deep-dive: rate chart, histogram, stats | `PairAnalyticsService` methods |
| `GET /strategy` | `strategy.html` | Multi-pair backtest builder with parameter tweaking | `HistoricalDataStore.get_tracked_pairs()`, backtest API |
| `GET /decision` | `decision.html` | Summary "should I trade?" view | `PairAnalyticsService` + aggregated backtest results |

**New API endpoints:**

| Endpoint | Method | Purpose | Returns |
|----------|--------|---------|---------|
| `/api/pairs/rankings` | GET | Pair rankings table data | JSON list of PairRanking |
| `/api/pairs/{symbol}/summary` | GET | Pair summary stats | JSON PairSummary |
| `/api/pairs/{symbol}/distribution` | GET | Distribution bins for Chart.js | JSON list of DistributionBin |
| `/api/pairs/{symbol}/timeseries` | GET | Funding rate time series for Chart.js | JSON list of {timestamp_ms, rate} |
| `/api/backtest/multi-pair` | POST | Run backtests across selected pairs | JSON {task_id, status} |
| `/api/backtest/trades/{task_id}` | GET | Get trade log for completed backtest | JSON list of TradeLog |

**Route organization:** Create new route modules to avoid bloating existing files:

```python
# routes/explore.py -- Pair Explorer pages and API
# routes/strategy.py -- Strategy Builder pages and API
# routes/decision.py -- Decision View page
```

Register in `app.py` following existing pattern:

```python
from bot.dashboard.routes import explore, strategy, decision
app.include_router(explore.router)
app.include_router(strategy.router)
app.include_router(decision.router)
```

**Navigation update in `base.html`:**

```html
<a href="/" class="text-gray-400 hover:text-white text-sm">Dashboard</a>
<a href="/explore" class="text-gray-400 hover:text-white text-sm">Explore</a>
<a href="/backtest" class="text-gray-400 hover:text-white text-sm">Backtest</a>
<a href="/strategy" class="text-gray-400 hover:text-white text-sm">Strategy</a>
<a href="/decision" class="text-gray-400 hover:text-white text-sm">Decision</a>
```

**New HTMX partials:**

| Partial | Used By | Chart.js? |
|---------|---------|-----------|
| `partials/pair_rankings_table.html` | `/explore` | No (table) |
| `partials/pair_rate_chart.html` | `/explore/{symbol}` | Yes (line chart) |
| `partials/pair_distribution.html` | `/explore/{symbol}` | Yes (bar chart/histogram) |
| `partials/pair_stats_card.html` | `/explore/{symbol}` | No (stats grid) |
| `partials/strategy_builder_form.html` | `/strategy` | No (form with multi-select) |
| `partials/multi_pair_results.html` | `/strategy` | Yes (comparison table + charts) |
| `partials/trade_log_table.html` | `/strategy`, `/explore/{symbol}` | No (table) |
| `partials/decision_summary.html` | `/decision` | Yes (summary cards + recommendation) |

**Confidence:** HIGH -- follows exact same patterns as existing backtest page.

---

## Data Flow

### Pair Explorer Flow (entirely new, read-only)

```
User navigates to /explore
    |
    v
Page loads with pair rankings table (server-rendered)
    |
    v
User clicks a pair row -> navigates to /explore/{symbol}
    |
    v
Page loads with stats card (server-rendered)
    |
    +-- HTMX hx-trigger="load" -> /api/pairs/{symbol}/timeseries
    |   -> Chart.js line chart of funding rate history
    |
    +-- HTMX hx-trigger="load" -> /api/pairs/{symbol}/distribution
        -> Chart.js bar chart (histogram) of rate distribution
```

### Enhanced Backtest Flow (extends existing)

```
User runs backtest (existing flow unchanged)
    |
    v
BacktestEngine.run() executes (existing event loop)
    |
    v
NEW: Engine records TradeLog entries at open/close decision points
    |
    v
BacktestResult returned with .trades populated
    |
    v
API serializes result including trades array
    |
    v
Client renders:
  - Existing: metrics cards, equity curve, heatmap
  - NEW: trade log table partial (expandable rows with P&L breakdown)
  - NEW: trade timeline on equity curve (markers at open/close points)
```

### Multi-Pair Strategy Builder Flow (new)

```
User navigates to /strategy
    |
    v
Form: select multiple pairs (checkbox list from tracked_pairs)
       + set parameters (reuses backtest config form pattern)
       + submit
    |
    v
POST /api/backtest/multi-pair
    |
    v
Background task: run_backtest() sequentially for each selected pair
    |
    v
Poll GET /api/backtest/status/{task_id} (existing pattern)
    |
    v
Render multi-pair comparison:
  - Per-pair metrics table (sortable by net P&L, win rate, etc.)
  - Aggregated summary ("X of Y pairs profitable")
  - Best/worst pair highlight
  - Trade logs per pair (expandable)
```

### Decision View Flow (new, aggregation)

```
User navigates to /decision
    |
    v
Page aggregates data from multiple sources:
  - PairAnalyticsService.get_all_pair_rankings() -- which pairs look good historically?
  - Most recent multi-pair backtest results -- what does the strategy produce?
  - Current live funding rates (from FundingMonitor via app.state) -- what is happening now?
    |
    v
Renders summary:
  - "X pairs have historically positive net yield after fees"
  - "Best performing pair in backtest: {pair} at {yield}%"
  - "Current live funding rates above threshold: {count}"
  - Traffic-light recommendation: green/yellow/red based on evidence
```

### Key Data Flow Principles

1. **No new writes to SQLite.** All v1.2 features are read-only over existing historical data.
2. **No changes to the trading loop.** Orchestrator, signal engine, execution path untouched.
3. **BacktestEngine produces more output, same input.** Backward compatible via default empty list.
4. **Dashboard is the only consumer.** No side effects on trading behavior.

---

## Patterns to Follow

### Pattern 1: Service Layer for Analytics (Existing Pattern)

**What:** `PairAnalyticsService` encapsulates all pair analysis logic, separate from route handlers.

**Why:** Matches existing `FeeCalculator`, `OpportunityRanker`, and `analytics.metrics` -- pure computation classes that routes consume. Makes analytics independently testable.

```python
# In routes/explore.py -- thin route handler
@router.get("/explore/{symbol}", response_class=HTMLResponse)
async def explore_pair_detail(request: Request, symbol: str) -> HTMLResponse:
    templates = request.app.state.templates
    pair_analytics = request.app.state.pair_analytics
    summary = await pair_analytics.get_pair_summary(symbol)
    return templates.TemplateResponse("explore_detail.html", {
        "request": request, "summary": summary, "symbol": symbol,
    })
```

### Pattern 2: Additive BacktestResult Extension

**What:** Add `trades: list[TradeLog]` with `field(default_factory=list)`.

**Why:** Default empty list means all existing code (sweep, comparison, CLI, dashboard API) works without modification. This pattern is already proven in the codebase -- `ParameterSweep` replaces equity curves with `[]` for non-best results.

### Pattern 3: Multi-Pair Backtest via Existing Background Task Pattern

**What:** Reuse the `app.state.backtest_tasks` dict and polling pattern from `api.py`.

**Why:** The existing pattern (POST creates task, returns task_id, GET polls for completion) handles the async lifecycle correctly and is already integrated with the backtest page's HTMX polling.

```python
async def _run_multi_pair_task(
    task_id: str, app_state: Any,
    config_template: BacktestConfig, symbols: list[str], db_path: str,
) -> None:
    results = {}
    for i, symbol in enumerate(symbols):
        config = config_template.with_overrides(symbol=symbol)
        result = await run_backtest(config, db_path)
        results[symbol] = result.to_dict()
        app_state.backtest_tasks[task_id]["progress"] = {
            "current": i + 1, "total": len(symbols), "current_symbol": symbol,
        }
    app_state.backtest_tasks[task_id]["result"] = results
    app_state.backtest_tasks[task_id]["status"] = "complete"
```

### Pattern 4: Chart.js Reuse for New Visualizations

**What:** Use Chart.js CDN (already loaded via `base.html`) for all new charts.

**Chart types needed:**

| Visualization | Chart.js Type | Example in codebase |
|---------------|---------------|---------------------|
| Funding rate history | Line chart | `partials/equity_curve.html` |
| Rate distribution | Bar chart (histogram) | `partials/param_heatmap.html` (bar variant) |
| Trade timeline | Scatter chart with markers | New |
| Multi-pair comparison | Grouped bar chart | New |
| Net yield overview | Horizontal bar chart | New |

### Pattern 5: Lazy Loading via HTMX for Heavy Content

**What:** Load chart data lazily via HTMX `hx-trigger="load"` on chart containers.

**Why:** Page shows stats card immediately. Charts load in parallel without blocking. Already used conceptually in backtest page (polling for results).

```html
<div hx-get="/api/pairs/{{ symbol }}/chart-partial"
     hx-trigger="load" hx-swap="innerHTML">
    <div class="animate-pulse h-64 bg-dash-card rounded"></div>
</div>
```

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Modifying BacktestEngine Core Loop Structure

**What:** Restructuring the engine's `run()` method to accommodate trade logging.
**Why bad:** The 430-line engine is well-tested. Structural changes risk regressions.
**Instead:** Add trade recording as thin instrumentation (~30 lines) around existing open/close blocks. Decision flow stays identical.

### Anti-Pattern 2: Sending Raw Rate Arrays to Browser for Histograms

**What:** Send 2500+ raw funding rate values to the browser for client-side histogram computation.
**Why bad:** Unnecessary payload size and client-side computation.
**Instead:** Compute histogram bins server-side (Python), send only 20-30 bin counts as JSON. Chart.js renders pre-computed data.

### Anti-Pattern 3: Adding CoinGecko as a Required Dependency

**What:** Making CoinGecko API required for pair rankings.
**Why bad:** Adds external API dependency, rate limits, network failure mode.
**Instead:** Use volume-based ranking from existing `tracked_pairs.last_volume_24h`. CoinGecko is optional enrichment.

### Anti-Pattern 4: Creating Separate Database for Backtest Results

**What:** Persisting backtest results to a new SQLite database.
**Why bad:** Adds lifecycle complexity for ephemeral data.
**Instead:** Keep results in memory (existing `app.state.backtest_tasks` pattern). Add `trades` to existing result dict.

### Anti-Pattern 5: Computing Statistics on Every Request

**What:** Query funding rates and compute statistics on every API call.
**Why bad:** Unnecessarily repeats computation for data that changes at most every 8 hours.
**Instead:** For the current scale (~20 pairs, ~2500 rates/pair), on-demand computation is fast enough (<50ms). If needed later, add TTL-based caching in `PairAnalyticsService`.

---

## New HistoricalDataStore Methods

Additional read methods needed. No schema changes -- existing tables and indexes support all queries.

```python
# Added to src/bot/data/store.py

async def get_funding_rate_stats(self, symbol: str) -> dict:
    """Aggregate stats for a symbol using SQLite AVG/COUNT/MIN/MAX.

    Returns: avg_rate, count, min_rate, max_rate,
             positive_rate_count, earliest_ms, latest_ms.
    """
    ...

async def get_all_pair_stats(self) -> list[dict]:
    """Aggregate stats across all tracked pairs via GROUP BY.

    Single query for the rankings table. Returns: symbol, avg_rate,
    count, earliest_ms, latest_ms.
    """
    ...
```

**Note on Decimal precision in aggregation:** SQLite's `AVG()` operates on REAL (float64). For aggregate descriptive statistics (mean, std), float64 precision is acceptable. Raw funding rate values remain stored as TEXT/Decimal for monetary precision.

**Confidence:** HIGH -- standard SQL on existing indexed columns.

---

## File Organization

### New Files

```
src/bot/
  analytics/
    pair_analytics.py          # PairAnalyticsService + PairSummary/PairRanking/DistributionBin
  data/
    market_cap.py              # MarketCapProvider
  dashboard/
    routes/
      explore.py               # Pair Explorer page routes + API endpoints
      strategy.py              # Strategy Builder page route + multi-pair API
      decision.py              # Decision View page route
    templates/
      explore.html             # Pair Explorer listing page
      explore_detail.html      # Pair detail deep-dive page
      strategy.html            # Strategy Builder page
      decision.html            # Decision View page
      partials/
        pair_rankings_table.html
        pair_rate_chart.html
        pair_distribution.html
        pair_stats_card.html
        strategy_builder_form.html
        multi_pair_results.html
        trade_log_table.html
        decision_summary.html
```

### Modified Files

```
src/bot/
  backtest/
    models.py                  # Add TradeLog dataclass, extend BacktestResult
    engine.py                  # Add trade recording (~30-40 lines of instrumentation)
  data/
    store.py                   # Add get_funding_rate_stats(), get_all_pair_stats()
  dashboard/
    app.py                     # Register new routers
    templates/
      base.html                # Add nav links for Explore, Strategy, Decision
  main.py                      # Inject PairAnalyticsService + MarketCapProvider
```

### Unchanged Files (verified against codebase)

```
src/bot/
  orchestrator.py              # NO CHANGES -- trading loop untouched
  signals/                     # NO CHANGES -- signal engine untouched
  execution/                   # NO CHANGES -- executor pattern untouched
  position/                    # NO CHANGES -- position management untouched
  pnl/                         # NO CHANGES -- P&L tracking untouched
  risk/                        # NO CHANGES -- risk management untouched
  exchange/                    # NO CHANGES -- exchange client untouched
  market_data/                 # NO CHANGES -- funding monitor untouched
  config.py                    # NO CHANGES -- all needed config already exists
  models.py                    # NO CHANGES -- trading models untouched
  backtest/runner.py           # NO CHANGES -- run_backtest() interface unchanged
  backtest/sweep.py            # NO CHANGES -- equity curve discard handles trades
  backtest/executor.py         # NO CHANGES
  backtest/data_wrapper.py     # NO CHANGES
```

---

## Scalability Considerations

| Concern | Current (~20 pairs, 50K records) | At 50 pairs, 200K records | At 200 pairs, 2M records |
|---------|----------------------------------|---------------------------|--------------------------|
| Pair analytics queries | <50ms per pair (indexed) | <100ms | Pre-computed summary table |
| Rankings computation | <100ms (GROUP BY on 50K rows) | <200ms | Cache with 1-hour TTL |
| Distribution (Python binning) | <20ms per pair | <50ms | Still fast (one symbol) |
| Multi-pair backtest (20 pairs) | ~20s sequential | ~50s for 50 | Background task with progress |
| Trade log serialization | <1ms for ~50 trades | <5ms | Paginate API response |
| SQLite concurrent reads | WAL mode handles well | WAL mode handles well | Still fine -- reads only |

No optimization needed for initial implementation at current scale.

---

## Dependency Graph and Build Order

```
Phase 1: Analytics Foundation (no dashboard dependencies)
  |-- PairAnalyticsService + data models (PairSummary, PairRanking, etc.)
  |-- HistoricalDataStore new read methods (get_funding_rate_stats, get_all_pair_stats)
  |-- TradeLog dataclass in backtest/models.py
  |-- Unit tests for analytics computations

Phase 2: Backtest Enhancement (depends on TradeLog from Phase 1)
  |-- BacktestEngine trade recording instrumentation (~30 lines)
  |-- BacktestResult.trades field extension
  |-- Verify existing backtest tests still pass

Phase 3: Pair Explorer UI (depends on PairAnalyticsService from Phase 1)
  |-- /explore page with rankings table
  |-- /explore/{symbol} detail page with charts
  |-- MarketCapProvider (volume proxy)
  |-- Chart.js line chart + histogram partials
  |-- Nav links in base.html

Phase 4: Strategy Builder + Trade Replay (depends on Phases 2 + 3)
  |-- /strategy page with multi-pair selection form
  |-- Multi-pair backtest API endpoint
  |-- Trade log table partial
  |-- Multi-pair comparison visualization

Phase 5: Decision View (depends on Phases 3 + 4)
  |-- /decision summary page
  |-- Aggregation of pair analytics + best backtest results
  |-- Recommendation display
```

**Critical path:** Phase 1 -> Phase 2 -> Phase 4 -> Phase 5

**Parallel opportunities:**
- Phase 3 (pair explorer UI) can be built in parallel with Phase 2 (backtest enhancement) since they share only the Phase 1 foundation
- Within Phase 3, MarketCapProvider is independent of the UI templates

**Why this order:**
1. Analytics service first -- both explorer and strategy builder depend on it
2. Backtest enhancement before strategy builder -- trade replay is the core differentiator
3. Decision view last -- it aggregates data from both explorer and strategy builder

---

## Integration with app.state

Following the existing pattern in `main.py`:

```python
# In main.py startup (additions to existing wiring)

# New v1.2 services
pair_analytics = PairAnalyticsService(data_store=data_store)
market_cap_provider = MarketCapProvider(data_store=data_store)

# Inject into app state (same pattern as existing components)
dashboard_app.state.pair_analytics = pair_analytics
dashboard_app.state.market_cap_provider = market_cap_provider
```

In `app.py`:

```python
# Register new routers (same pattern as existing)
from bot.dashboard.routes import explore, strategy, decision
app.include_router(explore.router)
app.include_router(strategy.router)
app.include_router(decision.router)
```

---

## Sources

- Codebase analysis: `src/bot/` (9,540 LOC Python, 1,320 LOC HTML, 286 tests)
  - `orchestrator.py` (802 lines) -- trading loop, untouched
  - `backtest/engine.py` (593 lines) -- primary modification target for trade logging
  - `backtest/models.py` (240 lines) -- extension target for TradeLog
  - `data/store.py` (326 lines) -- extension target for aggregate queries
  - `dashboard/app.py` (86 lines) -- router registration point
  - `dashboard/routes/pages.py` (115 lines) -- page route pattern to follow
  - `dashboard/routes/api.py` (519 lines) -- API + background task pattern to follow
  - `dashboard/templates/base.html` (56 lines) -- navigation extension point
- [HTMX + FastAPI dashboard patterns](https://testdriven.io/blog/fastapi-htmx/)
- [FastAPI HTMX hypermedia applications](https://medium.com/@strasbourgwebsolutions/fastapi-as-a-hypermedia-driven-application-w-htmx-jinja2templates-644c3bfa51d1)
- [CoinGecko API coins/markets endpoint](https://docs.coingecko.com/reference/coins-markets)
- [Bybit tickers API for volume data](https://bybit-exchange.github.io/docs/v5/market/tickers)
- [SQLite schema design for financial data](https://medium.com/data-science/how-to-store-financial-market-data-for-backtesting-84b95fc016fc)
- [Backtesting trade-level output patterns](https://www.quantstart.com/articles/backtesting-systematic-trading-strategies-in-python-considerations-and-open-source-frameworks/)

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Component boundaries | HIGH | Verified against existing codebase with line-level references |
| BacktestEngine enhancement | HIGH | Existing code paths clearly identified, ~30 lines change |
| Dashboard page patterns | HIGH | Exact pattern reuse from backtest page and main dashboard |
| PairAnalyticsService design | HIGH | Standard service layer pattern, SQL on indexed columns |
| MarketCapProvider (volume) | HIGH | Data already exists in tracked_pairs table |
| MarketCapProvider (CoinGecko) | MEDIUM | Symbol mapping needs validation, external dependency |
| Build order | HIGH | Based on actual dependency analysis of imports and data flow |
| Scalability estimates | MEDIUM | Based on query analysis, not measured |
