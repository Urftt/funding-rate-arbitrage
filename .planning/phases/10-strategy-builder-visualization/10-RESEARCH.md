# Phase 10: Strategy Builder & Visualization - Research

**Researched:** 2026-02-13
**Domain:** Multi-pair backtest orchestration, strategy presets, funding rate distribution visualization, CoinGecko market cap integration, Chart.js boxplot plugin
**Confidence:** HIGH

## Summary

Phase 10 builds three connected capabilities on top of the existing backtest engine (Phase 6), pair analysis service (Phase 8), and trade-level backtest output (Phase 9). The first capability is multi-pair backtest execution: the user selects multiple pairs from the tracked pair list, configures a single set of backtest parameters, and runs the same backtest across all selected pairs simultaneously, seeing results in a unified comparison table with an aggregate "X of Y pairs profitable" summary. The second capability is strategy presets (conservative, balanced, aggressive) that pre-fill the backtest form parameters, reducing the parameter-tuning burden for new users. The third capability is statistical visualization: a funding rate distribution histogram for individual pairs (server-side binning via `PairAnalyzer`), cross-pair comparison box plots using the `@sgratzl/chartjs-chart-boxplot` CDN plugin, and market cap tier filtering using the CoinGecko free API.

The multi-pair backtest reuses the existing `run_backtest()` function from `backtest/runner.py` in a sequential loop -- one `BacktestEngine` instantiation per pair, sharing the same `BacktestConfig` (overriding only the `symbol` field). This is the same pattern used by `ParameterSweep` for running multiple configurations. Memory management follows the existing sweep pattern: retain full results (equity curve, trades) for the best-performing pair, compact the rest to metrics-only. A new API endpoint `/api/backtest/multi` accepts a list of symbols and base configuration, runs all backtests as a background task, and returns results through the existing polling mechanism (`/api/backtest/status/{task_id}`).

The CoinGecko integration is the one external API dependency allowed by the v1.2 constraints. It fetches market cap data for the tracked pairs via the free `/coins/markets` endpoint (base URL: `https://api.coingecko.com/api/v3/`, rate limit: 5-30 calls/min, no API key required for basic use). The main challenge is mapping the project's ccxt-format symbols (e.g., `BTC/USDT:USDT`) to CoinGecko coin IDs (e.g., `bitcoin`). This requires a static or fetched mapping table. Market cap tiers are defined as: mega (>$50B), large ($10B-$50B), mid ($1B-$10B), small (<$1B).

**Primary recommendation:** Build the multi-pair backtest as a new async task pattern in `api.py` (reusing `run_backtest()` in a loop), add strategy preset definitions as a static Python dict in `backtest/models.py`, extend `PairAnalyzer` with a `get_rate_distribution()` method for histogram data, add a CoinGecko market cap service under `src/bot/data/market_cap.py` using `urllib.request` (stdlib, no new dependency), and include the `@sgratzl/chartjs-chart-boxplot` CDN for cross-pair box plots.

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | >=0.115 | New API endpoints for multi-pair backtest and market cap data | Already the dashboard framework |
| Chart.js | @4 (CDN) | Funding rate distribution histograms, extended equity curves | Already loaded on `/backtest` and `/pairs` pages |
| Jinja2 | >=3.1 | Template rendering for new UI sections | Already used for all pages |
| Tailwind CSS | CDN | Styling for comparison tables, preset buttons, filter UI | Already used everywhere |
| aiosqlite | >=0.22 | Read historical funding rates for distribution computation | Already used by `HistoricalDataStore` |
| Decimal (stdlib) | N/A | All monetary/rate arithmetic | Project-wide convention |
| BacktestEngine | N/A | Core backtest execution per pair | Built in Phase 6, proven |
| PairAnalyzer | N/A | Per-pair statistics and ranking | Built in Phase 8 |

### New Additions (within budget)
| Library | Version | Purpose | Budget |
|---------|---------|---------|--------|
| `@sgratzl/chartjs-chart-boxplot` | @4.4.5 (CDN) | Box plot chart type for cross-pair rate distribution comparison | Roadmap allows "one CDN addition (boxplot plugin)" |
| CoinGecko free API | v3 | Market cap data for tier filtering | Roadmap allows "one external API (CoinGecko free tier)" |

