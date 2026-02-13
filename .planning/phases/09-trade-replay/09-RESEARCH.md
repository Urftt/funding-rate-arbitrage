# Phase 9: Trade Replay - Research

**Researched:** 2026-02-13
**Domain:** Backtest trade-level data extraction, trade log UI, win/loss analytics, Chart.js trade markers and histograms
**Confidence:** HIGH

## Summary

Phase 9 adds per-trade detail to backtest results so users can understand exactly why strategies win or lose. The backtest engine (Phase 6) already tracks every position through `PnLTracker`, which records entry/exit prices, entry/exit fees, and individual funding payments (`FundingPayment` records with amount, rate, mark_price, timestamp). All the raw data needed for trade-level analysis already exists in `PositionPnL` objects -- the work is extracting it into a structured `BacktestTrade` model, computing per-trade metrics, and surfacing them through the API and UI.

The implementation requires three connected pieces: (1) a `BacktestTrade` dataclass that captures per-trade detail (entry/exit times, prices, funding collected, fees paid, holding period, net P&L) extracted from the existing `PnLTracker.get_closed_positions()` data, plus a `TradeStats` summary dataclass for aggregate win/loss statistics; (2) new API response fields and UI components on the existing backtest page -- a trade log table with expandable rows and a summary statistics card; (3) Chart.js enhancements to the equity curve (trade entry/exit markers via scatter point datasets in a mixed chart) and a new P&L distribution histogram (bar chart with manual binning).

Zero new Python dependencies are needed. The only potential frontend addition is the `chartjs-plugin-annotation` CDN for drawing point annotations on charts, but this can be avoided entirely by using Chart.js's built-in mixed chart capability (scatter point datasets overlaid on the line chart), which is simpler and consistent with the zero-new-dependency philosophy. The histogram is a standard Chart.js bar chart with server-side binning.

**Primary recommendation:** Create a `BacktestTrade` dataclass in `backtest/models.py` that extracts trade detail from `PositionPnL` during `_compute_metrics()`. Add a `trades` list and `trade_stats` summary to `BacktestResult.to_dict()`. Extend the backtest UI with a trade log table, summary stats card, scatter-point trade markers on the equity curve, and a bar-chart P&L distribution histogram -- all using existing Chart.js CDN and vanilla JS patterns.

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Chart.js | @4 (CDN) | Equity curve trade markers (mixed line+scatter) and P&L histogram (bar chart) | Already loaded on `/backtest` page via CDN, proven in `equity_curve.html` |
| FastAPI | >=0.115 | API endpoints return trade-level data in backtest results | Already the dashboard framework |
| Jinja2 | >=3.1 | Server-side template rendering for trade log partial | Already used for all dashboard pages |
| Tailwind CSS | CDN | Styling for trade log table, expandable rows, summary cards | Already used for all dashboard UI |
| Decimal (stdlib) | N/A | All monetary/P&L arithmetic | Project-wide convention, enforced everywhere |
| dataclasses (stdlib) | N/A | `BacktestTrade` and `TradeStats` models | Consistent with all project models |

### Supporting (no new additions needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | >=25.5 | Structured logging in trade extraction | Already project standard |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Mixed line+scatter chart for trade markers | `chartjs-plugin-annotation` CDN | Annotation plugin adds a CDN dependency; mixed chart approach uses built-in Chart.js feature, is simpler, and avoids the roadmap's "one CDN addition" budget (reserved for boxplot in Phase 10) |
| Server-side histogram binning | Client-side binning in JS | Server-side keeps computation in Python/Decimal, consistent with project pattern of "all statistics server-side" |
| Separate trade replay page | Extend existing backtest page | Extending the existing page keeps trades in context with the equity curve and metrics; no new page route needed |

**Installation:** No new packages needed. All capabilities use existing Chart.js CDN and Python stdlib.

## Architecture Patterns

