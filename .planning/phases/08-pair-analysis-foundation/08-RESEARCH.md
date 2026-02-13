# Phase 8: Pair Analysis Foundation - Research

**Researched:** 2026-02-13
**Domain:** Historical funding rate analytics, per-pair statistics, dashboard page creation
**Confidence:** HIGH

## Summary

Phase 8 builds a new "Pair Explorer" dashboard page where users can browse all tracked pairs ranked by historical profitability, drill into per-pair statistics, view funding rate time series charts, and filter by date range. This is a read-only analytics feature operating entirely on the existing `funding_rate_history` SQLite table populated by Phase 4.

The implementation requires three connected pieces: (1) a backend `PairAnalyzer` service that computes per-pair statistics from historical funding rates using SQL aggregation and Python `Decimal` arithmetic, (2) new API endpoints and a new dashboard page `/pairs` with a ranking table and drill-down detail view, and (3) Chart.js time series charts with date range toggle buttons (7d/30d/90d/all). The yield calculations must incorporate the existing `FeeSettings` to produce fee-adjusted annualized figures, reusing the same formula pattern from `OpportunityRanker`.

All computation stays in Python's standard library (`Decimal`, `statistics` module concepts implemented manually) plus SQL aggregation in aiosqlite. Zero new Python dependencies are needed. The only frontend addition is Chart.js, which is already loaded on the backtest page via CDN -- it just needs to be included on the new pairs page too.

**Primary recommendation:** Build a `PairAnalyzer` service class under `src/bot/analytics/pair_analyzer.py` that accepts a `HistoricalDataStore` and `FeeSettings`, computes all statistics via SQL + Decimal arithmetic, and returns typed dataclass results. Expose via `/api/pairs/ranking` and `/api/pairs/{symbol}/stats` endpoints. Create a new `/pairs` page using the existing template/partial pattern.

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiosqlite | >=0.22 | Async SQLite queries for funding rate aggregation | Already used by `HistoricalDataStore`, WAL mode for concurrent reads |
| FastAPI | >=0.115 | API endpoints for pair data | Already the dashboard framework |
| Jinja2 | >=3.1 | Server-side template rendering for pair explorer page | Already used for all dashboard pages |
| Chart.js | @4 (CDN) | Time series line charts for funding rate history | Already loaded on `/backtest` page, proven pattern in `equity_curve.html` |
| Tailwind CSS | CDN | Styling for tables and layout | Already used for all dashboard UI |
| HTMX | 2.0.4 | Interactive date range filtering without full page reloads | Already loaded in `base.html` |
| Decimal (stdlib) | N/A | All monetary/rate arithmetic | Project-wide convention, enforced everywhere |

### Supporting (no new additions needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | >=25.5 | Structured logging in PairAnalyzer | Already project standard |
| pydantic-settings | >=2.12 | FeeSettings for yield calculation | Already configured |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual Decimal statistics | pandas/numpy | Roadmap constraint says zero new Python deps; Decimal arithmetic is sufficient for aggregation of ~20 pairs x ~1095 records |
| Chart.js for time series | Lightweight-charts (TradingView) | Chart.js already in project; lightweight-charts would be better for financial data but adds a new CDN; not worth the divergence |
| SQL aggregation in SQLite | Python-side aggregation | SQL AVG/COUNT is faster for large datasets, but SQLite lacks PERCENTILE; hybrid approach (SQL for basics, Python for median/std) is the right call |

**Installation:** No new packages needed. Chart.js CDN already in project.

## Architecture Patterns

### Recommended Project Structure
```
src/bot/
  analytics/
    pair_analyzer.py          # NEW: PairAnalyzer service class
  dashboard/
    routes/
      pages.py                # MODIFY: add /pairs route
      api.py                  # MODIFY: add /api/pairs/* endpoints
    templates/
      pairs.html              # NEW: pair explorer page (extends base.html)
      partials/
        pair_ranking_table.html    # NEW: sortable ranking table
        pair_detail.html           # NEW: per-pair stats card
        funding_rate_chart.html    # NEW: time series chart partial
```