### Supporting (no new Python additions)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `urllib.request` (stdlib) | N/A | HTTP GET to CoinGecko API | Market cap data fetching -- avoids adding `requests` or `httpx` as new dependency |
| `json` (stdlib) | N/A | Parse CoinGecko JSON responses | Paired with urllib |
| structlog | >=25.5 | Structured logging | Already project standard |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `urllib.request` for CoinGecko | `httpx` or `aiohttp` | Would be a new Python dependency; roadmap says "zero new Python dependencies"; stdlib `urllib.request` is sufficient for a single synchronous API call on startup/refresh |
| `@sgratzl/chartjs-chart-boxplot` | Manual box plot with Chart.js bar chart + error bars | Would avoid CDN but box plot rendering is non-trivial (whiskers, outliers, quartile computation); the plugin handles all of this and the CDN budget explicitly allows it |
| Sequential multi-pair backtest | Parallel `asyncio.gather()` | Sequential is simpler and consistent with `ParameterSweep`. Each backtest opens/closes its own DB connection. Parallelism would add complexity for marginal time savings on ~20 pairs |
| Static symbol-to-CoinGecko mapping | Dynamic CoinGecko `/coins/list` endpoint | Static mapping is simpler, works offline, and covers the ~20 tracked pairs. Dynamic requires an extra API call and parsing ~13,000 coins |

**Installation:** Add one CDN script tag for boxplot plugin. No new Python packages.

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/@sgratzl/chartjs-chart-boxplot"></script>
```

## Architecture Patterns

### Recommended Project Structure
```
src/bot/
  backtest/
    models.py                    # MODIFY: add StrategyPreset, MultiPairResult models
    runner.py                    # MODIFY: add run_multi_pair() function
  analytics/
    pair_analyzer.py             # MODIFY: add get_rate_distribution() method
  data/
    market_cap.py                # NEW: CoinGecko market cap service (~80 lines)
  dashboard/
    routes/
      api.py                     # MODIFY: add /api/backtest/multi, /api/market-cap endpoints
      pages.py                   # MODIFY: pass market cap data and presets to backtest page
    templates/
      backtest.html              # MODIFY: add multi-pair UI, preset buttons, comparison table
      pairs.html                 # MODIFY: add histogram section, box plot section, market cap filter
      partials/
        strategy_presets.html    # NEW: preset button panel partial
        multi_pair_results.html  # NEW: comparison table and aggregate summary partial
        rate_distribution.html   # NEW: funding rate histogram partial (for pairs page)
        rate_boxplot.html        # NEW: cross-pair box plot partial
```

### Pattern 1: Multi-Pair Backtest via Sequential run_backtest() Loop
**What:** Reuse the existing `run_backtest()` function from `backtest/runner.py` in a loop over selected symbols. Each iteration creates a new `BacktestEngine` with the same config but a different symbol. Results are collected into a `MultiPairResult` dataclass. Follows the exact same pattern as `ParameterSweep.run()` which loops over config combinations.
**When to use:** The multi-pair backtest API endpoint.
**Example:**
```python
# Source: Pattern derived from src/bot/backtest/sweep.py ParameterSweep.run()

@dataclass
class MultiPairResult:
    """Results from running the same config across multiple pairs."""
    symbols: list[str]
    base_config: BacktestConfig
    results: list[tuple[str, BacktestResult]]  # (symbol, result) pairs

    @property
    def profitable_count(self) -> int:
        return sum(1 for _, r in self.results if r.metrics.net_pnl > Decimal("0"))

    @property
    def total_count(self) -> int:
        return len(self.results)

async def run_multi_pair(
    symbols: list[str],
    base_config: BacktestConfig,
    db_path: str = "data/historical.db",
) -> MultiPairResult:
    """Run the same backtest config across multiple pairs sequentially."""
    results = []
    for symbol in symbols:
        config = base_config.with_overrides(symbol=symbol)
        result = await run_backtest(config, db_path)
        # Memory management: only keep full data for best result
        results.append((symbol, result))
    return MultiPairResult(symbols=symbols, base_config=base_config, results=results)
```

### Pattern 2: Strategy Presets as Static Configuration
**What:** Define preset parameter sets as a Python dict mapping preset names to parameter overrides. The UI sends a preset name, the backend resolves it to concrete values, and pre-fills the form. No database storage needed -- presets are static.
**When to use:** Strategy preset selection.
**Example:**
```python
# Source: Project convention -- static configuration constants

STRATEGY_PRESETS = {
    "conservative": {
        "strategy_mode": "simple",
        "min_funding_rate": Decimal("0.0005"),
        "exit_funding_rate": Decimal("0.0002"),
    },
    "balanced": {
        "strategy_mode": "composite",
        "entry_threshold": Decimal("0.35"),
        "exit_threshold": Decimal("0.2"),
        "weight_rate_level": Decimal("0.35"),
        "weight_trend": Decimal("0.25"),
        "weight_persistence": Decimal("0.25"),
        "weight_basis": Decimal("0.15"),
    },
    "aggressive": {
        "strategy_mode": "composite",
        "entry_threshold": Decimal("0.25"),
        "exit_threshold": Decimal("0.15"),
        "weight_rate_level": Decimal("0.40"),
        "weight_trend": Decimal("0.20"),
        "weight_persistence": Decimal("0.25"),
        "weight_basis": Decimal("0.15"),
    },
}
```

### Pattern 3: Funding Rate Distribution via PairAnalyzer Extension
**What:** Add a `get_rate_distribution()` method to the existing `PairAnalyzer` that returns raw funding rate values for a pair (or multiple pairs). This feeds both the funding rate histogram on the pairs page (server-side binning) and the box plot chart (raw arrays sent to the client for the boxplot plugin to compute quartiles).
**When to use:** Rate distribution histogram (EXPR-04) and box plots (EXPR-07).
**Example:**
```python
# Source: Extension of src/bot/analytics/pair_analyzer.py

