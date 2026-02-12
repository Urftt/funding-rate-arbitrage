---
phase: 06-backtest-engine
plan: 01
subsystem: backtest
tags: [backtest, executor, dataclass, decimal, time-injection, look-ahead-bias]

# Dependency graph
requires:
  - phase: 01-core-trading-engine
    provides: "Executor ABC, OrderRequest/OrderResult models, FeeSettings"
  - phase: 04-historical-data
    provides: "HistoricalDataStore, HistoricalFundingRate, OHLCVCandle"
  - phase: 05-signal-analysis
    provides: "SignalSettings for composite strategy mode"
provides:
  - "BacktestConfig dataclass with with_overrides(), to_signal_settings(), to_dict()"
  - "BacktestResult, EquityPoint, BacktestMetrics, SweepResult dataclasses"
  - "BacktestExecutor implementing Executor ABC with injected prices"
  - "BacktestDataStoreWrapper preventing look-ahead bias"
  - "PnLTracker time_fn injection for simulated timestamps"
  - "BacktestSettings in config.py with BACKTEST_ env prefix"
affects: [06-02-PLAN, 06-03-PLAN, 06-04-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Executor ABC swap pattern: BacktestExecutor injects prices via set_prices() instead of TickerService"
    - "Time-bounded data wrapper: BacktestDataStoreWrapper caps all queries to prevent look-ahead bias"
    - "Time function injection: PnLTracker accepts Callable[[], float] for simulated timestamps"

key-files:
  created:
    - src/bot/backtest/__init__.py
    - src/bot/backtest/models.py
    - src/bot/backtest/executor.py
    - src/bot/backtest/data_wrapper.py
  modified:
    - src/bot/config.py
    - src/bot/pnl/tracker.py

key-decisions:
  - "BacktestExecutor uses injected prices (set_prices) rather than TickerService for full isolation"
  - "BacktestDataStoreWrapper uses min(until_ms, current_time) cap for look-ahead prevention"
  - "PnLTracker time_fn defaults to time.time for backward compatibility"

patterns-established:
  - "Price injection: BacktestExecutor.set_prices() + set_current_time() before each simulated step"
  - "Data boundary: BacktestDataStoreWrapper._cap_until() enforces time ceiling on all read queries"
  - "Time injection: Callable[[], float] parameter pattern for testable/backtest-able timestamps"

# Metrics
duration: 4min
completed: 2026-02-12
---

# Phase 06 Plan 01: Backtest Foundation Summary

**BacktestExecutor (Executor ABC swap), BacktestDataStoreWrapper (look-ahead prevention), BacktestConfig with Decimal models, and PnLTracker time injection**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-12T21:00:35Z
- **Completed:** 2026-02-12T21:04:16Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- BacktestConfig dataclass with with_overrides(), to_signal_settings(), and to_dict() methods covering both simple and composite strategy parameters
- BacktestExecutor implementing Executor ABC with price injection (set_prices/set_current_time), slippage, and fee calculation identical to PaperExecutor
- BacktestDataStoreWrapper wrapping HistoricalDataStore with automatic time-boundary capping on all read queries to prevent look-ahead bias
- PnLTracker enhanced with optional time_fn parameter (default time.time) enabling backtest to inject simulated timestamps without breaking existing callers
- BacktestSettings added to config.py with BACKTEST_ env prefix (slippage_bps, default_initial_capital, max_concurrent_positions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create backtest data models and configuration** - `edc2e2e` (feat)
2. **Task 2: Create BacktestExecutor, BacktestDataStoreWrapper, and inject time_fn** - `c818259` (feat)

## Files Created/Modified
- `src/bot/backtest/__init__.py` - Package exports for all backtest public names
- `src/bot/backtest/models.py` - BacktestConfig, BacktestResult, EquityPoint, BacktestMetrics, SweepResult dataclasses
- `src/bot/backtest/executor.py` - BacktestExecutor implementing Executor ABC with injected historical prices
- `src/bot/backtest/data_wrapper.py` - BacktestDataStoreWrapper capping queries at simulated time
- `src/bot/config.py` - Added BacktestSettings class and backtest field to AppSettings
- `src/bot/pnl/tracker.py` - Added time_fn parameter, replaced time.time() calls with self._time_fn()

## Decisions Made
- BacktestExecutor uses injected prices via set_prices() rather than TickerService -- full isolation from live market data services
- BacktestDataStoreWrapper uses min(until_ms, current_time_ms) cap strategy -- simple and correct, prevents any future data leakage
- PnLTracker time_fn defaults to time.time (not None with fallback) -- cleaner API, no conditional logic in hot paths

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All building blocks ready for Plan 02's BacktestEngine to compose:
  - BacktestExecutor can be injected into PositionManager via Executor ABC
  - BacktestDataStoreWrapper can replace HistoricalDataStore for SignalEngine
  - PnLTracker time_fn enables simulated timestamp tracking
  - BacktestConfig.to_signal_settings() bridges config to SignalEngine
- All 275 existing tests pass (backward-compatible changes)

## Self-Check: PASSED

All 7 files verified present. Both task commits (edc2e2e, c818259) confirmed in git log.

---
*Phase: 06-backtest-engine*
*Completed: 2026-02-12*