### Pattern 1: Service Class with Typed Returns (follow existing convention)
**What:** `PairAnalyzer` is a stateless service that takes `HistoricalDataStore` + `FeeSettings` and returns typed dataclass results. Follows the same pattern as `FeeCalculator`, `OpportunityRanker`, and `SignalEngine`.
**When to use:** All new analytics computation.
**Example:**
```python
# Source: Pattern derived from src/bot/pnl/fee_calculator.py and src/bot/market_data/opportunity_ranker.py

@dataclass
class PairStats:
    """Per-pair statistics computed from historical funding rates."""
    symbol: str
    record_count: int
    avg_rate: Decimal
    median_rate: Decimal
    std_dev: Decimal
    pct_positive: Decimal
    net_yield_per_period: Decimal
    annualized_yield: Decimal
    has_sufficient_data: bool

class PairAnalyzer:
    def __init__(self, data_store: HistoricalDataStore, fee_settings: FeeSettings) -> None:
        self._store = data_store
        self._fees = fee_settings

    async def get_pair_ranking(
        self, since_ms: int | None = None, until_ms: int | None = None
    ) -> list[PairStats]:
        """Compute ranked pair statistics for all tracked pairs."""
        ...
```

### Pattern 2: API Endpoint with Date Range Query Parameters
**What:** Date range filtering via query params (e.g., `?range=30d`), converted to `since_ms`/`until_ms` timestamps server-side. Follows the same pattern as `get_funding_rates` in `store.py`.
**When to use:** All pair analysis endpoints.
**Example:**
```python
# Source: Pattern derived from src/bot/dashboard/routes/api.py

@router.get("/pairs/ranking")
async def get_pair_ranking(request: Request, range: str = "all") -> JSONResponse:
    since_ms = _range_to_since_ms(range)  # "7d" -> now - 7*86400*1000
    analyzer: PairAnalyzer = request.app.state.pair_analyzer
    ranking = await analyzer.get_pair_ranking(since_ms=since_ms)
    return JSONResponse(content=_decimal_to_str([r.to_dict() for r in ranking]))
```

### Pattern 3: Dashboard Page with Chart.js (follow backtest page pattern)
**What:** New page `/pairs` extends `base.html`, includes Chart.js CDN in `{% block head %}`, renders initial data server-side, uses JavaScript `fetch()` + Chart.js for dynamic chart updates. Follows exact same pattern as `backtest.html`.
**When to use:** The pair explorer page.
**Example:**
```html
<!-- Source: Pattern from src/bot/dashboard/templates/backtest.html -->
{% extends "base.html" %}
{% block head %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
{% endblock %}
```

### Pattern 4: SQL + Python Hybrid Statistics
**What:** Use SQL for what it does well (COUNT, SUM, AVG, MIN, MAX with WHERE clauses on time ranges) and Python for what SQLite cannot do natively (median, standard deviation, percentile). Load funding rates for a pair into memory, compute stats in Python with Decimal.
**When to use:** Per-pair statistics that need median and std dev.
**Example:**
```python
# SQL for efficient filtering and counting
cursor = await db.execute(
    "SELECT funding_rate FROM funding_rate_history "
    "WHERE symbol = ? AND timestamp_ms >= ? AND timestamp_ms <= ? "
    "ORDER BY funding_rate ASC",
    (symbol, since_ms, until_ms),
)
rows = await cursor.fetchall()
rates = [Decimal(row[0]) for row in rows]

# Python for median (SQLite has no built-in MEDIAN)
n = len(rates)
if n % 2 == 0:
    median = (rates[n // 2 - 1] + rates[n // 2]) / 2
else:
    median = rates[n // 2]
```

### Pattern 5: Date Range Toggle with HTMX or Vanilla JS
**What:** Date range buttons (7d, 30d, 90d, all) that re-fetch data from the API and update the table and chart. Can use either HTMX partial swap or vanilla JS `fetch()` + DOM update. The backtest page uses vanilla JS `fetch()`, which is the established pattern.
**When to use:** The date range filter UI.

### Anti-Patterns to Avoid
- **Loading all rates for all pairs in a single query:** This could return hundreds of thousands of rows. Query per-pair or use SQL aggregation with GROUP BY.
- **Using float for rate arithmetic:** Project convention is Decimal everywhere. SQLite stores rates as TEXT; restore to Decimal on read.
- **Computing statistics on the frontend:** All statistical computation must happen server-side in Python. The frontend only receives pre-computed values and renders charts.
- **Creating a separate database or new tables:** All data exists in `funding_rate_history` and `tracked_pairs`. No schema changes needed.
- **Adding Python dependencies:** The roadmap constraint explicitly says "Zero new Python dependencies."

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Chart.js time axis | Custom date formatting/positioning | `chartjs-adapter-date-fns` (CDN) | Chart.js requires a date adapter for time-scale axes; adapter-date-fns is the official recommendation; it's a CDN script, not a Python dep |
| Fee-adjusted yield formula | New yield calculation | Reuse `OpportunityRanker` formula pattern | The formula `net_yield = rate - (spot_taker + perp_taker) * 2 / min_holding_periods` is already implemented and verified in `opportunity_ranker.py` |
| Annualization | Custom annualization math | Reuse `_HOURS_PER_YEAR / interval_hours` pattern | Already proven in `OpportunityRanker` |
| JSON serialization of Decimals | Custom serializer | Reuse `_decimal_to_str()` from `api.py` | Already handles recursive Decimal-to-string conversion |
| Database connection lifecycle | Manual connection management | Reuse `HistoricalDatabase` context manager | Already handles WAL mode, pragmas, schema creation |