### Recommended Project Structure
```
src/bot/
  backtest/
    models.py                    # MODIFY: add BacktestTrade, TradeStats dataclasses
    engine.py                    # MODIFY: extract trades from PnLTracker in _compute_metrics()
  dashboard/
    templates/
      backtest.html              # MODIFY: add trade log section, trade stats, histogram
      partials/
        equity_curve.html        # MODIFY: add trade marker scatter datasets
        trade_log.html           # NEW: expandable trade log table partial
        trade_stats.html         # NEW: win/loss summary stats card
        pnl_histogram.html       # NEW: P&L distribution histogram
```

### Pattern 1: Trade Data Extraction from PnLTracker (core data flow)
**What:** The `BacktestEngine._compute_metrics()` method already calls `self._pnl_tracker.get_closed_positions()` which returns `list[PositionPnL]`. Each `PositionPnL` contains everything needed: entry prices, exit prices, entry/exit fees, funding payments list (with individual timestamps, rates, and amounts), opened_at, closed_at. The new `BacktestTrade` dataclass is a computed projection of this data with pre-calculated fields (total_funding, total_fees, net_pnl, holding_hours, is_win).
**When to use:** During backtest result construction.
**Example:**
```python
# Source: Pattern derived from src/bot/backtest/engine.py _compute_metrics()
# and src/bot/pnl/tracker.py PositionPnL

@dataclass
class BacktestTrade:
    """Per-trade detail extracted from a closed PositionPnL."""
    trade_number: int
    entry_time_ms: int      # opened_at * 1000
    exit_time_ms: int       # closed_at * 1000
    entry_price: Decimal    # perp_entry_price (used as reference price)
    exit_price: Decimal     # perp_exit_price
    quantity: Decimal
    funding_collected: Decimal  # sum of funding_payments
    entry_fee: Decimal
    exit_fee: Decimal
    total_fees: Decimal     # entry_fee + exit_fee
    net_pnl: Decimal        # funding_collected - total_fees
    holding_periods: int    # len(funding_payments)
    is_win: bool            # net_pnl > 0

    @staticmethod
    def from_position_pnl(pnl: PositionPnL, trade_number: int) -> "BacktestTrade":
        funding = sum((fp.amount for fp in pnl.funding_payments), Decimal("0"))
        total_fees = pnl.entry_fee + pnl.exit_fee
        net = funding - total_fees
        return BacktestTrade(
            trade_number=trade_number,
            entry_time_ms=int(pnl.opened_at * 1000),
            exit_time_ms=int((pnl.closed_at or 0) * 1000),
            entry_price=pnl.perp_entry_price,
            exit_price=pnl.perp_exit_price,
            quantity=pnl.quantity,
            funding_collected=funding,
            entry_fee=pnl.entry_fee,
            exit_fee=pnl.exit_fee,
            total_fees=total_fees,
            net_pnl=net,
            holding_periods=len(pnl.funding_payments),
            is_win=net > Decimal("0"),
        )
```

### Pattern 2: Aggregate Trade Statistics
**What:** A `TradeStats` dataclass computes summary statistics from the trade list: win rate, avg win size, avg loss size, best trade, worst trade, avg holding periods, total trades, winning trades, losing trades.
**When to use:** Alongside the trade list in `BacktestResult`.
**Example:**
```python
@dataclass
class TradeStats:
    """Aggregate statistics computed from a list of BacktestTrade."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal | None
    avg_win: Decimal | None
    avg_loss: Decimal | None
    best_trade: Decimal | None
    worst_trade: Decimal | None
    avg_holding_periods: Decimal | None

    @staticmethod
    def from_trades(trades: list["BacktestTrade"]) -> "TradeStats":
        if not trades:
            return TradeStats(0, 0, 0, None, None, None, None, None, None)
        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        ...
```

