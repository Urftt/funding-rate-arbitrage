# Phase 6: Backtest Engine - Research

**Researched:** 2026-02-12
**Domain:** Event-driven backtesting, historical data replay, parameter optimization, equity curve visualization
**Confidence:** HIGH

## Summary

This phase builds a backtest engine that replays historical data through the existing strategy pipeline to produce realistic P&L results. The defining constraint is BKTS-02: the backtest MUST reuse the production `FeeCalculator`, `PnLTracker`, and `PositionManager` -- no separate simulation math. This means the backtest engine is an event-driven harness that feeds historical data into the same code path the live bot uses, rather than a separate analytical model.

The codebase already has everything needed for the data layer (Phase 4's `HistoricalDataStore` with `get_funding_rates()` and `get_ohlcv_candles()`) and the decision logic (Phase 5's `SignalEngine` for composite mode, `OpportunityRanker` for simple mode). The backtest engine's job is: (1) walk through historical funding rate timestamps in chronological order, (2) at each timestamp, construct the data snapshot that the strategy would have seen at that moment (no look-ahead), (3) feed that snapshot through the entry/exit decision logic, (4) use `FeeCalculator` and `PnLTracker` to track P&L, and (5) collect the time series of P&L for equity curve output.

The parameter sweep (BKTS-03) is a nested loop: for each combination of parameters, run a full backtest and collect the final metrics. This is embarrassingly parallel but can start single-threaded (sequential loop) since Python's `Decimal` arithmetic is CPU-bound and GIL-bound. The dashboard integration (BKTS-04) requires new API endpoints and HTML templates for equity curve charts and a parameter heatmap. The existing dashboard uses HTMX + Tailwind + Jinja2 templates, so the backtest results page follows the same pattern. For the equity curve chart, a lightweight JavaScript charting library is needed since the dashboard has no existing charting capability.

**Primary recommendation:** Create a new `src/bot/backtest/` module with an event-driven `BacktestEngine` that constructs a `BacktestExecutor` (an `Executor` subclass that fills orders at historical prices without exchange interaction), wires it into the existing `PositionManager`/`FeeCalculator`/`PnLTracker` pipeline, and walks through historical timestamps chronologically. Add a `ParameterSweep` runner that iterates over parameter grids. Add dashboard routes and templates for results display. Use Chart.js (CDN) for the equity curve chart.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `decimal` | stdlib | All P&L and score computations | Already used throughout codebase; required by project convention |
| `aiosqlite` | 0.22+ (already installed) | Read historical data for replay | Already used by Phase 4 HistoricalDataStore |
| `dataclasses` | stdlib | Backtest result models | Project convention for data models |
| `itertools.product` | stdlib | Parameter grid generation for sweeps | Standard library; no external dependency needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Chart.js | 4.x (CDN) | Equity curve and heatmap visualization in dashboard | BKTS-04: dashboard displays backtest results |
| `json` | stdlib | Serialize backtest results for API responses | Dashboard API endpoints for backtest results |
| `asyncio` | stdlib | Async backtest execution | BacktestEngine is async because HistoricalDataStore and SignalEngine are async |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Chart.js (CDN) | Plotly.js, D3.js | Chart.js is simpler, smaller, perfect for line charts and heatmaps; Plotly is heavier; D3 requires more code |
| Sequential parameter sweep | `concurrent.futures.ProcessPoolExecutor` | Parallelism would help but Decimal arithmetic is GIL-bound; multiprocess adds complexity for pickling async objects; start sequential, optimize later if needed |
| Custom event-driven loop | `backtrader`, `vectorbt` | These are massive frameworks; our backtest is specific to funding rate arbitrage (not general price-based trading); reusing production code (BKTS-02) is incompatible with external frameworks |
| In-memory result storage | SQLite result storage | Keep results in memory for simplicity; backtests are bounded in duration and produce small result sets |