**Key insight:** Phase 8 is almost entirely composed of existing patterns wired to new queries. The `OpportunityRanker` already computes fee-adjusted annualized yield for live rates -- we just need the same formula applied to historical averages. The `BacktestEngine` already loads funding rates by time range. The dashboard already has page/route/template patterns. This phase is integration work, not invention.

## Common Pitfalls

### Pitfall 1: Insufficient Data Skewing Rankings
**What goes wrong:** A pair with 2 extremely high funding rate records (e.g., from a listing pump event) ranks #1 by average, misleading users.
**Why it happens:** Low-data pairs have volatile statistics. A pair tracked for 1 day has 3 records (8h intervals); computing "annualized yield" from 3 data points is meaningless.
**How to avoid:** Define a minimum record count threshold (e.g., `MIN_RECORDS = 30` = ~10 days at 8h intervals). Pairs below this are either excluded from ranking or flagged with a "Low data" badge. This directly addresses Success Criterion #5.
**Warning signs:** Any pair with `record_count < 30` in the ranking response.

### Pitfall 2: Mixing Funding Intervals in Statistics
**What goes wrong:** Some Bybit pairs have 4h funding intervals, others 8h. Computing average rate across mixed intervals produces a meaningless number.
**Why it happens:** The `interval_hours` field in `HistoricalFundingRate` varies per record. Bybit changed some pairs from 8h to 4h.
**How to avoid:** Always normalize rates to a common period (per-8h or per-1h) before averaging. Or compute annualized yield which inherently accounts for interval differences: `annualized = rate * (8760 / interval_hours)`.
**Warning signs:** Pairs with mixed `interval_hours` values in their history.

### Pitfall 3: Chart.js Time Scale Without Date Adapter
**What goes wrong:** Chart.js displays timestamps as raw numbers instead of formatted dates. Chart fails silently or shows "Invalid Date".
**Why it happens:** Chart.js time scale (`type: 'time'`) requires a date adapter plugin. The existing equity curve chart avoids this by manually formatting labels, but a proper time series chart should use time scale.
**How to avoid:** Either (a) include `chartjs-adapter-date-fns` CDN and use `type: 'time'` scale, or (b) follow the existing pattern from `equity_curve.html` of pre-formatting labels as strings. Option (b) is simpler and already proven in the codebase.
**Warning signs:** Chart shows numbers on x-axis instead of dates.

### Pitfall 4: N+1 Query Pattern for All-Pairs Statistics
**What goes wrong:** Computing stats for 20 pairs makes 20 separate SQL queries (one per pair), taking several hundred milliseconds total.
**Why it happens:** Naive implementation: `for pair in pairs: stats = await compute_stats(pair)`.
**How to avoid:** Use SQL `GROUP BY symbol` for basic aggregations (COUNT, SUM, AVG). For median/std dev that require Python, batch-load all rates for all pairs in one query with `WHERE symbol IN (...)` and process in-memory grouped by symbol. For 20 pairs x 365 days x 3 records/day = ~22,000 rows, this fits easily in memory.
**Warning signs:** API response time > 500ms for the ranking endpoint.

### Pitfall 5: Decimal Precision Loss in JSON Serialization
**What goes wrong:** Frontend receives `0.00030000000000000003` instead of `0.0003` because a Decimal was accidentally converted to float before serialization.
**Why it happens:** Using `float(rate)` anywhere in the pipeline or letting JSON serializer auto-convert.
**How to avoid:** Always use `str(decimal_value)` for JSON serialization. The existing `_decimal_to_str()` helper in `api.py` handles this correctly. Parse back to `parseFloat()` only on the frontend where display precision doesn't matter.
**Warning signs:** Trailing digits in JSON responses.

