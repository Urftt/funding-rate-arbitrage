# Technology Stack: v1.2 Pair Explorer & Enhanced Visualization

**Project:** Funding Rate Arbitrage -- pair profitability analysis, statistical distributions, market cap filtering, trade-level backtest output
**Researched:** 2026-02-13
**Confidence:** HIGH (builds on validated v1.1 stack; additions are minimal and well-understood)

## Scope

This document covers ONLY the stack additions/changes needed for the v1.2 milestone features:

1. **Pair profitability analysis** -- per-pair P&L breakdown, ranking, historical performance
2. **Statistical distribution visualization** -- funding rate distributions, P&L histograms, box plots
3. **Market cap data** -- filtering pairs by market capitalization tier
4. **Enhanced backtest output** -- trade-level detail (entry/exit timestamps, per-trade P&L, funding collected per trade)

It does NOT re-research the existing validated stack (Python 3.12, ccxt, FastAPI, HTMX, Tailwind, Chart.js@4, aiosqlite, numpy, scipy, structlog, Decimal arithmetic).

---

## Existing Stack (Context Only -- DO NOT CHANGE)

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.12 | Runtime |
| ccxt | >=4.5.0 | Exchange API (Bybit) |
| FastAPI | >=0.115 | Dashboard backend |
| HTMX | 2.0.4 | Dashboard interactivity (CDN) |
| Tailwind CSS | CDN | Styling |
| Chart.js | @4 | Charts (CDN: `cdn.jsdelivr.net/npm/chart.js@4`) |
| Jinja2 | >=3.1 | Template rendering |
| aiosqlite | >=0.22 | Historical data storage (SQLite WAL) |
| numpy | >=2.4.0 | Array math, statistical calculations |
| scipy | >=1.17.0 | Linear regression, grid search |
| structlog | >=25.5 | Structured logging |
| Decimal (stdlib) | -- | All monetary math |

---

## Recommended NEW Stack Additions

### 1. Frontend: @sgratzl/chartjs-chart-boxplot -- Distribution Visualization

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| @sgratzl/chartjs-chart-boxplot | 4.4.5 | Box plot and violin plot chart types for Chart.js | Only maintained Chart.js box plot plugin. Provides `boxplot` and `violin` chart types that integrate natively with Chart.js 4. Required for visualizing funding rate distributions across pairs and P&L distribution analysis. |