**Installation:**
No new Python packages needed. Chart.js loaded via CDN in the dashboard template (same pattern as HTMX and Tailwind).

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
```

## Architecture Patterns

### Recommended Project Structure
```
src/bot/
├── backtest/                    # NEW: Backtest engine module
│   ├── __init__.py              # Public exports
│   ├── models.py                # BacktestConfig, BacktestResult, EquityPoint, SweepResult
│   ├── executor.py              # BacktestExecutor (Executor subclass, fills at historical prices)
│   ├── engine.py                # BacktestEngine (event-driven replay loop)
│   ├── runner.py                # run_backtest() and run_parameter_sweep() entry points
│   └── sweep.py                 # ParameterGrid generation and sweep orchestration
├── dashboard/
│   ├── routes/
│   │   ├── api.py               # MODIFIED: Add backtest API endpoints
│   │   └── pages.py             # MODIFIED: Add backtest results page
│   └── templates/
│       ├── backtest.html        # NEW: Backtest results page
│       └── partials/
│           ├── backtest_form.html    # NEW: Backtest configuration form
│           ├── equity_curve.html     # NEW: Chart.js equity curve
│           └── param_heatmap.html    # NEW: Parameter comparison heatmap
├── config.py                    # MODIFIED: Add BacktestSettings
└── main.py                      # MODIFIED: Wire backtest routes
```

### Pattern 1: BacktestExecutor (Executor ABC Implementation)
**What:** A backtest-specific `Executor` subclass that fills orders at historical prices from the data store, without any exchange interaction. This is the key to reusing the production `PositionManager` -- by swapping the executor, the entire position lifecycle works identically but with historical data.
**When to use:** During backtest replay, the `PositionManager` calls `executor.place_order()` just like in production. The `BacktestExecutor` returns `OrderResult` with historical prices and calculated fees.
**Why:** Satisfies BKTS-02 (reuse production code). The `PositionManager`, `FeeCalculator`, and `PnLTracker` don't know they're running a backtest.

```python
from bot.execution.executor import Executor
from bot.models import OrderRequest, OrderResult, OrderSide

class BacktestExecutor(Executor):
    """Executor that fills orders at historical prices for backtesting.

    Maintains a price feed that the engine updates at each timestamp.
    Orders fill instantly at the current historical price with configured slippage.
    """

    def __init__(self, fee_settings: FeeSettings) -> None:
        self._fee_settings = fee_settings
        self._current_prices: dict[str, Decimal] = {}
        self._slippage = Decimal("0.0005")  # Match PaperExecutor

    def set_prices(self, prices: dict[str, Decimal]) -> None:
        """Update current prices for the simulation timestamp."""
        self._current_prices = prices

    async def place_order(self, request: OrderRequest) -> OrderResult:
        price = self._current_prices[request.symbol]
        if request.side == OrderSide.BUY:
            fill_price = price * (Decimal("1") + self._slippage)
        else:
            fill_price = price * (Decimal("1") - self._slippage)

        fee_rate = (
            self._fee_settings.spot_taker
            if request.category == "spot"
            else self._fee_settings.perp_taker
        )
        fee = request.quantity * fill_price * fee_rate

        return OrderResult(
            order_id=f"bt_{uuid4().hex[:12]}",
            symbol=request.symbol,
            side=request.side,
            filled_qty=request.quantity,
            filled_price=fill_price,
            fee=fee,
            timestamp=self._current_timestamp,
            is_simulated=True,
        )

    async def cancel_order(self, order_id, symbol, category="linear") -> bool:
        return True  # Backtest orders are instant