### Pattern 3: Mixed Chart for Trade Markers (no annotation plugin)
**What:** Chart.js supports mixed chart types within a single chart. Add scatter-type datasets to the existing line chart for entry (green triangles) and exit (red triangles) markers. This avoids the `chartjs-plugin-annotation` CDN dependency entirely.
**When to use:** Trade markers on the equity curve.
**Example:**
```javascript
// Source: Chart.js docs - Mixed Chart Types
// https://www.chartjs.org/docs/latest/charts/mixed.html
window._equityChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: labels,
        datasets: [
            // Equity curve (line)
            { type: 'line', label: 'Equity', data: equityValues, ... },
            // Trade entries (scatter points)
            {
                type: 'scatter',
                label: 'Entry',
                data: entryPoints.map(t => ({ x: t.labelIndex, y: t.equity })),
                pointStyle: 'triangle',
                pointRadius: 8,
                backgroundColor: '#22c55e',
                borderColor: '#22c55e',
                showLine: false,
            },
            // Trade exits (scatter points)
            {
                type: 'scatter',
                label: 'Exit',
                data: exitPoints.map(t => ({ x: t.labelIndex, y: t.equity })),
                pointStyle: 'triangle',
                rotation: 180,
                pointRadius: 8,
                backgroundColor: '#ef4444',
                borderColor: '#ef4444',
                showLine: false,
            }
        ]
    },
    ...
});
```

### Pattern 4: Server-Side Histogram Binning
**What:** Compute P&L histogram bins on the server (Python) rather than the client (JS). This keeps all statistical computation server-side, consistent with the project pattern. The API returns bin edges and counts; the frontend renders a Chart.js bar chart.
**When to use:** The P&L distribution histogram (TRPL-05).
**Example:**
```python
def _compute_pnl_histogram(trades: list[BacktestTrade], bin_count: int = 10) -> dict:
    """Compute histogram bins for trade P&L distribution."""
    if not trades:
        return {"bins": [], "counts": []}
    pnls = [t.net_pnl for t in trades]
    min_pnl = min(pnls)
    max_pnl = max(pnls)
    if min_pnl == max_pnl:
        return {"bins": [str(min_pnl)], "counts": [len(pnls)]}
    bin_width = (max_pnl - min_pnl) / Decimal(str(bin_count))
    bins = []
    counts = []
    for i in range(bin_count):
        lower = min_pnl + bin_width * Decimal(str(i))
        upper = lower + bin_width
        label = f"${float(lower):.2f}"
        count = sum(1 for p in pnls if lower <= p < upper or (i == bin_count - 1 and p == max_pnl))
        bins.append(label)
        counts.append(count)
    return {"bins": bins, "counts": counts}
```

### Pattern 5: Expandable Table Rows (HTML/CSS only, no JS framework)
**What:** Trade log table with clickable rows that expand to show full P&L breakdown. Uses Tailwind `hidden` class toggling with inline onclick handlers, consistent with the existing HTMX-less vanilla JS patterns in the codebase.
**When to use:** The trade log table (TRPL-02).
**Example:**
```javascript
// Each trade row has a summary row and a hidden detail row
function buildTradeRow(trade) {
    var pnlColor = trade.is_win ? 'text-green-400' : 'text-red-400';
    var summaryRow = '<tr class="border-b border-dash-border cursor-pointer hover:bg-dash-bg/50" ' +
        'onclick="this.nextElementSibling.classList.toggle(\'hidden\')">' +
        '<td class="py-2 px-2">#' + trade.trade_number + '</td>' +
        '<td class="py-2 px-2 font-mono text-xs">' + fmtDate(trade.entry_time_ms) + '</td>' +
        '<td class="py-2 px-2 font-mono text-xs">' + fmtDate(trade.exit_time_ms) + '</td>' +
        '<td class="text-right py-2 px-2 font-mono ' + pnlColor + '">' + fmtDollar(trade.net_pnl) + '</td>' +
        '<td class="text-right py-2 px-2">' + trade.holding_periods + '</td>' +
        '<td class="py-2 px-2">' + (trade.is_win ? '✓ Win' : '✗ Loss') + '</td>' +
        '</tr>';
    var detailRow = '<tr class="hidden bg-dash-bg/30">' +
        '<td colspan="6" class="py-3 px-4">' +
        '... expandable detail content ...' +
        '</td></tr>';
    return summaryRow + detailRow;
}
```