**Confidence:** HIGH -- verified via [jsDelivr CDN](https://www.jsdelivr.com/package/npm/@sgratzl/chartjs-chart-boxplot) and [GitHub](https://github.com/sgratzl/chartjs-chart-boxplot). v4.4.5 published October 2025, actively maintained, Chart.js 4 compatible.

**CDN integration** (matches existing pattern -- no build system needed):

```html
<!-- In base.html or page-specific block, AFTER chart.js -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/@sgratzl/chartjs-chart-boxplot@4.4.5"></script>
```

The UMD build auto-registers the `boxplot` and `violin` chart types with Chart.js when loaded via script tag. No explicit `Chart.register()` call needed for UMD/CDN usage.

**Usage pattern:**

```javascript
// Funding rate distribution across pairs
new Chart(ctx, {
    type: 'boxplot',  // or 'violin' for density visualization
    data: {
        labels: ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
        datasets: [{
            label: 'Funding Rate Distribution',
            data: [
                [0.0001, 0.0002, 0.0003, 0.0001, 0.0005],  // raw arrays
                [0.0002, 0.0001, 0.0004, 0.0003, 0.0002],
                [0.0003, 0.0006, 0.0002, 0.0008, 0.0004],
            ],
            backgroundColor: 'rgba(34, 197, 94, 0.2)',
            borderColor: '#22c55e',
        }]
    },
    options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#9ca3af' } } },
        scales: {
            y: { ticks: { color: '#6b7280' }, grid: { color: '#334155' } },
            x: { ticks: { color: '#6b7280' }, grid: { color: '#334155' } },
        }
    }
});
```

**Key capability:** The plugin computes quartiles, median, whiskers, and outliers automatically from raw data arrays. No server-side statistical computation needed for box plots -- just pass arrays of funding rates per pair. This keeps the backend simple (return raw rate arrays) and the frontend handles the statistics.

---

### 2. Backend: No New Python Dependencies Required

This is the critical finding: **zero new Python packages are needed for v1.2**.

Every new capability maps to existing stack components:

| New Capability | Implementation | Libraries Used |
|----------------|----------------|----------------|
| Per-pair P&L aggregation | SQL GROUP BY queries on existing tables | aiosqlite (existing) |
| Funding rate histograms | `numpy.histogram()` server-side, Chart.js bar chart client-side | numpy (existing) |
| Statistical summaries (mean, median, std, quartiles) | `numpy.mean()`, `numpy.median()`, `numpy.std()`, `numpy.percentile()` | numpy (existing) |
| Funding rate box plots | Return raw rate arrays, boxplot plugin handles stats | numpy (existing) for array slicing |
| Market cap data | CoinGecko free API via `aiohttp`-style calls... **NO** -- use ccxt's built-in market data | ccxt (existing) |
| Trade-level backtest output | Extend BacktestResult dataclass with trade list | stdlib dataclasses (existing) |
| Per-trade P&L in backtests | PnLTracker already tracks per-position; expose it | existing Decimal analytics |
| Date range filtering for pair analysis | SQL WHERE clauses on timestamp_ms | aiosqlite (existing) |

**Why no new dependencies:**

- **numpy** (already installed) provides `numpy.histogram()` which returns bin counts and edges -- exactly what Chart.js bar charts need for histogram visualization. Server computes bins, client renders bars.
- **scipy** (already installed) provides `scipy.stats.describe()` for comprehensive statistical summaries if needed beyond numpy.
- **aiosqlite** (already installed) handles all new SQL queries for pair aggregation.
- **Chart.js** (already loaded via CDN) handles histograms as styled bar charts with zero-gap `categoryPercentage: 1.0, barPercentage: 1.0` configuration.

---

### 3. Market Cap Data: CoinGecko Free API (No Library Needed)

| Data Source | Tier | Purpose | Why |
|-------------|------|---------|-----|
| CoinGecko API v3 `/coins/markets` | Free (Demo) | Market cap per cryptocurrency for pair filtering/tiering | Best free-tier crypto market cap API. 30 calls/min, 10K calls/month. Returns market_cap, market_cap_rank for all listed coins. No API key required for basic usage (key recommended for reliability). |

**Confidence:** HIGH -- verified via [CoinGecko API docs](https://docs.coingecko.com/reference/coins-markets) and [pricing page](https://www.coingecko.com/en/api/pricing).

**Why CoinGecko over CoinMarketCap:** CoinGecko free tier provides market cap data with generous limits (30 calls/min). CoinMarketCap gates most useful endpoints behind paid tiers ($699/mo for full API). CoinGecko covers 13,000+ cryptocurrencies which is more than sufficient for Bybit's ~200 perpetual pairs.

**Why NOT add a CoinGecko Python library:**

The `pycoingecko` PyPI package is an unnecessary dependency. The API call is a single HTTP GET. The project already has `ccxt` which internally uses `aiohttp` for async HTTP -- but rather than coupling to ccxt's internals, use Python's stdlib `urllib.request` for the single synchronous call (market cap data is fetched infrequently as a cache-on-startup operation), or use the existing `aiohttp` that ccxt brings transitively.

**Implementation pattern -- direct HTTP, no new dependency:**

```python
import json
import urllib.request
from decimal import Decimal


def fetch_market_caps(vs_currency: str = "usd", per_page: int = 250) -> dict[str, Decimal]:
    """Fetch market cap data from CoinGecko. Called once on startup, cached.

    Returns:
        Dict mapping uppercase symbol (e.g., "BTC") to market cap in USD.
    """
    url = (
        f"https://api.coingecko.com/api/v3/coins/markets"
        f"?vs_currency={vs_currency}&order=market_cap_desc"
        f"&per_page={per_page}&page=1&sparkline=false"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read())

    return {
        coin["symbol"].upper(): Decimal(str(coin["market_cap"]))
        for coin in data
        if coin.get("market_cap")
    }
```

**Data freshness strategy:** Market cap tiers change slowly (BTC is always large-cap). Fetch once at startup, refresh every 24 hours. Store in memory dict. 250 coins per call covers all Bybit perpetual pairs. At 1 call per 24h, free tier of 10K calls/month is never a concern.

**Market cap tier classification:**

```python
TIER_THRESHOLDS = {
    "mega": Decimal("50_000_000_000"),    # >$50B (BTC, ETH)
    "large": Decimal("10_000_000_000"),   # $10B-$50B
    "mid": Decimal("1_000_000_000"),      # $1B-$10B
    "small": Decimal("100_000_000"),      # $100M-$1B
    "micro": Decimal("0"),                # <$100M
}
```

---

## Histogram Visualization Pattern (No Plugin Needed)

Chart.js does not have a native histogram chart type, but histograms are trivially implemented as bar charts with server-side binning. This is the standard approach used across the Chart.js ecosystem.

**Server side (numpy, already installed):**

```python
import numpy as np
from decimal import Decimal


def compute_histogram(
    values: list[Decimal], bins: int | str = "auto"
) -> dict:
    """Compute histogram bins from Decimal values for Chart.js rendering.

    Args:
        values: List of Decimal values (funding rates, P&L, etc.).
        bins: Number of bins or numpy strategy ('auto', 'sturges', 'fd').

    Returns:
        Dict with 'labels' (bin edge strings) and 'counts' (frequency per bin).
    """
    arr = np.array([float(v) for v in values], dtype=np.float64)
    counts, bin_edges = np.histogram(arr, bins=bins)

    labels = [
        f"{bin_edges[i]:.6f} - {bin_edges[i+1]:.6f}"
        for i in range(len(counts))
    ]

    return {
        "labels": labels,
        "counts": counts.tolist(),
        "bin_edges": [float(e) for e in bin_edges],
    }
```

**Client side (Chart.js bar chart, already loaded):**

```javascript
function renderHistogram(histData, title, color) {
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: histData.labels,
            datasets: [{
                label: title,
                data: histData.counts,
                backgroundColor: color + '80',
                borderColor: color,
                borderWidth: 1,
                categoryPercentage: 1.0,  // No gap between bars
                barPercentage: 1.0,        // Bars fill their category
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#9ca3af' } },
                tooltip: {
                    callbacks: {
                        title: (items) => items[0].label,
                        label: (item) => `Count: ${item.raw}`
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#6b7280', maxRotation: 45 },
                    grid: { display: false }
                },
                y: {
                    ticks: { color: '#6b7280' },
                    grid: { color: '#334155' },
                    title: { display: true, text: 'Frequency', color: '#9ca3af' }
                }
            }
        }
    });
}
```

**Why server-side binning, not client-side:** Funding rate datasets can be 50K+ records. Sending raw arrays to the browser for client-side binning wastes bandwidth and can cause UI jank. `numpy.histogram()` bins 50K records in <1ms. Send only the bin counts (20-30 numbers) to the client.

---

## Trade-Level Backtest Output (No New Dependencies)

The existing `BacktestResult` contains `equity_curve` (list of EquityPoints) and `BacktestMetrics` (aggregates). For trade-level visualization, extend the model:

**What exists:**
- `PnLTracker` already tracks per-position: `opened_at`, `closed_at`, `entry_fee`, `exit_fee`, `funding_payments` list
- `BacktestEngine` already has access to per-trade data via `self._pnl_tracker.get_closed_positions()`

**What to add (pure Python, no dependencies):**

```python
@dataclass
class BacktestTrade:
    """A single trade within a backtest run."""
    trade_number: int
    symbol: str
    entry_timestamp_ms: int
    exit_timestamp_ms: int
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    funding_collected: Decimal
    fees_paid: Decimal
    net_pnl: Decimal
    funding_payments_count: int
    holding_periods: int  # Number of 8h funding intervals held
```

Add `trades: list[BacktestTrade]` to `BacktestResult`. The `BacktestEngine._compute_metrics()` method already iterates closed positions -- simply collect them into `BacktestTrade` objects during that iteration.

**Visualization:** Trade-level data enables:
- Scatter plots: entry time vs. net P&L (Chart.js scatter type, already available)
- Trade duration histogram (numpy.histogram + bar chart pattern above)
- Funding collected per trade bar chart (Chart.js bar, already available)
- Entry/exit markers on equity curve (Chart.js annotation plugin or custom point rendering)

---

## Chart.js Annotation Plugin (Optional Enhancement)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| chartjs-plugin-annotation | 3.1.0 | Draw lines, boxes, and labels on charts | Useful for marking trade entry/exit points on equity curves, drawing threshold lines on distribution charts. Optional -- trade markers can also be done with a second scatter dataset overlaid on the equity line. |

**CDN:**
```html
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0"></script>
```

**Recommendation:** Defer this. Trade entry/exit markers on the equity curve can be implemented by adding a scatter dataset with specific points to the existing line chart -- no plugin needed. Only add the annotation plugin if simple overlays prove insufficient for the UX requirements.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Box plots | @sgratzl/chartjs-chart-boxplot (CDN) | D3.js | D3 is a completely different rendering paradigm. Would require rewriting all existing Chart.js charts or maintaining two charting libraries. Unacceptable complexity increase. |
| Box plots | @sgratzl/chartjs-chart-boxplot (CDN) | Plotly.js | Plotly is 3MB+ minified. Designed for scientific notebooks, not embedded dashboards. Massive overkill for adding box plots to an existing Chart.js dashboard. |
| Histograms | Chart.js bar chart + numpy.histogram() | Chart.js histogram plugin | No maintained histogram plugin exists for Chart.js 4. Bar charts with zero-gap configuration are the standard community approach. |
| Histograms | numpy.histogram() server-side | Client-side binning in JS | 50K+ record datasets should be binned server-side. numpy does this in <1ms. Sending raw arrays to browser is wasteful. |
| Market cap data | CoinGecko free API (direct HTTP) | pycoingecko library | One GET request does not warrant a dependency. The library adds indirection, version management, and slows API update adoption. |
| Market cap data | CoinGecko free API | CoinMarketCap API | CoinMarketCap gates market cap endpoints behind paid tiers ($699/mo). CoinGecko provides equivalent data on the free tier. |
| Market cap data | CoinGecko free API | Derive from Bybit volume | Volume is not market cap. A high-volume pair could be micro-cap during a hype cycle. Market cap provides the actual filtering dimension needed. |
| Async HTTP for CoinGecko | stdlib urllib.request | httpx / aiohttp (new dep) | Market cap is fetched once per 24h on startup. A synchronous call in a background task is fine. Adding httpx (or explicit aiohttp) for one daily HTTP call is over-engineering. ccxt already pulls aiohttp transitively if async is truly needed. |
| Trade-level output | Extend BacktestResult dataclass | New TradeLog database table | Trade data is ephemeral (per-backtest-run). Persisting to SQLite adds write overhead and cleanup complexity for data that lives only during result display. Keep it in-memory as part of the result dict. |
| Statistical summaries | numpy (mean, median, std, percentile) | pandas describe() | Pandas is 30MB+ and introduces DataFrame patterns foreign to the codebase. numpy provides identical statistical functions without the overhead. |

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| pandas | 30MB+, DataFrame paradigm not used anywhere in codebase | numpy for stats, SQL for aggregation |
| plotly / plotly.js | 3MB+ JS bundle, completely different rendering model than Chart.js | Chart.js + boxplot plugin |
| D3.js | Low-level SVG rendering library, would require rewriting all charts | Chart.js ecosystem |
| pycoingecko | Unnecessary wrapper for a single HTTP GET call | stdlib urllib.request |
| httpx | Overkill for one daily HTTP call; already have aiohttp via ccxt | urllib.request or ccxt's transitive aiohttp |
| matplotlib / seaborn | Server-side image rendering libraries for Python; we render charts client-side in Chart.js | Chart.js (all rendering in browser) |
| quantstats | Heavy analytics library (pulls pandas, matplotlib, seaborn) for generating HTML reports | Custom numpy-based analytics already built |
| chartjs-plugin-annotation | Adds complexity for trade markers that can be done with scatter datasets | Overlay scatter dataset on line chart |
| SQLAlchemy / Alembic | ORM is overkill for the 3-4 new SQL queries needed | Raw SQL via aiosqlite (existing pattern) |

---

## Installation

### New production dependencies

None. Zero new Python packages.

### CDN addition (frontend only)

Add to pages that use box plot/violin charts:

```html
<script src="https://cdn.jsdelivr.net/npm/@sgratzl/chartjs-chart-boxplot@4.4.5"></script>
```

This is a **single script tag** added to the specific template pages that need distribution visualization (likely a new `pair_explorer.html` template). The existing `base.html` does NOT need to change -- Chart.js is loaded per-page in the `{% block head %}` block (see existing `backtest.html` pattern).

### pyproject.toml

**No changes required.** The dependency list stays exactly as-is.

---

## Version Compatibility Matrix

| Package | Version | Python 3.12 | Status | Notes |
|---------|---------|-------------|--------|-------|
| @sgratzl/chartjs-chart-boxplot | 4.4.5 | N/A (JS) | Requires Chart.js >=4.0 | CDN only, UMD auto-registers |
| CoinGecko API v3 | -- | N/A (HTTP) | Free tier: 30 calls/min, 10K/month | No auth required (key recommended) |

All Python dependencies are unchanged from v1.1. No version bumps needed.

---

## Stack Patterns by Feature Area

### If building pair profitability analysis:

- **Data layer:** SQL `GROUP BY symbol` queries on `funding_rate_history` table via aiosqlite (existing)
- **Aggregation:** `SUM()`, `AVG()`, `COUNT()` in SQL for per-pair totals; numpy for statistical summaries (std, percentiles) on queried arrays
- **API:** New FastAPI endpoints returning JSON (existing pattern in `routes/api.py`)
- **Frontend:** HTMX `hx-get` to load pair cards/tables, Chart.js bar charts for rankings (existing patterns)

### If building statistical distribution visualization:

- **Histograms:** `numpy.histogram()` server-side, Chart.js bar chart client-side with `categoryPercentage: 1.0, barPercentage: 1.0`
- **Box plots:** `@sgratzl/chartjs-chart-boxplot` CDN plugin, pass raw arrays from API, plugin computes statistics
- **Violin plots:** Same plugin, `type: 'violin'` -- useful for comparing rate distributions across pairs
- **Summary stats:** `numpy.mean()`, `numpy.median()`, `numpy.std()`, `numpy.percentile([25, 75])` in API response alongside chart data

### If building market cap filtering:

- **Data source:** CoinGecko `/coins/markets` via stdlib `urllib.request`
- **Caching:** In-memory dict, refreshed every 24 hours via background asyncio task
- **Mapping:** CoinGecko returns lowercase symbol; map to ccxt symbol format (`BTC` -> `BTC/USDT:USDT`)
- **Filtering:** Add `market_cap_tier` to pair data; filter in SQL or Python depending on query pattern
- **Persistence:** Optional SQLite table for market cap cache (survive restarts without API call), but in-memory is sufficient given the 24h refresh

### If building enhanced backtest trade-level output:

- **Model:** Add `BacktestTrade` dataclass and `trades: list[BacktestTrade]` to `BacktestResult`
- **Collection:** `BacktestEngine` already iterates through trades; collect into list during `_compute_metrics()`
- **Serialization:** `to_dict()` pattern already established; extend it
- **Visualization:** Trade scatter plot (Chart.js scatter), trade P&L histogram (numpy + bar chart), trade table (HTMX + Jinja2 table partial)

---

## Summary: What Changes vs. What Stays

| Layer | Changes | Stays Same |
|-------|---------|------------|
| Python dependencies | None | All existing deps |
| Frontend CDN | +1 script tag (boxplot plugin, page-specific) | Chart.js@4, HTMX 2.0.4, Tailwind CDN |
| External APIs | +CoinGecko free tier (1 call/24h) | ccxt/Bybit |
| Data models | +BacktestTrade dataclass, +market_cap field on pairs | All existing models |
| SQL schema | +Optional market_cap_cache table | All existing tables |
| Dashboard patterns | Same: HTMX partials, Chart.js rendering, Jinja2 templates | No architectural changes |

**Total new external dependencies: 0 Python packages, 1 CDN script tag, 1 free API endpoint.**

This is intentionally minimal. The existing stack was chosen well for v1.1 and extends naturally to v1.2's visualization and analysis needs.

---

## Sources

### Verified (HIGH confidence)
- [Chart.js Bar Chart docs](https://www.chartjs.org/docs/latest/charts/bar.html) -- histogram via bar chart configuration
- [@sgratzl/chartjs-chart-boxplot on jsDelivr](https://www.jsdelivr.com/package/npm/@sgratzl/chartjs-chart-boxplot) -- v4.4.5 CDN, Chart.js 4 compatible
- [@sgratzl/chartjs-chart-boxplot GitHub](https://github.com/sgratzl/chartjs-chart-boxplot) -- actively maintained, v4.4.5 Oct 2025
- [numpy.histogram docs (v2.4)](https://numpy.org/doc/stable/reference/generated/numpy.histogram.html) -- bin computation with auto strategy
- [CoinGecko API /coins/markets](https://docs.coingecko.com/reference/coins-markets) -- market_cap field, 250 per page, free tier
- [CoinGecko API pricing](https://www.coingecko.com/en/api/pricing) -- Demo tier: 30 calls/min, 10K/month, free

### Community patterns (MEDIUM confidence)
- [Chart.js histogram via bar chart (Lei Mao)](https://leimao.github.io/blog/JavaScript-ChartJS-Histogram/) -- standard approach, manually bin + bar chart
- [Chart.js histogram discussion #10699](https://github.com/chartjs/Chart.js/discussions/10699) -- confirms bar chart approach is canonical
- [CoinGecko vs CoinMarketCap comparison](https://coincodecap.com/coinmarketcap-vs-coingecko-vs-bitquery-crypto-price-api) -- CoinGecko better free tier

---
*Stack research for: Funding Rate Arbitrage v1.2 Pair Explorer & Enhanced Visualization*
*Researched: 2026-02-13*