```

### Pattern 2: Event-Driven Replay Loop (No Look-Ahead)
**What:** The backtest engine walks through historical timestamps in chronological order. At each funding period timestamp, it constructs the data snapshot visible at that moment (all data with `timestamp_ms <= current_ts`) and feeds it through the strategy.
**When to use:** The core backtest loop.
**Why:** Prevents look-ahead bias (BKTS-01). The strategy only sees data that was available at each decision point.

```python
class BacktestEngine:
    """Event-driven backtest that replays historical data through the strategy pipeline."""

    async def run(self, config: BacktestConfig) -> BacktestResult:
        # 1. Load ALL historical data for the date range
        all_funding_rates = await self._data_store.get_funding_rates(
            symbol=config.symbol, since_ms=config.start_ms, until_ms=config.end_ms
        )

        # 2. Walk through funding periods chronologically
        equity_curve = []
        for i, fr in enumerate(all_funding_rates):
            current_ts = fr.timestamp_ms

            # 3. Construct "visible" data snapshot (no look-ahead)
            visible_rates = all_funding_rates[:i + 1]  # Only past + current

            # 4. Build FundingRateData from historical record
            funding_snapshot = FundingRateData(
                symbol=fr.symbol,
                rate=fr.funding_rate,
                next_funding_time=current_ts + fr.interval_hours * 3600 * 1000,
                interval_hours=fr.interval_hours,
                mark_price=ohlcv_close_at(current_ts),  # From OHLCV data
                volume_24h=volume_24h_at(current_ts),    # From OHLCV data
            )

            # 5. Update executor prices
            self._executor.set_prices(prices_at(current_ts))

            # 6. Run strategy decision (same code as production)
            if config.strategy_mode == "composite":
                await self._signal_engine_cycle(funding_snapshot, visible_rates)
            else:
                await self._simple_threshold_cycle(funding_snapshot)

            # 7. Simulate funding settlement for open positions
            self._settle_funding(funding_snapshot)

            # 8. Record equity point
            portfolio = self._pnl_tracker.get_portfolio_summary()
            equity_curve.append(EquityPoint(
                timestamp_ms=current_ts,
                equity=portfolio["net_portfolio_pnl"],
            ))

        return BacktestResult(
            config=config,
            equity_curve=equity_curve,
            final_pnl=...,
            metrics=...,
        )
```

### Pattern 3: Strategy Abstraction for v1.0 vs v1.1 Comparison
**What:** The backtest engine accepts a `strategy_mode` parameter (`"simple"` or `"composite"`) and uses the same branching logic as the orchestrator to run either path. This enables BKTS-05 (side-by-side comparison).
**When to use:** When running comparison backtests.
**Why:** Reuses the exact same decision logic. The only difference is which scoring path is active.

```python
# Run both strategies over the same data, compare results
simple_result = await engine.run(BacktestConfig(
    strategy_mode="simple",
    start_ms=start, end_ms=end,
    min_funding_rate=Decimal("0.0003"),
))

composite_result = await engine.run(BacktestConfig(
    strategy_mode="composite",
    start_ms=start, end_ms=end,
    signal_weights={"rate_level": "0.35", "trend": "0.25", ...},
    entry_threshold=Decimal("0.5"),
    exit_threshold=Decimal("0.3"),
))
```

### Pattern 4: Parameter Grid Sweep
**What:** Generate all combinations of parameter values using `itertools.product`, run a backtest for each, and collect results into a matrix for heatmap display.
**When to use:** BKTS-03 parameter optimization.
**Why:** Simple, correct, and transparent. No optimization library needed.

```python
from itertools import product

class ParameterSweep:
    """Run backtests over a grid of parameter combinations."""

    async def run(
        self,
        base_config: BacktestConfig,
        param_grid: dict[str, list],  # e.g., {"entry_threshold": [0.3, 0.4, 0.5], ...}
    ) -> list[SweepResult]:
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        results = []

        for combo in product(*values):
            params = dict(zip(keys, combo))
            config = base_config.with_overrides(**params)
            result = await self._engine.run(config)
            results.append(SweepResult(params=params, result=result))

        return results
```

### Pattern 5: Dashboard Integration with Dedicated Backtest Page
**What:** A separate `/backtest` page in the dashboard (not crammed into the main dashboard) with a configuration form, run button, and results display area. Uses HTMX for form submission and result loading.
**When to use:** BKTS-04 dashboard display.
**Why:** Backtest is a distinct workflow from live monitoring. A separate page keeps the main dashboard clean.

```python
# In dashboard/routes/pages.py
@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    return templates.TemplateResponse("backtest.html", {"request": request})

# In dashboard/routes/api.py
@router.post("/backtest/run")
async def run_backtest(request: Request) -> JSONResponse:
    body = await request.json()
    config = BacktestConfig.from_dict(body)
    result = await run_backtest_with_engine(config, request.app.state)
    return JSONResponse(content=result.to_dict())