### Anti-Patterns to Avoid
- **Adding `BacktestTrade` list to `EquityPoint`:** Trade data belongs at the result level, not per-equity-point. Each equity point corresponds to a funding rate timestamp; trades span multiple timestamps.
- **Storing full trade list in parameter sweep results:** Sweep results already discard equity curves for memory management (only best result keeps its curve). Trade lists should follow the same pattern -- only the best result retains trades.
- **Computing trade statistics on the frontend:** All P&L math must happen server-side in Python with Decimal precision. Frontend only receives pre-computed values.
- **Using `chartjs-plugin-annotation` CDN for trade markers:** This consumes the roadmap's "one CDN addition" budget (reserved for boxplot in Phase 10). Use Chart.js's built-in mixed chart scatter datasets instead.
- **Creating a new page for trade replay:** Trade details belong on the existing backtest page, in context with the equity curve and metrics.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| P&L calculation per trade | Custom P&L formula | Extract from `PositionPnL` (funding_payments sum - entry_fee - exit_fee) | This exact formula is already used in `_net_return()` in `analytics/metrics.py` and in `_compute_metrics()` in `engine.py` |
| Win rate calculation | New win rate function | Reuse formula from `analytics/metrics.py:win_rate()` | Already implemented and tested |
| Trade marker positioning | Complex timestamp-to-pixel mapping | Chart.js scatter datasets with label indices | Chart.js handles coordinate mapping natively |
| Histogram binning | numpy.histogram | Manual Decimal-based binning | Zero dependency constraint; ~15 lines of Python |
| JSON Decimal serialization | Custom serializer | Reuse `to_dict()` pattern with `str(decimal_value)` | Consistent with all existing model serialization |
| Expandable table rows | React/Vue/Alpine components | Vanilla JS onclick + classList.toggle | Consistent with existing dashboard patterns (no JS frameworks) |

**Key insight:** Phase 9 is primarily a data extraction and UI presentation task. The `PnLTracker` already captures all the raw data -- every `PositionPnL` has entry prices, exit prices, fees, and every individual `FundingPayment` with its rate and amount. The work is transforming this into a user-friendly `BacktestTrade` model and rendering it in the UI. No new data collection or computation logic is needed; it is a projection of existing data.

## Common Pitfalls

### Pitfall 1: total_trades Double-Counting in BacktestEngine
**What goes wrong:** The existing `total_trades` counter in `engine.py` increments on BOTH opens AND closes (line 321 `total_trades += 1` for close, line 374 `total_trades += 1` for open). This means `total_trades` is roughly double the number of actual round-trip trades. This will confuse users if displayed alongside the new trade list.
**Why it happens:** The counter was designed for the `BacktestMetrics` summary before trade-level detail existed. "Total trades" meant "total trade events" (orders), not "round-trip positions."
**How to avoid:** The new `BacktestTrade` list is built from `get_closed_positions()` which gives the correct count of round-trip trades. Use `len(trades)` for the trade count in `TradeStats`, not the legacy `total_trades` counter. Consider clarifying in `BacktestMetrics` that `total_trades` means "trade events" or replacing it with the round-trip count.
**Warning signs:** Trade count in the summary card being 2x the length of the trade log table.

### Pitfall 2: Timestamp Mismatch Between Equity Curve and Trade Markers
**What goes wrong:** Trade entry/exit timestamps from `PositionPnL.opened_at` / `closed_at` (seconds) don't align with `EquityPoint.timestamp_ms` (milliseconds). Markers appear at wrong positions on the equity curve.
**Why it happens:** `PositionPnL.opened_at` and `closed_at` are Unix timestamps in **seconds** (from `time.time()` or the `time_fn` callback). `EquityPoint.timestamp_ms` is in **milliseconds**. The backtest engine sets `self._current_time_s = fr.timestamp_ms / 1000.0` and the PnLTracker uses that as `closed_at`.
**How to avoid:** Convert consistently: `entry_time_ms = int(pnl.opened_at * 1000)`. For chart positioning, match trade timestamps to the nearest equity curve point by finding the closest `timestamp_ms` in the equity curve array. Since entry/exit happen at funding rate timestamps, they should exactly match equity points.
**Warning signs:** Trade markers floating between or outside equity curve points.