async def get_rate_distribution(
    self,
    symbol: str,
    since_ms: int | None = None,
    until_ms: int | None = None,
) -> dict:
    """Get funding rate distribution data for histogram rendering."""
    rates = await self._store.get_funding_rates(symbol, since_ms, until_ms)
    values = [r.funding_rate for r in rates]
    if not values:
        return {"bins": [], "counts": [], "raw_rates": []}

    # Server-side histogram binning (same pattern as compute_pnl_histogram)
    min_val, max_val = min(values), max(values)
    bin_count = min(20, max(5, len(values) // 20))
    # ... binning logic ...

    return {
        "bins": bins,
        "counts": counts,
        "raw_rates": [str(v) for v in values],  # For box plot
    }
```

### Pattern 4: CoinGecko Market Cap Service with Symbol Mapping
**What:** A lightweight service that maps the project's ccxt-format symbols to CoinGecko coin IDs, fetches market cap data via the free API, and classifies pairs into market cap tiers. Uses `urllib.request` (stdlib) to avoid adding a new Python dependency. Results are cached in memory with a TTL (e.g., 1 hour) since market cap tiers change slowly.
**When to use:** Market cap tier filtering (EXPR-08) and historical performance summary (EXPR-09).
**Example:**
```python
# Source: New module, follows project convention of stateless service classes

import json
import time
import urllib.request

# Static mapping for common tracked pairs
SYMBOL_TO_COINGECKO = {
    "BTC/USDT:USDT": "bitcoin",
    "ETH/USDT:USDT": "ethereum",
    "SOL/USDT:USDT": "solana",
    "DOGE/USDT:USDT": "dogecoin",
    "XRP/USDT:USDT": "ripple",
    # ... extend for all top 20 tracked pairs
}

MARKET_CAP_TIERS = {
    "mega": Decimal("50000000000"),    # > $50B
    "large": Decimal("10000000000"),   # $10B - $50B
    "mid": Decimal("1000000000"),      # $1B - $10B
    "small": Decimal("0"),             # < $1B
}

class MarketCapService:
    def __init__(self, cache_ttl_seconds: int = 3600):
        self._cache: dict[str, dict] = {}
        self._cache_time: float = 0
        self._ttl = cache_ttl_seconds

    def _fetch_market_caps(self, coin_ids: list[str]) -> dict[str, Decimal]:
        """Fetch market caps from CoinGecko free API using stdlib."""
        ids_param = ",".join(coin_ids)
        url = (
            f"https://api.coingecko.com/api/v3/coins/markets"
            f"?vs_currency=usd&ids={ids_param}&per_page=250"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {
            item["id"]: Decimal(str(item["market_cap"] or 0))
            for item in data
        }
```

### Pattern 5: Box Plot with CDN Plugin
**What:** Include the `@sgratzl/chartjs-chart-boxplot` CDN script after Chart.js. Create a chart with `type: 'boxplot'` where each dataset data entry is an array of raw numbers (the plugin auto-computes quartiles, median, whiskers). Each label is a pair symbol, each data entry is that pair's funding rate values as a number array.
**When to use:** Cross-pair rate distribution comparison (EXPR-07).
**Example:**
```javascript
// Source: @sgratzl/chartjs-chart-boxplot documentation
// CDN: https://cdn.jsdelivr.net/npm/@sgratzl/chartjs-chart-boxplot

new Chart(ctx, {
    type: 'boxplot',
    data: {
        labels: ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
        datasets: [{
            label: 'Funding Rate Distribution',
            data: [
                [0.0001, 0.0003, 0.0005, 0.0002, ...],  // BTC rates
                [0.0002, 0.0004, 0.0001, 0.0003, ...],  // ETH rates
                [0.0003, 0.0006, 0.0008, 0.0001, ...],  // SOL rates
            ],
            backgroundColor: 'rgba(59, 130, 246, 0.5)',
            borderColor: '#3b82f6',
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { labels: { color: '#9ca3af' } }
        },
        scales: {
            x: { ticks: { color: '#6b7280' }, grid: { color: '#334155' } },
            y: {
                ticks: {
                    color: '#6b7280',
                    callback: function(v) { return (v * 100).toFixed(4) + '%'; }
                },
                grid: { color: '#334155' },
                title: { display: true, text: 'Funding Rate', color: '#9ca3af' }
            }
        }
    }
});
```

### Pattern 6: Background Task with Multi-Pair Results
**What:** Follow the exact same background task pattern used by `_run_backtest_task()`, `_run_sweep_task()`, and `_run_comparison_task()` in `api.py`. Create a new `_run_multi_pair_task()` that runs the multi-pair backtest and stores results in `app.state.backtest_tasks[task_id]`.
**When to use:** The multi-pair backtest API endpoint.

### Anti-Patterns to Avoid
- **Running multi-pair backtests in parallel with `asyncio.gather()`:** While tempting for speed, this creates multiple concurrent `HistoricalDatabase` connections and increases memory usage proportionally. The sequential approach is proven in `ParameterSweep` and safer. Each backtest takes ~1-5 seconds, so 20 pairs takes ~20-100 seconds -- acceptable for a background task.
- **Using `requests` or `httpx` for CoinGecko:** This would violate the "zero new Python dependencies" constraint. `urllib.request` from stdlib is sufficient for a simple GET request.
- **Storing CoinGecko data in SQLite:** Market cap data changes frequently and is only used for UI filtering. An in-memory cache with TTL is simpler and sufficient. No schema changes needed.
- **Building a custom box plot renderer:** The boxplot CDN plugin handles quartile computation, whisker calculation, outlier detection, and rendering. The CDN budget explicitly allows this one addition.
- **Making presets configurable via database:** Presets are a UX convenience feature with 3 fixed options. A static Python dict is the right approach -- no database, no configuration complexity.
- **Sending all funding rate records to the frontend for histogram binning:** Server-side binning is the project pattern (see `compute_pnl_histogram` in `backtest/models.py`). However, for box plots, the plugin needs raw arrays -- send the raw rates for the selected comparison pairs only (not all pairs at once).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Box plot quartile/whisker computation | Manual Q1/Q3/IQR/whisker math | `@sgratzl/chartjs-chart-boxplot` plugin | The plugin auto-computes all statistics from raw number arrays; hand-rolling misses edge cases (outliers, empty data, single values) |
| Multi-pair backtest execution | New backtest executor class | `run_backtest()` in a loop (pattern from `ParameterSweep`) | The existing function handles all database lifecycle, engine creation, and error handling |
| Funding rate histogram binning | Client-side JS binning | Server-side Decimal binning (pattern from `compute_pnl_histogram`) | Project convention: all statistics server-side in Python with Decimal precision |
| Market cap data fetching | `requests`/`httpx` library | `urllib.request` (stdlib) | Zero new dependency constraint; simple GET request doesn't need a full HTTP client |
| Symbol-to-CoinGecko ID mapping | Real-time API lookup for each symbol | Static mapping dict + fallback parser | The project tracks ~20 pairs; a static map covers them all. Parsing `BTC` from `BTC/USDT:USDT` provides a reasonable fallback |
| Strategy preset storage | Database table or config file | Static Python dict constant | Three fixed presets don't warrant persistence infrastructure |
| Decimal-to-JSON serialization | Custom serializer | Reuse `_decimal_to_str()` and `to_dict()` pattern | Already handles all edge cases across the codebase |
| Comparison table rendering | React/Vue component | Vanilla JS innerHTML (pattern from `backtest.html`) | Consistent with all existing dashboard patterns |

**Key insight:** Phase 10 is primarily an orchestration and UI integration phase. The core computation (backtest execution, pair statistics, fee-adjusted yield) is already implemented. The work is: (1) running existing code over multiple pairs and collecting results, (2) adding preset configurations, (3) extending existing analytics with distribution data, (4) adding one CDN plugin for box plots, and (5) making one external API call for market cap data.

## Common Pitfalls

### Pitfall 1: Multi-Pair Backtest Memory Growth
**What goes wrong:** Running 20 backtests sequentially accumulates 20 full `BacktestResult` objects in memory, each with equity curves (thousands of points), trade lists, and trade stats. For 20 pairs with 1,000 equity points each, this is ~20,000 objects plus trades.
**Why it happens:** Unlike `ParameterSweep` which discards non-best equity curves, a multi-pair comparison needs to show metrics for ALL pairs.
**How to avoid:** Follow the sweep memory management pattern: only retain the full equity curve and trades list for the best-performing pair. For all other pairs, keep only the compact `BacktestMetrics` and `TradeStats`. The comparison table only shows aggregate metrics (net P&L, Sharpe, win rate), not individual equity curves.
**Warning signs:** Memory spikes when running multi-pair backtests with 15+ pairs.

### Pitfall 2: CoinGecko Symbol-to-ID Mapping Failures
**What goes wrong:** The project uses ccxt-format symbols (`BTC/USDT:USDT`) but CoinGecko uses lowercase slug IDs (`bitcoin`). Mapping fails for less common pairs.
**Why it happens:** CoinGecko IDs are not derivable from ticker symbols -- `DOGE` maps to `dogecoin`, not `doge`. Some pairs may not exist on CoinGecko at all.
**How to avoid:** Use a static mapping dict for the common top-20 pairs. For unmapped pairs, try a fallback: extract the base symbol (e.g., `BTC` from `BTC/USDT:USDT`), convert to lowercase, and try the CoinGecko `/coins/list` endpoint. If that fails, assign the pair to "unknown" tier and exclude from market cap filtering.
**Warning signs:** Pairs showing "Unknown" market cap tier in the UI.

### Pitfall 3: CoinGecko Rate Limiting
**What goes wrong:** Fetching market cap data for 20 pairs at page load, combined with multiple users or page refreshes, exceeds CoinGecko's free tier rate limit (5-30 calls/min).
**Why it happens:** No caching of CoinGecko responses. Each page load triggers a new API call.
**How to avoid:** Cache CoinGecko responses in memory with a 1-hour TTL. Market cap tiers change on the order of weeks, not minutes. Fetch all needed coins in a single API call (the `/coins/markets` endpoint accepts a comma-separated `ids` parameter for batch requests). Never call CoinGecko on every page load -- only refresh the cache if the TTL has expired.
**Warning signs:** 429 (Too Many Requests) errors from CoinGecko in logs.

### Pitfall 4: Box Plot Plugin Not Registering with Chart.js
**What goes wrong:** The box plot chart type throws "boxplot is not a registered chart type" error.
**Why it happens:** The boxplot plugin CDN script must load AFTER Chart.js. If Chart.js is loaded in `{% block head %}` and the boxplot plugin is loaded later, timing may be correct. But if both are in the same block without proper ordering, or if Chart.js uses a module-style import, the plugin may not auto-register.
**How to avoid:** Load both scripts in the `{% block head %}` section in the correct order: Chart.js first, then the boxplot plugin. Verify with `console.log(Chart.defaults)` that the `boxplot` type exists before creating charts. The existing pattern loads Chart.js via CDN in `{% block head %}` which works for global registration.
**Warning signs:** JavaScript console error about unknown chart type.

### Pitfall 5: Backtest Form Complexity with Preset + Multi-Pair + Existing Modes
**What goes wrong:** The backtest form already has 3 run modes (single, compare, sweep), strategy mode toggle, and advanced parameters. Adding preset buttons and multi-pair checkboxes makes the form overwhelming.
**Why it happens:** Feature accumulation without UX simplification.
**How to avoid:** Use a progressive disclosure approach: (1) preset buttons at the top that auto-fill parameters and collapse the advanced section, (2) pair selection checkboxes appear only when "Multi-Pair" run mode is selected, (3) the existing single/compare/sweep modes remain as-is. Consider making the multi-pair mode a fourth radio option in the existing "Run Mode" group.
**Warning signs:** Users confused by too many form options, or form extending beyond one screen height.

### Pitfall 6: Histogram Bin Scaling for Rate Distributions vs P&L Distributions
**What goes wrong:** Reusing the exact `compute_pnl_histogram()` logic for funding rate distributions produces bins with labels like `$0.0001` which are confusing (rates are not dollar amounts) or bins that are too wide/narrow.
**Why it happens:** Funding rates are very small numbers (typically 0.0001 to 0.001). Dollar P&L values are much larger (typically -$10 to +$50). The bin width and label formatting need different treatment.
**How to avoid:** Create a separate `compute_rate_histogram()` function (or parameterize the existing one) that: (1) uses percentage-formatted labels (e.g., "0.0100%"), (2) uses an appropriate bin count for the typical ~1,000 rate records (more bins than the ~10-trade P&L histogram), and (3) handles the near-zero-centered distribution of funding rates.
**Warning signs:** Histogram showing all rates in a single bin, or bins with confusing dollar-sign labels.

### Pitfall 7: Multi-Pair Backtest with Pairs Lacking OHLCV Data
**What goes wrong:** Some tracked pairs may have funding rate history but no OHLCV candle data (or vice versa). The `BacktestEngine` returns an empty result if either dataset is missing. In a multi-pair run, one failing pair should not block the others.
**Why it happens:** Data fetching may have partially succeeded for some pairs. The `BacktestEngine` handles this gracefully by returning `_empty_result()`, but the multi-pair runner needs to include these "no data" results in the comparison table rather than crashing.
**How to avoid:** In the multi-pair loop, catch exceptions per-pair and record the error. Return a `MultiPairResult` that includes both successful results and error entries. The comparison table should show "No data" for pairs that failed.
**Warning signs:** Multi-pair backtest reporting fewer results than selected pairs.

## Code Examples

Verified patterns from the existing codebase:

### Existing Background Task Pattern (to extend for multi-pair)
```python
# Source: src/bot/dashboard/routes/api.py lines 276-294
async def _run_backtest_task(
    task_id: str, app_state: Any, config: BacktestConfig, db_path: str
) -> None:
    try:
        result = await run_backtest(config, db_path)
        app_state.backtest_tasks[task_id]["result"] = result.to_dict()
        app_state.backtest_tasks[task_id]["status"] = "complete"
    except Exception as e:
        log.error("backtest_task_error", task_id=task_id, error=str(e))
        app_state.backtest_tasks[task_id]["result"] = {"error": str(e)}
        app_state.backtest_tasks[task_id]["status"] = "error"
```

### Existing Config Override Pattern (used for per-pair symbol swap)
```python
# Source: src/bot/backtest/models.py lines 64-73
def with_overrides(self, **kwargs: object) -> "BacktestConfig":
    """Return a new BacktestConfig with specified fields overridden."""
    return replace(self, **kwargs)

# Usage in multi-pair: config.with_overrides(symbol="ETH/USDT:USDT")
```

### Existing Sweep Memory Management (pattern for multi-pair)
```python
# Source: src/bot/backtest/sweep.py lines 126-157
# Only the best result retains full equity curve and trades
if result.metrics.net_pnl > best_pnl:
    if best_index >= 0:
        prev = results[best_index][1]
        results[best_index] = (
            results[best_index][0],
            BacktestResult(
                config=prev.config,
                equity_curve=[],
                trades=[],
                trade_stats=prev.trade_stats,
                metrics=prev.metrics,
            ),
        )
    best_pnl = result.metrics.net_pnl
    best_index = len(results)
    results.append((params, result))
```

### Existing Form Data Collection (pattern for preset pre-fill)
```javascript
// Source: src/bot/dashboard/templates/backtest.html lines 99-125
function getFormData() {
    const data = {
        symbol: document.getElementById('bt-symbol').value,
        start_date: document.getElementById('bt-start-date').value,
        end_date: document.getElementById('bt-end-date').value,
        strategy_mode: document.getElementById('bt-strategy').value,
    };
    // ... collect optional overrides
    return data;
}
// Preset pre-fill would set input values before getFormData() collects them
```

### Existing PairAnalyzer Data Access (pattern for rate distribution)
```python
# Source: src/bot/analytics/pair_analyzer.py lines 230-269
async def get_pair_stats(
    self, symbol: str, since_ms: int | None = None, until_ms: int | None = None,
) -> PairDetail:
    rates = await self._store.get_funding_rates(symbol, since_ms, until_ms)
    stats = _compute_stats(symbol, rates, self._fee_settings)
    time_series = [
        {"timestamp_ms": r.timestamp_ms, "funding_rate": str(r.funding_rate), ...}
        for r in rates
    ]
    return PairDetail(symbol=symbol, stats=stats, time_series=time_series)
```

### Existing Metric Card HTML (pattern for comparison table)
```javascript
// Source: src/bot/dashboard/templates/backtest.html lines 183-188
function metricCard(label, value, colorClass) {
    return '<div class="bg-dash-card rounded-lg border border-dash-border p-3">' +
           '<p class="text-xs text-gray-400 mb-1">' + label + '</p>' +
           '<p class="text-lg font-semibold ' + (colorClass || 'text-white') + '">' + value + '</p>' +
           '</div>';
}
```

### Existing Pair Ranking API (pattern for market cap enrichment)
```python
# Source: src/bot/dashboard/routes/api.py lines 196-214
@router.get("/pairs/ranking")
async def get_pair_ranking(request: Request, range: str = "all") -> JSONResponse:
    pair_analyzer = getattr(request.app.state, "pair_analyzer", None)
    if pair_analyzer is None:
        return JSONResponse(content={"error": "Pair analysis not available"}, status_code=501)
    since_ms = _range_to_since_ms(range)
    ranking = await pair_analyzer.get_pair_ranking(since_ms=since_ms)
    return JSONResponse(content=[s.to_dict() for s in ranking])
```

### Existing Run Mode Radio Buttons (pattern for multi-pair mode)
```html
<!-- Source: src/bot/dashboard/templates/partials/backtest_form.html lines 50-68 -->
<div class="flex items-center gap-6">
    <label class="flex items-center gap-2 text-sm text-gray-200 cursor-pointer">
        <input type="radio" name="run_mode" value="single" checked ...>
        Single Backtest
    </label>
    <label class="flex items-center gap-2 text-sm text-gray-200 cursor-pointer">
        <input type="radio" name="run_mode" value="compare" ...>
        Compare v1.0 vs v1.1
    </label>
    <!-- Add "multi" option here -->
</div>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-pair backtest only | Parameter sweep across configs (Phase 6) | v1.1 (2026-02-12) | `ParameterSweep` proves the loop-over-configs pattern; multi-pair is loop-over-symbols |
| No pair statistics | `PairAnalyzer` with per-pair stats (Phase 8) | v1.2 (2026-02-13) | Statistics engine exists; just need to extend with distribution data |
| No trade-level detail | `BacktestTrade` and `TradeStats` models (Phase 9) | v1.2 (2026-02-13) | Full per-trade data available for comparison table metrics |
| No external API integration | None yet | Current | CoinGecko will be the first external data source beyond Bybit |
| Chart.js bar/line only | Bar, line, scatter charts (Phases 6, 9) | v1.2 (2026-02-13) | Box plot is the first new chart type requiring a CDN plugin |

**No deprecated patterns apply.** The project stack (FastAPI, Chart.js 4, Tailwind CDN, aiosqlite, dataclasses) is current and stable.

## Open Questions

1. **CoinGecko API key requirement**
   - What we know: The CoinGecko free/demo tier appears to work without an API key for basic use (5-15 calls/min). However, CoinGecko has been tightening access and now offers a "Demo" API key for better rate limits (30 calls/min, 10K calls/month).
   - What's unclear: Whether the keyless public endpoint will reliably work, or if a demo API key is now required. The documentation is ambiguous.
   - Recommendation: Code the service to work without a key by default, but support an optional `COINGECKO_API_KEY` environment variable. If the key is set, include it as the `x_cg_demo_api_key` query parameter. This future-proofs the integration without requiring users to register.

2. **Market cap tier boundaries**
   - What we know: The success criteria says "mega, large, mid, small" tiers. No specific dollar boundaries are defined.
   - What's unclear: What the exact tier boundaries should be.
   - Recommendation: Use industry-standard cryptocurrency market cap tiers: mega (>$50B -- BTC, ETH), large ($10B-$50B -- SOL, XRP, BNB, etc.), mid ($1B-$10B), small (<$1B). These are well-established in the crypto industry.

3. **Where should multi-pair selection UI live?**
   - What we know: The existing backtest page has a single symbol dropdown. Multi-pair requires selecting multiple symbols.
   - What's unclear: Whether to use a multi-select dropdown, checkboxes, or a "Select All" approach.
   - Recommendation: Add a new "Multi-Pair" radio option in the Run Mode group. When selected, show a panel of checkboxes (one per tracked pair) with a "Select All" / "Deselect All" toggle. This is progressive disclosure -- the checkboxes only appear when the multi-pair mode is active.

4. **Strategy presets: are they for backtest form only, or also the main dashboard?**
   - What we know: The requirement says "pre-fill backtest parameters." The presets are tied to the backtest workflow.
   - What's unclear: Whether presets should also affect the main dashboard's live trading parameters.
   - Recommendation: Presets apply ONLY to the backtest form. They pre-fill parameters for backtesting/experimentation. Applying them to live trading would violate the "read-only" constraint of v1.2. The preset buttons sit above the advanced parameters section on the backtest page.

5. **Performance summary card content (EXPR-09)**
   - What we know: Success criteria says "see a historical performance summary card ('X pairs averaged Y% yield after fees')."
   - What's unclear: What other metrics should be in the summary card beyond the aggregate yield.
   - Recommendation: The performance summary card should show: (1) number of pairs in the selected tier, (2) average annualized yield after fees across those pairs, (3) median yield, (4) range (best to worst). This directly reuses `PairAnalyzer.get_pair_ranking()` data filtered by market cap tier.

6. **Box plot data volume**
   - What we know: Each tracked pair has ~1,000+ funding rate records. Sending raw arrays for 20 pairs to the frontend means ~20,000 numbers in the JSON response.
   - What's unclear: Whether this volume is acceptable for the box plot chart, or if we should subsample.
   - Recommendation: 20,000 floating-point numbers is approximately 200KB of JSON, which is acceptable for a single-page chart. The boxplot plugin handles large arrays efficiently (it just computes quartiles). No subsampling needed. However, only send data for pairs the user has selected for comparison (likely 3-10 pairs at a time), not all 20.

## Sources

### Primary (HIGH confidence)
- **Codebase analysis** -- All patterns and code examples from direct reading of project source:
  - `src/bot/backtest/engine.py` -- BacktestEngine for per-pair execution
  - `src/bot/backtest/models.py` -- BacktestConfig, BacktestResult, ParameterSweep models, compute_pnl_histogram
  - `src/bot/backtest/runner.py` -- run_backtest() entry point, run_comparison() pattern
  - `src/bot/backtest/sweep.py` -- ParameterSweep sequential loop and memory management pattern
  - `src/bot/analytics/pair_analyzer.py` -- PairAnalyzer service class, PairStats, PairDetail
  - `src/bot/data/store.py` -- HistoricalDataStore.get_funding_rates(), get_tracked_pairs()
  - `src/bot/data/models.py` -- HistoricalFundingRate, OHLCVCandle
  - `src/bot/data/database.py` -- Schema definition (funding_rate_history, tracked_pairs tables)
  - `src/bot/config.py` -- BacktestConfig fields, strategy parameters, FeeSettings
  - `src/bot/dashboard/routes/api.py` -- Background task pattern, polling pattern, _build_config_from_body()
  - `src/bot/dashboard/routes/pages.py` -- Page route patterns, backtest page tracked_pairs
  - `src/bot/dashboard/app.py` -- App factory, template setup, app.state wiring
  - `src/bot/dashboard/templates/backtest.html` -- Full backtest page JS with all display functions
  - `src/bot/dashboard/templates/pairs.html` -- Pair explorer page JS with ranking and detail
  - `src/bot/dashboard/templates/base.html` -- CDN loading, nav bar, page structure
  - `src/bot/dashboard/templates/partials/backtest_form.html` -- Form with run mode radios, advanced params
  - `src/bot/dashboard/templates/partials/equity_curve.html` -- Chart.js rendering pattern
  - `src/bot/dashboard/templates/partials/pnl_histogram.html` -- Bar chart histogram pattern
  - `src/bot/main.py` -- Service wiring, lifespan, PairAnalyzer instantiation
  - `tests/test_backtest_trades.py` -- Test patterns for TDD with dataclass models

### Secondary (MEDIUM confidence)
- [@sgratzl/chartjs-chart-boxplot GitHub](https://github.com/sgratzl/chartjs-chart-boxplot) -- Version 4.4.5, CDN via jsDelivr, data format (raw number arrays), Chart.js compatibility
- [@sgratzl/chartjs-chart-boxplot examples](https://www.sgratzl.com/chartjs-chart-boxplot/examples/) -- Usage example with `type: 'boxplot'`, random values demo, script tag ordering
- [jsDelivr CDN for @sgratzl/chartjs-chart-boxplot](https://www.jsdelivr.com/package/npm/@sgratzl/chartjs-chart-boxplot) -- CDN URL: `https://cdn.jsdelivr.net/npm/@sgratzl/chartjs-chart-boxplot`
- [CoinGecko API docs -- /coins/markets](https://docs.coingecko.com/reference/coins-markets) -- Query params (vs_currency, ids, per_page), response fields (market_cap, market_cap_rank)
- [CoinGecko API setup](https://docs.coingecko.com/docs/setting-up-your-api-key) -- Base URL `https://api.coingecko.com/api/v3/`, demo API key parameter `x_cg_demo_api_key`
- [CoinGecko rate limits](https://support.coingecko.com/hc/en-us/articles/4538771776153-What-is-the-rate-limit-for-CoinGecko-API-public-plan) -- Free tier 5-30 calls/min, demo 30 calls/min with 10K calls/month cap

### Tertiary (LOW confidence)
- CoinGecko API keyless access stability -- Based on web search results and documentation, but CoinGecko has been tightening access over time. The keyless endpoint may require a demo key in the future. Flagged for validation during implementation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Everything except the boxplot CDN and CoinGecko API is already in the project. The two additions are explicitly budgeted in the roadmap constraints.
- Architecture: HIGH -- All patterns directly derived from existing codebase code. Multi-pair backtest is a direct extension of the ParameterSweep loop pattern. Strategy presets are static config. Distribution data extends PairAnalyzer.
- Pitfalls: HIGH -- Pitfalls identified from direct analysis of memory management patterns (sweep), CoinGecko API documentation, Chart.js plugin registration requirements, and existing UI complexity.
- CoinGecko integration: MEDIUM -- API documentation confirms endpoint behavior, but rate limiting and keyless access stability are based on web search results that may not reflect the latest policy changes.
- Boxplot plugin: MEDIUM -- CDN URL and data format confirmed via GitHub README and examples site, but not tested in this specific codebase context. The `type: 'boxplot'` registration with CDN-loaded Chart.js needs validation.

**Research date:** 2026-02-13
**Valid until:** 2026-03-15 (stable for codebase patterns; CoinGecko API terms may change sooner)