```

### Anti-Patterns to Avoid
- **Reimplementing fee/P&L math in the backtest:** Violates BKTS-02. The entire point is reusing `FeeCalculator` and `PnLTracker`. If you find yourself writing `fee = quantity * price * rate` in backtest code, you are doing it wrong.
- **Loading the entire history into memory at once for all pairs:** Memory explosion. Load per-symbol, and only for the backtest date range.
- **Using `time.time()` in backtest code:** The backtest must use simulated timestamps from historical data, not wall-clock time. Any production code that uses `time.time()` (e.g., `PnLTracker.record_close`) needs the backtest harness to inject the simulated timestamp.
- **Making the backtest synchronous:** The `HistoricalDataStore` and `SignalEngine` are async. The backtest engine must be async too.
- **Coupling backtest to the live Orchestrator:** Do NOT run the backtest by calling `orchestrator._autonomous_cycle()`. The orchestrator depends on live exchange connections, funding monitors, etc. Instead, extract the decision logic into a callable that the backtest engine invokes directly.
- **Blocking the main event loop during parameter sweep:** Long-running sweeps must not freeze the dashboard. Run backtest in background task, report progress.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fee calculation | Custom fee math in backtest | `FeeCalculator.calculate_entry_fee()` / `calculate_exit_fee()` | BKTS-02 requirement; production code is already correct |
| P&L tracking | Custom P&L accumulation | `PnLTracker.record_open()` / `record_close()` / `record_funding_payment()` | BKTS-02 requirement; avoids divergence between backtest and production |
| Position lifecycle | Custom position state tracking | `PositionManager` with `BacktestExecutor` | Reuses validated position open/close flow |
| Composite signal scoring | Custom signal math in backtest | `SignalEngine.score_opportunities()` | Reuses validated signal pipeline |
| Simple threshold scoring | Custom threshold logic in backtest | `OpportunityRanker.rank_opportunities()` | Reuses validated v1.0 path |
| Analytics (Sharpe, drawdown) | Custom analytics for backtest results | `bot.analytics.metrics` module | Already implements sharpe_ratio, max_drawdown, win_rate |
| Parameter grid generation | Custom nested loops | `itertools.product` | Stdlib; correct; handles any number of dimensions |
| Chart rendering | Server-side chart generation (matplotlib) | Chart.js in browser (CDN) | No Python dependency; renders in browser; interactive; CDN pattern matches existing HTMX/Tailwind approach |

**Key insight:** The entire backtest engine is essentially a data replay harness. The actual strategy logic, fee math, and P&L tracking already exist. The new code is: (1) a historical price executor, (2) a chronological replay loop, (3) a parameter sweep runner, (4) data models for results, and (5) dashboard UI for display.

## Common Pitfalls

### Pitfall 1: Look-Ahead Bias in Signal Computation
**What goes wrong:** The signal engine fetches ALL historical funding rates for a symbol (including future data) when computing trend/persistence at a past timestamp.
**Why it happens:** In production, `SignalEngine._compute_signal()` calls `data_store.get_funding_rates(symbol=fr.symbol)` without time bounds. During backtest, this would return data that didn't exist yet at the simulated timestamp.
**How to avoid:** The backtest engine must intercept or wrap the data store calls to enforce `until_ms <= current_backtest_timestamp`. Two approaches: (a) pass a `BacktestDataStore` wrapper that automatically applies the time cutoff, or (b) pre-slice the data before passing to the signal engine. Option (a) is cleaner because it works transparently with the existing `SignalEngine` code.
**Warning signs:** Backtest results that are suspiciously good (the strategy "knows" the future).

### Pitfall 2: `time.time()` in Production Code Breaking Simulated Time
**What goes wrong:** `PnLTracker.record_close()` sets `pnl.closed_at = time.time()`, which records the wall-clock time, not the simulated backtest timestamp. This breaks analytics that sort by `closed_at`.
**Why it happens:** Production code naturally uses wall-clock time.
**How to avoid:** Inject a clock abstraction. The simplest approach: give the `PnLTracker` an optional `time_fn: Callable[[], float]` parameter that defaults to `time.time` in production but is overridden to return the simulated timestamp during backtests. The same pattern for `PositionManager` (which uses `time.time()` in `Position.opened_at`).
**Warning signs:** All backtest positions having the same `closed_at` timestamp (the time the backtest was run, not the simulated close time).

### Pitfall 3: TickerService Async Locks in Synchronous-Like Backtest
**What goes wrong:** The production `TickerService` uses `asyncio.Lock` for concurrent access. During backtest, the engine updates prices and then immediately reads them. If the engine uses a production `TickerService`, the async lock overhead is unnecessary but not harmful.
**Why it happens:** The `TickerService` was designed for concurrent real-time access.
**How to avoid:** For the backtest, either (a) use a simplified `BacktestTickerService` without locks (since backtest is single-threaded), or (b) just use the production `TickerService` and accept the minor overhead. Option (b) is simpler and consistent with BKTS-02 philosophy.
**Warning signs:** No actual problem in practice, but option (a) is marginally cleaner.

### Pitfall 4: OHLCV Price Alignment with Funding Rate Timestamps
**What goes wrong:** Funding rates have timestamps every 4-8h, but OHLCV candles are hourly. The backtest needs to find the OHLCV close price at the funding rate timestamp.
**Why it happens:** Funding rates and OHLCV have different granularity.
**How to avoid:** For each funding rate timestamp, find the most recent OHLCV candle with `timestamp_ms <= funding_rate.timestamp_ms`. This is a simple binary search or linear scan on the sorted candle list. Pre-index candles by timestamp for O(1) lookup.
**Warning signs:** Using interpolation or averaging instead of the most recent available candle (which introduces look-ahead).

### Pitfall 5: Memory Growth During Parameter Sweep
**What goes wrong:** Running 100+ backtests in a sweep, each storing a full equity curve and position history, causes memory to grow substantially.
**Why it happens:** Each backtest creates new `PnLTracker`, `PositionManager`, etc. with position history.
**How to avoid:** After extracting final metrics from each backtest run, discard the intermediate state. Only keep the summary (final P&L, Sharpe ratio, max drawdown, equity curve). For the sweep heatmap, only the final metric value per parameter combination is needed.
**Warning signs:** Memory growth proportional to sweep size rather than constant per run.

### Pitfall 6: PositionManager Asyncio Lock During Backtest
**What goes wrong:** `PositionManager` uses `asyncio.Lock` for concurrent access. During backtest, there is only one "thread" but the lock is still acquired/released.
**Why it happens:** Production `PositionManager` was designed for concurrent access from orchestrator + dashboard.
**How to avoid:** Accept the overhead (trivial in backtest context) or provide the lock as optional. The simpler approach is to just use the production `PositionManager` as-is.
**Warning signs:** No actual problem; the async lock works fine in single-"thread" async context.

### Pitfall 7: Spot Symbol Derivation Without Live Markets Dict
**What goes wrong:** Both `OpportunityRanker` and `SignalEngine` require a `markets` dict to derive spot symbols from perp symbols. In production, this comes from `exchange_client.get_markets()`. During backtest, there is no live exchange connection.
**Why it happens:** The backtest doesn't connect to the exchange.
**How to avoid:** Build a static `markets` dict from the historical data. Since the backtest only processes pairs that have historical data in the database, the backtest engine can construct a minimal `markets` dict with the required `base`, `quote`, `spot`, and `active` fields for each tracked pair. Alternatively, pre-compute the spot symbol mapping at backtest startup.
**Warning signs:** `OpportunityRanker` or `SignalEngine` returning empty results because spot symbol derivation fails.

### Pitfall 8: Dashboard Blocking During Long Backtest Runs
**What goes wrong:** A parameter sweep over a large grid (e.g., 5x5x5 = 125 combinations over 1 year of data) takes minutes. If run synchronously in the API handler, the dashboard freezes.
**Why it happens:** FastAPI runs request handlers on the event loop. A long-running computation blocks the loop.
**How to avoid:** Run backtests as background tasks (`asyncio.create_task`). The API endpoint returns immediately with a task ID. A separate status endpoint returns progress and results. The dashboard polls for completion using HTMX polling.
**Warning signs:** Dashboard becoming unresponsive when a backtest is running.

## Code Examples

### BacktestConfig Model
```python
# Source: Project convention from config.py and models.py
from dataclasses import dataclass, field
from decimal import Decimal