### Pitfall 6: Missing Navigation Link
**What goes wrong:** User can't find the new Pair Explorer page because there's no link in the navigation bar.
**Why it happens:** Forgetting to update `base.html` nav section when adding a new page.
**How to avoid:** Add the `/pairs` link to the nav bar in `base.html` alongside the existing Dashboard and Backtest links.
**Warning signs:** Page exists at `/pairs` but is only reachable by typing the URL directly.

## Code Examples

Verified patterns from the existing codebase:

### Querying Funding Rates with Time Range (existing pattern)
```python
# Source: src/bot/data/store.py lines 172-207
async def get_funding_rates(
    self,
    symbol: str,
    since_ms: int | None = None,
    until_ms: int | None = None,
) -> list[HistoricalFundingRate]:
    conditions = ["symbol = ?"]
    params: list = [symbol]

    if since_ms is not None:
        conditions.append("timestamp_ms >= ?")
        params.append(since_ms)
    if until_ms is not None:
        conditions.append("timestamp_ms <= ?")
        params.append(until_ms)

    where = " AND ".join(conditions)
    cursor = await self._database.db.execute(
        f"SELECT symbol, timestamp_ms, funding_rate, interval_hours "
        f"FROM funding_rate_history WHERE {where} ORDER BY timestamp_ms ASC",
        params,
    )
    rows = await cursor.fetchall()
    return [
        HistoricalFundingRate(
            symbol=row[0],
            timestamp_ms=row[1],
            funding_rate=Decimal(row[2]),
            interval_hours=row[3],
        )
        for row in rows
    ]
```

### Fee-Adjusted Yield Computation (existing pattern)
```python
# Source: src/bot/market_data/opportunity_ranker.py lines 59-83
round_trip_fee_pct = (
    self._fee_settings.spot_taker + self._fee_settings.perp_taker
) * 2
amortized_fee = round_trip_fee_pct / Decimal(str(min_holding_periods))

net_yield_per_period = fr.rate - amortized_fee
periods_per_year = _HOURS_PER_YEAR / Decimal(str(fr.interval_hours))
annualized_yield = net_yield_per_period * periods_per_year
```

### Chart.js Line Chart (existing pattern)
```javascript
// Source: src/bot/dashboard/templates/partials/equity_curve.html lines 16-81
function renderEquityCurve(equityData, label, color) {
    const ctx = document.getElementById('equity-chart').getContext('2d');
    if (window._equityChart) {
        window._equityChart.destroy();
    }
    const labels = equityData.map(p => {
        const d = new Date(p.timestamp_ms);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const values = equityData.map(p => parseFloat(p.equity));
    window._equityChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets: [{ label, data: values, borderColor: color, ... }] },
        options: { responsive: true, maintainAspectRatio: false, ... }
    });
}
```

### Dashboard Page Creation (existing pattern)
```python
# Source: src/bot/dashboard/routes/pages.py lines 100-114
@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request) -> HTMLResponse:
    templates: Jinja2Templates = request.app.state.templates
    data_store = getattr(request.app.state, "data_store", None)
    tracked_pairs: list[dict] = []
    if data_store is not None:
        tracked_pairs = await data_store.get_tracked_pairs(active_only=True)
    return templates.TemplateResponse("backtest.html", {
        "request": request,
        "tracked_pairs": tracked_pairs,
    })
```

### Decimal Standard Deviation (pure stdlib, no numpy)
```python
# Pattern for computing sample std dev with Decimal precision
def _decimal_std_dev(values: list[Decimal]) -> Decimal:
    """Sample standard deviation (N-1 denominator) using Decimal."""
    n = Decimal(len(values))
    if n < 2:
        return Decimal("0")
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - Decimal("1"))
    return variance.sqrt()
```