### Pitfall 3: Empty Trade List for Short Backtests
**What goes wrong:** A backtest with 0 trades (no positions were ever opened) causes division-by-zero in avg_win, avg_loss, or histogram binning.
**Why it happens:** Very conservative thresholds or short date ranges may produce no trades. The strategy never triggers an entry.
**How to avoid:** All `TradeStats` fields that require division should return `None` when there are no trades (or no wins/losses). The histogram function should return empty bins/counts. The UI should show "No trades" instead of empty tables/charts.
**Warning signs:** NaN or division-by-zero errors in the API response.

### Pitfall 4: Equity Curve Trade Marker Indices with Category Scale
**What goes wrong:** Chart.js scatter datasets use `{x, y}` coordinates, but the equity curve uses category labels (string dates), not numeric x-axis values. Scatter points need numeric x values to position correctly on a category scale.
**Why it happens:** The existing equity curve uses `labels: [date strings]` with a category x-axis (Chart.js default for string labels). Scatter datasets expect numeric x coordinates.
**How to avoid:** Use the label array index as the x-coordinate for scatter points. For each trade entry/exit timestamp, find the index in the equity curve array where `timestamp_ms` matches, and use that index as the x value. Chart.js category scales accept numeric indices.
**Warning signs:** Scatter points clustered at x=0 or not visible at all.

### Pitfall 5: Sweep Memory Bloat from Trade Lists
**What goes wrong:** Adding a `trades` list to `BacktestResult` means parameter sweeps now retain trade-level data for every combination, vastly increasing memory usage. A sweep with 45 combinations x 50 trades each = 2,250 trade objects.
**Why it happens:** The sweep already manages this for equity curves -- it only keeps the best result's curve. The same pattern must apply to trades.
**How to avoid:** Follow the existing `sweep.py` memory management pattern: only retain the `trades` list for the best result (highest net P&L). All other results have their trades list replaced with an empty list after metrics extraction. The trade statistics (`TradeStats`) are kept for all results since they are compact aggregates.
**Warning signs:** Memory growth during parameter sweeps.

### Pitfall 6: P&L Histogram with All Same-Value Trades
**What goes wrong:** If all trades have the same net P&L (e.g., all trades lose exactly the same amount due to fees with no funding), the histogram bin width is zero, causing division by zero or a single degenerate bar.
**Why it happens:** `max_pnl == min_pnl` means the range is zero. `bin_width = 0 / 10 = 0`.
**How to avoid:** Special-case: if `min_pnl == max_pnl`, return a single bin containing all trades.
**Warning signs:** Histogram shows no bars or throws an error.

## Code Examples

Verified patterns from the existing codebase:

### Closed Position Access (existing data source for trades)
```python
# Source: src/bot/pnl/tracker.py lines 384-394
def get_closed_positions(self) -> list[PositionPnL]:
    """Return closed positions sorted by close time (most recent first)."""
    closed = [p for p in self._position_pnl.values() if p.closed_at is not None]
    closed.sort(key=lambda p: p.closed_at, reverse=True)
    return closed
```

### Net Return Calculation (existing formula to reuse)
```python
# Source: src/bot/analytics/metrics.py lines 14-27
def _net_return(position: PositionPnL) -> Decimal:
    """Compute net return for a closed position: funding - fees."""
    total_funding = sum(
        (fp.amount for fp in position.funding_payments),
        Decimal("0"),
    )
    return total_funding - position.entry_fee - position.exit_fee
```

### PositionPnL Data Available per Trade (existing data model)
```python
# Source: src/bot/pnl/tracker.py lines 39-53
@dataclass
class PositionPnL:
    """P&L tracking state for a single delta-neutral position."""
    position_id: str
    entry_fee: Decimal
    exit_fee: Decimal = Decimal("0")
    funding_payments: list[FundingPayment] = field(default_factory=list)
    spot_entry_price: Decimal = Decimal("0")
    perp_entry_price: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    opened_at: float = 0.0
    closed_at: float | None = None
    spot_exit_price: Decimal = Decimal("0")
    perp_exit_price: Decimal = Decimal("0")
    perp_symbol: str = ""
```