@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""
    symbol: str  # e.g., "BTC/USDT:USDT"
    start_ms: int  # Start timestamp (milliseconds)
    end_ms: int  # End timestamp (milliseconds)
    strategy_mode: str = "simple"  # "simple" or "composite"
    initial_capital: Decimal = Decimal("10000")

    # Simple strategy params
    min_funding_rate: Decimal = Decimal("0.0003")
    exit_funding_rate: Decimal = Decimal("0.0001")

    # Composite strategy params (only used when strategy_mode="composite")
    entry_threshold: Decimal = Decimal("0.5")
    exit_threshold: Decimal = Decimal("0.3")
    weight_rate_level: Decimal = Decimal("0.35")
    weight_trend: Decimal = Decimal("0.25")
    weight_persistence: Decimal = Decimal("0.25")
    weight_basis: Decimal = Decimal("0.15")

    # Signal params
    trend_ema_span: int = 6
    persistence_threshold: Decimal = Decimal("0.0003")
    persistence_max_periods: int = 30

    def with_overrides(self, **kwargs) -> "BacktestConfig":
        """Return a copy with parameter overrides applied."""
        import dataclasses
        return dataclasses.replace(self, **kwargs)
```

### BacktestResult Model
```python
@dataclass
class EquityPoint:
    """Single point on the equity curve."""
    timestamp_ms: int
    equity: Decimal

