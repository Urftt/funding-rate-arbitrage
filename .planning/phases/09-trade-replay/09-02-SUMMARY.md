---
phase: 09-trade-replay
plan: 02
subsystem: ui
tags: [jinja2, tailwind, javascript, trade-log, expandable-rows, metric-cards]

# Dependency graph
requires:
  - phase: 09-trade-replay
    provides: BacktestTrade.to_dict() trades and TradeStats.to_dict() trade_stats in API response
  - phase: 06-backtest-engine
    provides: backtest.html IIFE pattern, metricCard/fmtDollar/fmtPercent/fmtNum helpers
affects: [09-trade-replay, dashboard-ui]

# Tech tracking
tech-stack:
  added: []
  patterns: [two-row expandable table (summary + hidden detail), onclick toggle sibling row]

key-files:
  created:
    - src/bot/dashboard/templates/partials/trade_log.html
    - src/bot/dashboard/templates/partials/trade_stats.html
  modified:
    - src/bot/dashboard/templates/backtest.html

key-decisions:
  - "Used onclick toggle on nextElementSibling for expandable rows (no external JS library needed)"
  - "Avg loss displayed with negative sign prefix (-$) since server provides absolute value magnitude"
  - "Trade log and stats hidden in compare/sweep modes; only shown for single backtests"

patterns-established:
  - "Two-row expandable table: summary row with onclick toggling hidden detail row via nextElementSibling"
  - "fmtDate helper for millisecond timestamp formatting in trade log"

# Metrics
duration: 2min
completed: 2026-02-13
---

# Phase 9 Plan 2: Trade Log & Stats UI Summary

**Expandable trade log table and win/loss summary statistics cards for single backtest results using two-row toggle pattern and metricCard helpers**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-13T10:48:25Z
- **Completed:** 2026-02-13T10:51:11Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Trade log table with expandable detail rows showing per-trade entry/exit times, P&L, fees, funding, prices, and quantity
- Trade statistics card with 8 metric cards: total trades, win rate, winning/losing count, avg win, avg loss, best trade, worst trade, avg holding periods
- Empty trade state shows "No trades in this backtest" message
- Trade sections properly hidden for compare and sweep modes, visible only for single backtests
- All styling consistent with existing dark theme (bg-dash-card, border-dash-border, text-gray-400)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create trade log and trade stats template partials** - `6401274` (feat)
2. **Task 2: Wire trade log and stats into backtest.html JavaScript** - `50086db` (feat)

## Files Created/Modified
- `src/bot/dashboard/templates/partials/trade_log.html` - Expandable trade log table with thead, empty tbody#trade-log-body, and empty state message
- `src/bot/dashboard/templates/partials/trade_stats.html` - Grid container for trade statistics metric cards
- `src/bot/dashboard/templates/backtest.html` - Added displayTradeLog, displayTradeStats, fmtDate functions; includes partials; updated reset/compare/sweep to manage trade sections

## Decisions Made
- Used inline `onclick="this.nextElementSibling.classList.toggle('hidden')"` for expandable row toggle -- lightweight, no external dependency
- Avg loss displayed with `-$` prefix because server sends absolute value magnitude (positive number)
- Trade log shows both summary row (trade number, dates, P&L, periods, win/loss badge) and hidden detail row (symbol, prices, quantity, funding, fees)
- fmtDate uses `toLocaleDateString` + `toLocaleTimeString` for browser-locale-aware formatting

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Trade log and stats UI complete, rendering data from BacktestResult.to_dict() response
- Ready for 09-03 (Chart.js trade markers on equity curve and P&L histogram chart)
- All 296 existing tests continue to pass

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 09-trade-replay*
*Completed: 2026-02-13*