### FundingPayment Detail (existing per-payment data)
```python
# Source: src/bot/pnl/tracker.py lines 28-34
@dataclass
class FundingPayment:
    """Record of a single funding payment for a position."""
    amount: Decimal
    rate: Decimal
    mark_price: Decimal
    timestamp: float
```

### BacktestResult Serialization (pattern to extend)
```python
# Source: src/bot/backtest/models.py lines 180-203
def to_dict(self) -> dict:
    return {
        "config": self.config.to_dict(),
        "equity_curve": [
            {"timestamp_ms": ep.timestamp_ms, "equity": str(ep.equity)}
            for ep in self.equity_curve
        ],
        "metrics": { ... },
        # NEW: add trades and trade_stats here
    }
```

### Chart.js Equity Curve (existing pattern to extend with scatter datasets)
```javascript
// Source: src/bot/dashboard/templates/partials/equity_curve.html lines 16-81
function renderEquityCurve(equityData, label, color) {
    const ctx = document.getElementById('equity-chart').getContext('2d');
    if (window._equityChart) { window._equityChart.destroy(); }
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

### Sweep Memory Management (existing pattern for trade list handling)
```python
# Source: src/bot/backtest/sweep.py lines 126-151
# Only the best result retains full data; others are trimmed
if result.metrics.net_pnl > best_pnl:
    if best_index >= 0:
        results[best_index] = (
            results[best_index][0],
            BacktestResult(
                config=results[best_index][1].config,
                equity_curve=[],  # Discard to save memory
                metrics=results[best_index][1].metrics,
            ),
        )
    best_pnl = result.metrics.net_pnl
    best_index = len(results)
    results.append((params, result))  # Keep full for new best