@dataclass
class BacktestResult:
    """Complete result from a single backtest run."""
    config: BacktestConfig
    equity_curve: list[EquityPoint]
    total_trades: int
    winning_trades: int
    net_pnl: Decimal
    total_fees: Decimal
    total_funding: Decimal
    sharpe_ratio: Decimal | None
    max_drawdown: Decimal | None
    win_rate: Decimal | None
    duration_days: int

@dataclass
class SweepResult:
    """Result from a parameter sweep with multiple backtest runs."""
    param_grid: dict[str, list]
    results: list[tuple[dict, BacktestResult]]  # (params, result) pairs
```

### Time-Bounded Data Store Wrapper (Anti-Look-Ahead)
```python
class BacktestDataStoreWrapper:
    """Wraps HistoricalDataStore to enforce time boundaries (no look-ahead).

    All queries are automatically bounded to until_ms <= current_backtest_time.
    """

    def __init__(self, store: HistoricalDataStore) -> None:
        self._store = store
        self._current_time_ms: int = 0

    def set_current_time(self, timestamp_ms: int) -> None:
        """Advance the simulated clock."""
        self._current_time_ms = timestamp_ms

    async def get_funding_rates(
        self, symbol: str, since_ms: int | None = None, until_ms: int | None = None
    ) -> list[HistoricalFundingRate]:
        effective_until = min(until_ms, self._current_time_ms) if until_ms else self._current_time_ms
        return await self._store.get_funding_rates(
            symbol=symbol, since_ms=since_ms, until_ms=effective_until
        )

    async def get_ohlcv_candles(
        self, symbol: str, since_ms: int | None = None, until_ms: int | None = None
    ) -> list[OHLCVCandle]:
        effective_until = min(until_ms, self._current_time_ms) if until_ms else self._current_time_ms
        return await self._store.get_ohlcv_candles(
            symbol=symbol, since_ms=since_ms, until_ms=effective_until
        )
```

### Chart.js Equity Curve Template
```html
<!-- Source: Chart.js CDN pattern, matching existing Tailwind/HTMX dashboard -->
<div class="bg-dash-card rounded-lg border border-dash-border p-4">
    <h3 class="text-white font-semibold mb-2">Equity Curve</h3>
    <canvas id="equity-chart" height="300"></canvas>
</div>

<script>
const ctx = document.getElementById('equity-chart').getContext('2d');
new Chart(ctx, {
    type: 'line',
    data: {
        labels: equityData.map(p => new Date(p.timestamp_ms).toLocaleDateString()),
        datasets: [{
            label: 'Portfolio P&L',
            data: equityData.map(p => parseFloat(p.equity)),
            borderColor: '#22c55e',
            fill: false,
            tension: 0.1,
        }]
    },
    options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#e2e8f0' } } },
        scales: {
            x: { ticks: { color: '#94a3b8' } },
            y: { ticks: { color: '#94a3b8' } },
        }
    }
});
</script>
```

### Parameter Heatmap for Two-Dimensional Sweep
```html
<!-- Heatmap for entry_threshold vs exit_threshold, colored by net P&L -->
<div class="bg-dash-card rounded-lg border border-dash-border p-4">
    <h3 class="text-white font-semibold mb-2">Parameter Heatmap: Net P&L</h3>
    <canvas id="heatmap-chart" height="300"></canvas>
