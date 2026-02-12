---
phase: 06-backtest-engine
plan: 02
subsystem: backtest
tags: [backtest, engine, replay, event-driven, pnl-tracking, strategy, equity-curve]

# Dependency graph
requires:
  - phase: 06-backtest-engine
    plan: 01
    provides: "BacktestConfig, BacktestExecutor, BacktestDataStoreWrapper, PnLTracker time_fn injection"
  - phase: 01-core-trading-engine
    provides: "PositionManager, FeeCalculator, PnLTracker, PositionSizer, DeltaValidator"
  - phase: 05-signal-analysis
    provides: "SignalEngine for composite strategy mode"
  - phase: 04-historical-data
    provides: "HistoricalDataStore, HistoricalDatabase, HistoricalFundingRate, OHLCVCandle"
provides:
  - "BacktestEngine with async run() for event-driven historical replay"
  - "run_backtest() entry point wiring database, store, and engine"
  - "run_comparison() for v1.0 vs v1.1 side-by-side strategy comparison (BKTS-05)"
  - "run_backtest_cli() convenience function with date-string parsing"
affects: [06-03-PLAN, 06-04-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Event-driven replay: walk funding rate timestamps chronologically, construct data snapshots, feed through strategy pipeline"
    - "Component composition: engine creates all internal components (executor, data wrapper, PnLTracker, PositionManager) and wires them together"
    - "Graceful empty-data: return zero-metric BacktestResult when no historical data available"

key-files:
  created:
    - src/bot/backtest/engine.py
    - src/bot/backtest/runner.py
  modified:
    - src/bot/backtest/__init__.py

key-decisions:
  - "Engine creates its own component instances rather than accepting pre-built ones -- simplifies API and ensures correct wiring"
  - "Simple strategy uses inline threshold comparison (not OpportunityRanker) since backtesting single-symbol"
  - "Generous InstrumentInfo for backtest mode (no exchange constraint validation needed)"
  - "Composite mode falls back to simple strategy on error for resilience"

patterns-established:
  - "Backtest component composition: BacktestEngine constructor creates executor, data wrapper, PnLTracker, PositionManager, SignalEngine internally"
  - "Strategy branching: _simple_decision() vs _composite_decision() methods with fallback"
  - "Runner pattern: async context manager for database lifecycle, sequential execution for comparison"

# Metrics
duration: 4min
completed: 2026-02-12
---

# Phase 06 Plan 02: Core Backtest Engine Summary

**Event-driven BacktestEngine replaying historical funding rates through production strategy pipeline with run_backtest() and run_comparison() entry points**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-12T21:06:35Z
- **Completed:** 2026-02-12T21:10:47Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- BacktestEngine with async run() method that walks through historical funding rate timestamps chronologically, constructs data snapshots at each step, makes strategy decisions, simulates funding settlements, and returns BacktestResult with equity curve and metrics
- Full production code reuse (BKTS-02): FeeCalculator, PnLTracker, PositionManager, PositionSizer, DeltaValidator all used as-is via Executor ABC swap
- Both simple threshold and composite signal strategy modes supported (BKTS-05) with automatic fallback
- Three runner functions: run_backtest() for single execution, run_comparison() for v1.0 vs v1.1 side-by-side, run_backtest_cli() for date-string convenience

## Task Commits

Each task was committed atomically:

1. **Task 1: Create BacktestEngine with event-driven replay loop** - `2d1660e` (feat)
2. **Task 2: Create run_backtest() runner and validate end-to-end** - `562d19b` (feat)

## Files Created/Modified
- `src/bot/backtest/engine.py` - BacktestEngine class with async run(), simple/composite decision methods, metrics computation, and empty-result handling
- `src/bot/backtest/runner.py` - run_backtest(), run_comparison(), run_backtest_cli() entry points with database lifecycle management
- `src/bot/backtest/__init__.py` - Updated exports to include BacktestEngine, run_backtest, run_comparison, run_backtest_cli

## Decisions Made
- Engine creates its own component instances internally rather than accepting pre-built ones -- simplifies the API and ensures correct wiring between BacktestExecutor, BacktestDataStoreWrapper, PnLTracker, and PositionManager
- Simple strategy uses direct threshold comparison inline (not OpportunityRanker) since backtest operates on a single symbol and does not need multi-pair ranking
- Generous InstrumentInfo with very low minimums and high maximums for backtest mode -- exchange constraint validation is not meaningful in simulation
- Composite mode includes try/except with fallback to simple strategy for resilience against signal computation errors

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- BacktestEngine is ready for Plan 03's parameter sweep to call run_backtest() in loops with varying configurations
- run_comparison() provides the foundation for Plan 04's reporting to compare strategies
- All 275 existing tests pass (backward-compatible additions only)
- Empty-data handling ensures graceful behavior when database lacks data for requested symbol/date range

## Self-Check: PASSED

All 3 files verified present. Both task commits (2d1660e, 562d19b) confirmed in git log.

---
*Phase: 06-backtest-engine*
*Completed: 2026-02-12*