```

### Metric Card HTML (existing pattern for stats display)
```javascript
// Source: src/bot/dashboard/templates/backtest.html lines 163-168
function metricCard(label, value, colorClass) {
    return '<div class="bg-dash-card rounded-lg border border-dash-border p-3">' +
           '<p class="text-xs text-gray-400 mb-1">' + label + '</p>' +
           '<p class="text-lg font-semibold ' + (colorClass || 'text-white') + '">' + value + '</p>' +
           '</div>';
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Aggregate-only backtest metrics | PnLTracker tracks per-position detail | v1.0 (2026-02-11) | All per-trade data already captured in PositionPnL |
| No trade-level backtest output | BacktestResult has equity curve + aggregate metrics | v1.1 (2026-02-12) | Need to extend BacktestResult with trades list |
| Chart.js annotation plugin for markers | Mixed chart with scatter datasets | Chart.js v4 | Built-in feature, no plugin CDN needed |

**No deprecated patterns apply.** The project stack (FastAPI, Chart.js 4, Tailwind CDN, aiosqlite, dataclasses) is current and stable.

## Open Questions

1. **Should the trade log be on the existing backtest page or a new page?**
   - What we know: The roadmap says "User can inspect individual simulated trades from backtest results." The backtest page already shows the equity curve and metrics.
   - What's unclear: Whether the page will feel too long with trade log + histogram added.
   - Recommendation: Extend the existing backtest page. The trade log, trade stats, and histogram only appear after a backtest completes (same as equity curve). Use collapsible sections (`<details>` or show/hide) if needed. This keeps trades in context with the equity curve.

2. **How to handle the `total_trades` discrepancy in `BacktestMetrics`?**
   - What we know: The existing `total_trades` counter counts opens + closes (so it is roughly 2x the number of round-trip trades). The new `TradeStats.total_trades` will count round-trips correctly.
   - What's unclear: Whether to fix the existing `BacktestMetrics.total_trades` or leave it and rely on `TradeStats` for the correct count.
   - Recommendation: Fix `BacktestMetrics.total_trades` to count round-trip trades (closed positions) instead of trade events. This prevents user confusion. The existing count was only displayed in the metrics cards, which will now get the correct number from `TradeStats`.

3. **Histogram bin count**
   - What we know: The P&L distribution histogram needs bins. Too few bins (3-5) lose detail; too many (50+) are sparse for backtests with 10-20 trades.
   - What's unclear: What default bin count works well.
   - Recommendation: Use `min(10, max(3, len(trades) // 3))` as a dynamic bin count. This adapts to the number of trades while staying in a reasonable 3-10 range.

4. **Trade marker density on equity curve**
   - What we know: A backtest with many trades (50+) could make the equity curve cluttered with markers.
   - What's unclear: Whether to limit displayed markers or show all.
   - Recommendation: Show all markers. With `pointRadius: 6` and the equity curve typically spanning 30-90 days, markers won't overlap badly for realistic trade counts (5-30 trades). If density is an issue, toggle marker visibility via a checkbox (future enhancement).

## Sources

### Primary (HIGH confidence)
- **Codebase analysis** - All patterns and code examples come from direct reading of the project source files:
  - `src/bot/backtest/engine.py` - BacktestEngine run loop, _compute_metrics(), PnLTracker usage
  - `src/bot/backtest/models.py` - BacktestConfig, BacktestMetrics, BacktestResult, EquityPoint, SweepResult
  - `src/bot/backtest/runner.py` - run_backtest(), run_comparison() entry points
  - `src/bot/backtest/sweep.py` - ParameterSweep memory management pattern
  - `src/bot/pnl/tracker.py` - PnLTracker, PositionPnL, FundingPayment dataclasses
  - `src/bot/pnl/fee_calculator.py` - FeeCalculator and funding payment calculation
  - `src/bot/analytics/metrics.py` - _net_return(), sharpe_ratio(), win_rate()
  - `src/bot/models.py` - Position, OrderResult dataclasses
  - `src/bot/dashboard/routes/api.py` - Backtest API endpoints, _decimal_to_str()
  - `src/bot/dashboard/routes/pages.py` - Page route patterns
  - `src/bot/dashboard/templates/backtest.html` - Backtest page JS patterns
  - `src/bot/dashboard/templates/partials/equity_curve.html` - Chart.js rendering patterns
  - `src/bot/dashboard/templates/partials/param_heatmap.html` - HTML table rendering patterns
  - `tests/test_analytics.py` - Test patterns for Decimal analytics with _make_position helper

### Secondary (MEDIUM confidence)
- [Chart.js Mixed Chart Types](https://www.chartjs.org/docs/latest/charts/mixed.html) - Mixed line+scatter datasets on same chart
- [Chart.js Bar Chart](https://www.chartjs.org/docs/latest/charts/bar.html) - Bar chart configuration for histogram
- [Chart.js Point Styling](https://www.chartjs.org/docs/latest/samples/line/point-styling.html) - Point styles (triangle, circle) and rotation
- [Chart.js Scatter Chart](https://www.chartjs.org/docs/latest/charts/scatter.html) - Scatter dataset configuration
- [chartjs-plugin-annotation](https://www.chartjs.org/chartjs-plugin-annotation/latest/guide/) - Evaluated but not recommended (CDN budget constraint)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Everything is already in the project. Zero new dependencies needed.
- Architecture: HIGH - All patterns directly derived from existing codebase code. `PositionPnL` already contains all the raw data needed for trade-level detail.
- Pitfalls: HIGH - Pitfalls identified from direct analysis of data model field types (seconds vs milliseconds), counter semantics (total_trades double-counting), and memory management patterns (sweep trade list retention).
- Trade data extraction: HIGH - Verified by reading `PnLTracker.record_open()`, `record_close()`, and `record_funding_payment()` to confirm all fields are captured.
- Chart.js mixed chart: MEDIUM - Based on Chart.js documentation and search results; not yet tested in this specific codebase context.

**Research date:** 2026-02-13
**Valid until:** 2026-03-15 (stable -- no moving parts; all dependencies already pinned)
