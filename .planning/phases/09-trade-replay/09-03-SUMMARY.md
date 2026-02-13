---
phase: 09-trade-replay
plan: 03
subsystem: ui
tags: [chartjs, scatter, histogram, bar-chart, trade-markers, equity-curve]

# Dependency graph
requires:
  - phase: 09-trade-replay
    provides: BacktestResult.to_dict() with trades, trade_stats, pnl_histogram keys
  - phase: 06-backtest-engine
    provides: equity_curve.html renderEquityCurve, backtest.html IIFE pattern, Chart.js CDN
provides:
  - renderEquityCurve extended with optional trades parameter and scatter overlay datasets
  - renderPnlHistogram function for P&L distribution bar chart with green/red coloring
  - Trade entry markers (green triangles) and exit markers (red inverted triangles) on equity curve
  - pnl_histogram.html partial with Chart.js bar chart
  - backtest.html wiring for histogram and trade markers in single/sweep/compare modes
affects: [dashboard-ui, backtest-visualization]

# Tech tracking
tech-stack:
  added: []
  patterns: [Chart.js scatter overlay on line chart, mixed chart types (line + scatter), conditional dataset injection]

key-files:
  created:
    - src/bot/dashboard/templates/partials/pnl_histogram.html
  modified:
    - src/bot/dashboard/templates/partials/equity_curve.html
    - src/bot/dashboard/templates/backtest.html

key-decisions:
  - "Trade markers use timestamp-to-index lookup for O(1) mapping from trade times to equity curve positions"
  - "Scatter datasets conditionally added only when trades exist (graceful degradation for empty trades)"
  - "Histogram hidden in compare/sweep modes; sweep best result passes trades for equity curve markers"
  - "Tooltip callback differentiates scatter vs line datasets for contextual display"

patterns-established:
  - "Chart.js mixed chart: line base with scatter overlay using conditional dataset injection"
  - "Histogram bin color determined by parsing dollar-prefixed string labels for positive/negative"

# Metrics
duration: 2min
completed: 2026-02-13
---

# Phase 9 Plan 3: Trade Markers & P&L Histogram Summary

**Chart.js scatter overlay for trade entry/exit markers on equity curve and P&L distribution bar chart with green/red profit/loss coloring**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-13T10:53:04Z
- **Completed:** 2026-02-13T10:55:40Z
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments
- Equity curve chart now shows green upward triangle markers at trade entry points and red inverted triangle markers at exit points using Chart.js scatter datasets
- New P&L distribution histogram renders as a bar chart with green bars for profitable bins and red bars for losing bins
- Timestamp-to-index lookup enables O(1) mapping from trade entry/exit times to equity curve x-axis positions
- Both visualizations handle edge cases gracefully: no trades produces no markers, empty histogram data hides the section
- Charts properly destroyed and recreated on new backtest runs via existing window._chartName pattern
- Histogram and trade markers correctly hidden in compare and sweep modes

## Task Commits

Each task was committed atomically:

1. **Task 1: Add trade markers to equity curve and create P&L histogram** - `6c6c38e` (feat)

## Files Created/Modified
- `src/bot/dashboard/templates/partials/equity_curve.html` - Extended renderEquityCurve with trades parameter, scatter datasets for entry/exit markers, enhanced tooltip callback
- `src/bot/dashboard/templates/partials/pnl_histogram.html` - New partial with renderPnlHistogram function for bar chart with green/red bin coloring
- `src/bot/dashboard/templates/backtest.html` - Added pnl_histogram include, pnlHistSection DOM ref, wired histogram render into displaySingleResult, hide in compare/sweep/reset

## Decisions Made
- Trade markers use timestamp-to-index lookup (`tsToIndex`) for O(1) mapping -- entry/exit timestamps match equity curve timestamps exactly since both are recorded at funding rate timestamps
- Scatter datasets conditionally added only when entry/exit points array is non-empty (no empty legend entries)
- Tooltip callback checks `context.dataset.type === 'scatter'` to show "Entry at $X" vs "Equity: $X" format
- Sweep best result passes trades array for equity curve markers (`sorted[0].result.trades || []`)
- Histogram bin color parsing uses `parseFloat(bin.replace('$', ''))` to determine positive/negative from server-formatted labels

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Trade replay feature (TRPL-01 through TRPL-05) is now complete across all 3 plans
- Phase 09 fully delivers: trade data layer, trade log/stats UI, and chart visualizations
- All 296 existing tests continue to pass

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 09-trade-replay*
*Completed: 2026-02-13*