### Bulk SQL Aggregation with GROUP BY
```python
# Efficient multi-pair statistics using SQL GROUP BY
cursor = await db.execute(
    "SELECT symbol, COUNT(*), SUM(CAST(funding_rate AS REAL)), "
    "SUM(CASE WHEN CAST(funding_rate AS REAL) > 0 THEN 1 ELSE 0 END) "
    "FROM funding_rate_history "
    "WHERE timestamp_ms >= ? AND timestamp_ms <= ? "
    "GROUP BY symbol",
    (since_ms, until_ms),
)
# Note: SUM(CAST(...)) for basic aggregations; median/std need Python-side
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Live-only funding rates | Historical data store (Phase 4) | v1.1 (2026-02-12) | Now have 365 days of funding history per pair to analyze |
| No pair comparison | OpportunityRanker for live rates | v1.0 (2026-02-11) | Yield formula exists, just needs historical application |
| Manual label formatting in Chart.js | Same (no time adapter) | Current | Works fine; time adapter is optional if we pre-format labels |

**No deprecated patterns apply.** The project stack (FastAPI, Chart.js 4, Tailwind CDN, aiosqlite) is current and stable.

## Open Questions

1. **Minimum data threshold for pair inclusion**
   - What we know: Some pairs may have very few funding records (e.g., recently listed). Success Criterion #5 requires flagging or excluding them.
   - What's unclear: What specific threshold constitutes "sufficient data"? 30 records (~10 days)? 90 records (~30 days)?
   - Recommendation: Default to 30 records (MIN_RECORDS constant). Pairs below threshold are included in ranking but displayed with a "(low data)" badge and sorted to bottom. This balances visibility with accuracy.

2. **Chart.js date adapter: include or not?**
   - What we know: The existing equity curve chart uses pre-formatted string labels (no time adapter). A proper time series uses `type: 'time'` scale which requires `chartjs-adapter-date-fns` CDN.
   - What's unclear: Whether the extra CDN is worth the time-axis improvement (zoom, proper spacing for irregular timestamps).
   - Recommendation: Follow existing pattern -- pre-format labels as strings. This avoids a new CDN dependency and is consistent with the equity curve. If the roadmap mentions "one CDN addition (boxplot plugin)", that's allocated for Phase 10, not here.

3. **Number of min_holding_periods for historical yield calculation**
   - What we know: `OpportunityRanker` uses a configurable `min_holding_periods` (default 3) to amortize round-trip fees. For historical analysis, we're looking at average rates, not a single snapshot.
   - What's unclear: Whether to use the same default (3) or a different value for historical pair ranking.
   - Recommendation: Use the same `min_holding_periods = 3` from `RiskSettings` to maintain consistency between live ranking and historical ranking. This way the user sees consistent yield numbers.

4. **Where to store PairAnalyzer instance**
   - What we know: Other services are stored on `app.state` (e.g., `app.state.data_store`, `app.state.orchestrator`). PairAnalyzer needs `data_store` and `fee_settings`.
   - What's unclear: Whether to instantiate in app lifespan or lazily in route handlers.
   - Recommendation: Instantiate in the app lifespan (in `main.py`) and store on `app.state.pair_analyzer`, following the pattern of other services. This avoids repeated construction.

## Sources

### Primary (HIGH confidence)
- **Codebase analysis** - All patterns and code examples come from direct reading of the project source files:
  - `src/bot/data/store.py` - HistoricalDataStore query patterns
  - `src/bot/data/database.py` - Schema definition (funding_rate_history table)
  - `src/bot/data/models.py` - HistoricalFundingRate dataclass
  - `src/bot/market_data/opportunity_ranker.py` - Fee-adjusted yield formula
  - `src/bot/pnl/fee_calculator.py` - FeeCalculator and FeeSettings usage
  - `src/bot/config.py` - FeeSettings, HistoricalDataSettings, RiskSettings
  - `src/bot/analytics/metrics.py` - Decimal statistics pattern (sharpe, std dev)
  - `src/bot/dashboard/app.py` - App factory and template setup
  - `src/bot/dashboard/routes/pages.py` - Page route pattern
  - `src/bot/dashboard/routes/api.py` - API endpoint pattern
  - `src/bot/dashboard/templates/base.html` - Base template with CDN includes
  - `src/bot/dashboard/templates/backtest.html` - Chart.js page pattern
  - `src/bot/dashboard/templates/partials/equity_curve.html` - Chart.js rendering pattern
  - `src/bot/backtest/engine.py` - Historical data loading and time range filtering
  - `tests/test_analytics.py` - Test patterns for Decimal analytics

### Secondary (MEDIUM confidence)
- **Chart.js documentation** - Chart.js v4 line chart API, time scale adapter requirement (based on training data, verified by CDN URL pattern in existing project)
- **SQLite documentation** - GROUP BY aggregation, CAST for numeric comparison, lack of native MEDIAN/PERCENTILE/STDDEV functions

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Everything is already in the project. Zero new dependencies needed.
- Architecture: HIGH - All patterns directly derived from existing codebase code (not hypothesized).
- Pitfalls: HIGH - Pitfalls identified from direct analysis of data model constraints and existing code patterns.
- Yield formula: HIGH - Exact formula already implemented and tested in OpportunityRanker.

**Research date:** 2026-02-13
**Valid until:** 2026-03-15 (stable -- no moving parts; all dependencies already pinned)
