---
phase: 07-dynamic-position-sizing
plan: 02
subsystem: position-sizing
tags: [integration, orchestrator, backtest, dynamic-sizing, structlog]

# Dependency graph
requires:
  - phase: 07-dynamic-position-sizing
    plan: 01
    provides: "DynamicSizer class with compute_signal_budget and calculate_matching_quantity"
  - phase: 01-core-trading-engine
    provides: "Orchestrator, PositionManager, PositionSizer production components"
  - phase: 06-backtest-engine
    provides: "BacktestEngine with composite mode, BacktestConfig"
provides:
  - "DynamicSizer wired into Orchestrator composite entry flow with portfolio exposure tracking"
  - "DynamicSizer creation in main.py gated on sizing.enabled + composite mode"
  - "DynamicSizer wired into BacktestEngine for signal-adjusted position opens"
  - "BacktestConfig with dynamic sizing parameters and to_sizing_settings()"
affects: [parameter-sweep, dashboard, backtest-cli]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Optional dependency injection: DynamicSizer | None = None preserves v1.0 path", "Exposure tracking across multi-position opens within single cycle"]

key-files:
  created: []
  modified:
    - src/bot/orchestrator.py
    - src/bot/main.py
    - src/bot/backtest/engine.py
    - src/bot/backtest/models.py

key-decisions:
  - "Orchestrator breaks out of composite loop (not continue) when portfolio cap reached -- no budget means no pair can open"
  - "BacktestEngine stores _last_signal_score on self rather than changing _composite_decision return type -- simpler, minimal change"
  - "Backtest dynamic sizer uses initial_capital as max_position_size_usd (natural backtest boundary)"

patterns-established:
  - "Pre-compute exposure before loop, update after each open (no stale reads within cycle)"
  - "Gate all dynamic sizing logic on self._dynamic_sizer is not None (zero overhead when disabled)"

# Metrics
duration: 3min
completed: 2026-02-12
---

# Phase 7 Plan 2: DynamicSizer Integration Summary

**DynamicSizer wired into orchestrator composite flow, main.py component creation, and backtest engine with signal-adjusted budgets and portfolio exposure tracking**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-12T21:46:30Z
- **Completed:** 2026-02-12T21:50:23Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Orchestrator accepts optional DynamicSizer, computes signal-adjusted budget per position in composite mode, tracks and updates portfolio exposure after each successful open within the same cycle
- main.py creates DynamicSizer when sizing.enabled AND strategy_mode=="composite", injects into Orchestrator
- BacktestEngine creates DynamicSizer when composite mode + sizing_enabled, uses signal-adjusted available_balance for position opens
- BacktestConfig extended with 4 sizing fields (sizing_enabled, sizing_min/max_allocation_fraction, sizing_max_portfolio_exposure) and to_sizing_settings() method
- When dynamic sizing disabled (default), all behavior is identical to Phase 6 baseline -- 286/286 tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire DynamicSizer into orchestrator and main.py** - `af866b6` (feat)
2. **Task 2: Wire DynamicSizer into backtest engine and config** - `593e691` (feat)

## Files Created/Modified
- `src/bot/orchestrator.py` - Added dynamic_sizer parameter, _compute_current_exposure(), signal-adjusted budget in composite entry flow
- `src/bot/main.py` - Added DynamicSizer creation (step 14.7) and injection into Orchestrator
- `src/bot/backtest/engine.py` - Added DynamicSizer creation, _compute_current_exposure(), _last_signal_score tracking, signal-adjusted position opens
- `src/bot/backtest/models.py` - Added sizing fields to BacktestConfig, to_sizing_settings(), to_dict() updates

## Decisions Made
- Orchestrator uses `break` (not `continue`) when portfolio cap reached: if no budget remains, no subsequent pair can open either -- break is correct and efficient.
- BacktestEngine stores `_last_signal_score` on self and resets each `_composite_decision` call rather than changing the method return type. This avoids modifying the existing tuple[bool, bool] return contract.
- Backtest uses `config.initial_capital` as `max_position_size_usd` for DynamicSizer -- natural boundary for single-symbol backtests.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Dynamic sizing is disabled by default (sizing.enabled=False). Enable with SIZING_ENABLED=true environment variable.

## Next Phase Readiness
- Phase 7 complete: DynamicSizer fully integrated across live orchestrator and backtest engine
- All SIZE requirements met: SIZE-01 (conviction scaling), SIZE-02 (portfolio cap), SIZE-03 (PositionSizer delegation)
- v1.1 Strategy Intelligence milestone complete (phases 4-7 all done)
- 286/286 tests passing with zero regressions

## Self-Check: PASSED

All files exist, all commits verified, all must-have patterns present, all tests passing (286/286).

---
*Phase: 07-dynamic-position-sizing*
*Completed: 2026-02-12*