</div>

<script>
// Chart.js matrix chart plugin or custom rendering via HTML table with colored cells
// Simpler approach: HTML table with inline background-color based on P&L value
</script>
```

### Multi-Symbol Backtest Support
```python
# A backtest can run over multiple symbols simultaneously (multi-pair portfolio)
@dataclass
class MultiSymbolBacktestConfig(BacktestConfig):
    """Backtest config for multiple symbols (portfolio-level)."""
    symbols: list[str] = field(default_factory=list)
    max_simultaneous_positions: int = 5
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| External backtesting frameworks (backtrader, vectorbt) | In-application event-driven backtest reusing production code | Modern practice for strategy-specific bots | Eliminates divergence between backtest and live execution |
| Float-based P&L approximation in backtests | Decimal-precision P&L via production FeeCalculator/PnLTracker | Project convention | Exact fee accounting, no floating-point drift |
| Server-side chart generation (matplotlib PNG) | Client-side Chart.js rendering | Standard for web dashboards | Interactive, no Python dependency, real-time updates |
| Batch parameter optimization (scipy.optimize) | Grid sweep with exhaustive search | Appropriate for small parameter spaces | Transparent, reproducible, no convergence issues |

**Deprecated/outdated:**
- No deprecations. This is new functionality.

## Key Design Decisions for Planner

### 1. BacktestExecutor as the Executor Swap
The fundamental design: create a `BacktestExecutor` that implements the `Executor` ABC, filling orders at historical prices. Wire it into the same `PositionManager` that production uses. The `PositionManager` doesn't know it's running a backtest. This is the cleanest way to satisfy BKTS-02.

### 2. Time Injection for Simulated Clock
Production code uses `time.time()` in several places (`PnLTracker.record_close`, `PositionManager.open_position`, `FundingPayment.timestamp`). The backtest needs these to use simulated time. The cleanest approach: add an optional `time_fn: Callable[[], float] = time.time` parameter to `PnLTracker` and have the backtest engine provide a lambda that returns the current simulated timestamp. This is a minimal, non-breaking change.

### 3. Data Store Wrapper for Look-Ahead Prevention
The `SignalEngine` calls `data_store.get_funding_rates(symbol=...)` without time bounds. During backtest, this must be bounded to the current simulated time. A `BacktestDataStoreWrapper` that proxies all calls with an automatic `until_ms` bound is the cleanest solution. The `SignalEngine` receives the wrapper and doesn't need any changes.

### 4. Static Markets Dict for Offline Execution
The strategy pipeline needs a `markets` dict for spot symbol derivation. In backtest, build this statically from the tracked pairs in the database. The structure is simple: for each `SYMBOL/USDT:USDT`, create entries for both the perp and spot (`SYMBOL/USDT`) markets.

### 5. Backtest Scope: Single-Pair First, Multi-Pair Later
Start with single-pair backtests (one symbol over a date range). This is simpler and covers the core use case. Multi-pair portfolio backtests add complexity (position limit management, capital allocation) but share the same engine. The `BacktestConfig` can support both with `symbol` (single) or `symbols` (multi).

### 6. Dashboard: Separate Backtest Page
Backtest results should live on a `/backtest` page, not clutter the main monitoring dashboard. The form collects: symbol, date range, strategy mode, and parameter overrides. Results display: equity curve, summary metrics, and comparison table (for v1.0 vs v1.1). For sweep results: parameter heatmap.

### 7. Background Execution for Long Runs
Backtest runs (especially sweeps) can take significant time. The API endpoint should start the backtest as a background task and return a task ID. The frontend polls for completion. Store in-progress results in `app.state.backtest_results`.

## Open Questions

