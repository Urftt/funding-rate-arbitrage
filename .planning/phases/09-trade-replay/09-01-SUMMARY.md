---
phase: 09-trade-replay
plan: 01
subsystem: backtest
tags: [dataclasses, decimal, pnl, histogram, trade-stats, tdd]

# Dependency graph
requires:
  - phase: 06-backtest-engine
    provides: BacktestEngine, PnLTracker with PositionPnL closed positions, BacktestResult model
provides:
  - BacktestTrade dataclass with from_position_pnl factory extracting per-trade detail
  - TradeStats dataclass with from_trades factory computing win/loss statistics
  - compute_pnl_histogram function for server-side P&L distribution binning
  - Extended BacktestResult.to_dict() with trades, trade_stats, pnl_histogram keys
  - Sweep memory management for trades (only best result retains full list)
affects: [09-trade-replay, dashboard-api, backtest-ui]

# Tech tracking
tech-stack:
  added: []
  patterns: [TDD dataclass extraction, server-side histogram binning, sweep memory management for trades]

key-files:
  created:
    - tests/test_backtest_trades.py
  modified:
    - src/bot/backtest/models.py
    - src/bot/backtest/engine.py
    - src/bot/backtest/sweep.py

key-decisions:
  - "Used TYPE_CHECKING import for PositionPnL to avoid circular import between models.py and tracker.py"
  - "Fixed total_trades to count round-trip trades (closed positions) instead of open+close events (Pitfall 1)"
  - "Dynamic histogram bin count: min(10, max(3, len(trades) // 3)) adapts to trade count"
  - "avg_loss computed as absolute value (positive number representing loss magnitude)"

patterns-established:
  - "Trade extraction via from_position_pnl factory method on BacktestTrade"
  - "Sweep memory management: only best result retains trades list; all retain compact trade_stats"

# Metrics
duration: 4min
completed: 2026-02-13
---

# Phase 9 Plan 1: Trade Data Layer Summary

**BacktestTrade and TradeStats dataclasses with per-trade extraction from PnLTracker, server-side P&L histogram binning, and sweep memory management**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-13T10:41:20Z
- **Completed:** 2026-02-13T10:46:12Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- BacktestTrade dataclass extracts per-trade detail (entry/exit times, prices, funding, fees, net P&L) from existing PositionPnL data
- TradeStats computes aggregate win/loss statistics (win rate, avg win/loss, best/worst trade, avg holding periods)
- compute_pnl_histogram provides server-side binning with dynamic bin count and edge case handling (empty, all-same-value)
- BacktestResult.to_dict() now includes trades, trade_stats, and pnl_histogram in API response
- Parameter sweep memory management updated to discard trades for non-best results
- total_trades in BacktestMetrics now correctly counts round-trip trades instead of open+close events

## Task Commits

Each task was committed atomically:

1. **Task 1: Create BacktestTrade, TradeStats, and histogram models with TDD tests** - `318efd1` (feat)
2. **Task 2: Integrate trade extraction into BacktestEngine, BacktestResult, and sweep** - `5e18654` (feat)

## Files Created/Modified
- `src/bot/backtest/models.py` - Added BacktestTrade, TradeStats dataclasses, compute_pnl_histogram function, extended BacktestResult
- `src/bot/backtest/engine.py` - _compute_metrics now extracts trades and returns tuple, fixed total_trades counting
- `src/bot/backtest/sweep.py` - Memory management includes trades list (only best retains full list)
- `tests/test_backtest_trades.py` - 10 TDD tests covering trade extraction, stats, histogram, edge cases

## Decisions Made
- Used `TYPE_CHECKING` import for PositionPnL to avoid circular import between models.py and tracker.py
- Fixed total_trades to count round-trip trades (closed positions) instead of open+close events (research Pitfall 1)
- avg_loss computed as absolute value of mean of losing trade P&Ls (positive number for display)
- Dynamic histogram bin count adapts to trade count: min(10, max(3, len(trades) // 3))
- win_rate quantized to 0.001 using ROUND_HALF_UP (consistent with analytics/metrics.py)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- BacktestResult API response now contains all data needed for plans 09-02 (Trade Log UI) and 09-03 (Chart.js trade markers and histogram)
- trades, trade_stats, and pnl_histogram keys present in to_dict() output
- All 296 existing tests continue to pass

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 09-trade-replay*
*Completed: 2026-02-13*