1. **Multi-pair vs single-pair backtest scope for initial implementation**
   - What we know: BKTS-01 says "replays historical data through strategy pipeline." The production bot manages multiple pairs simultaneously.
   - What's unclear: Whether the initial backtest should support multi-pair portfolio simulation or just single-pair P&L.
   - Recommendation: Start with single-pair backtests for simplicity. The core engine design supports multi-pair (just loop over multiple symbols), but the P&L tracking and capital allocation become more complex. Single-pair gives immediate value for parameter optimization.
   - **Confidence:** MEDIUM (single-pair is pragmatic; multi-pair is more realistic)

2. **Heatmap visualization: Chart.js matrix plugin vs HTML table**
   - What we know: Chart.js has an official matrix chart type via the `chartjs-chart-matrix` plugin. An HTML table with colored cells is simpler but less polished.
   - What's unclear: Whether the matrix plugin is stable and well-documented enough.
   - Recommendation: Use a simple HTML table with Tailwind background color classes for the heatmap. It is simpler, requires no additional JS dependency, and the grid sizes are small (typically 5x5 to 10x10). Chart.js line chart for equity curve only.
   - **Confidence:** HIGH (HTML table heatmap is reliable and simple)

3. **How to handle pairs that didn't exist for the entire backtest period**
   - What we know: Some pairs may have been listed after the backtest start date. Historical data would start partway through.
   - What's unclear: Should the engine skip pairs without full coverage, or start trading them when data becomes available?
   - Recommendation: For single-pair backtests, validate that sufficient data exists for the requested date range and return an error if not. The engine should report the actual data coverage in the result.
   - **Confidence:** HIGH

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/bot/execution/executor.py` -- Executor ABC that BacktestExecutor must implement
- Existing codebase: `src/bot/execution/paper_executor.py` -- Reference implementation for simulated fills
- Existing codebase: `src/bot/pnl/fee_calculator.py` -- FeeCalculator interface to reuse (BKTS-02)
- Existing codebase: `src/bot/pnl/tracker.py` -- PnLTracker interface to reuse (BKTS-02)
- Existing codebase: `src/bot/position/manager.py` -- PositionManager to reuse with BacktestExecutor
- Existing codebase: `src/bot/signals/engine.py` -- SignalEngine for composite strategy backtesting
- Existing codebase: `src/bot/market_data/opportunity_ranker.py` -- OpportunityRanker for simple strategy backtesting
- Existing codebase: `src/bot/data/store.py` -- HistoricalDataStore for data replay
- Existing codebase: `src/bot/data/models.py` -- HistoricalFundingRate, OHLCVCandle models
- Existing codebase: `src/bot/config.py` -- Settings patterns, SignalSettings (sweepable parameters)
- Existing codebase: `src/bot/analytics/metrics.py` -- Sharpe, drawdown, win_rate for backtest results
- Existing codebase: `src/bot/dashboard/app.py` -- Dashboard app factory pattern
- Existing codebase: `src/bot/dashboard/templates/base.html` -- Tailwind + HTMX + CDN pattern
- Existing codebase: `src/bot/orchestrator.py` -- Strategy branching logic (simple vs composite)
- Existing codebase: `src/bot/models.py` -- FundingRateData, OpportunityScore, Position, OrderResult

### Secondary (MEDIUM confidence)
- Chart.js official docs: Line chart and configuration options for equity curve display
- Python `itertools.product` docs: Parameter grid generation

### Tertiary (LOW confidence)
- Optimal default parameter sweep ranges: Need empirical data to determine useful sweep bounds

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new Python libraries; Chart.js via CDN is standard for web dashboards
- Architecture: HIGH -- BacktestExecutor pattern is a direct application of the existing Executor ABC; all reuse points are well-understood from code review
- Data replay: HIGH -- HistoricalDataStore already provides all needed query methods with time range filtering
- Look-ahead prevention: HIGH -- BacktestDataStoreWrapper is a straightforward proxy pattern
- Dashboard integration: HIGH -- follows established Jinja2 + HTMX + Tailwind patterns
- Pitfalls: HIGH -- identified from careful code review (time.time() injection, markets dict, data store bounding, memory growth)
- Parameter sweep: MEDIUM -- design is straightforward but optimal sweep ranges are empirical

**Research date:** 2026-02-12
**Valid until:** 2026-03-12 (30 days -- codebase is stable, no external dependency changes expected)
