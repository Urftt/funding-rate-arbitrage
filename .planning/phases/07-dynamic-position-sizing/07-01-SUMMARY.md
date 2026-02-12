---
phase: 07-dynamic-position-sizing
plan: 01
subsystem: position-sizing
tags: [decimal, tdd, delegation-pattern, pydantic-settings, structlog]

# Dependency graph
requires:
  - phase: 01-core-trading-engine
    provides: "PositionSizer with exchange constraint validation (qty_step, min_qty, min_notional)"
provides:
  - "DynamicSizer class with compute_signal_budget and calculate_matching_quantity"
  - "DynamicSizingSettings with SIZING_ env prefix (enabled, min/max allocation fraction, portfolio cap)"
affects: [07-02-integration, orchestrator, backtest-engine]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Delegation pattern: DynamicSizer wraps PositionSizer", "Linear score-to-fraction interpolation for conviction sizing"]

key-files:
  created:
    - src/bot/position/dynamic_sizer.py
    - tests/test_position/test_dynamic_sizer.py
  modified:
    - src/bot/config.py

key-decisions:
  - "DynamicSizingSettings does NOT duplicate max_position_size_usd -- reads from TradingSettings via constructor injection"
  - "Linear interpolation for score-to-fraction mapping (simplest, configurable, backtestable)"
  - "No refactor commit needed -- implementation was clean from GREEN phase"

patterns-established:
  - "Delegation pattern: DynamicSizer.calculate_matching_quantity delegates to PositionSizer.calculate_matching_quantity"
  - "Budget computation separated from exchange constraint validation (compute_signal_budget vs calculate_matching_quantity)"

# Metrics
duration: 3min
completed: 2026-02-12
---

# Phase 7 Plan 1: DynamicSizer Core Summary

**DynamicSizer with linear signal-conviction scaling, portfolio exposure cap, and PositionSizer delegation via TDD**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-12T21:40:39Z
- **Completed:** 2026-02-12T21:44:17Z
- **Tasks:** 7 (config, tests, stub, RED verify, implement, GREEN verify, refactor review)
- **Files modified:** 3

## Accomplishments
- DynamicSizingSettings added to config.py with 4 fields (enabled, min_allocation_fraction, max_allocation_fraction, max_portfolio_exposure) and SIZING_ env prefix
- DynamicSizer class with compute_signal_budget (linear score-to-fraction mapping + portfolio cap) and calculate_matching_quantity (delegation to PositionSizer)
- 11 tests proving SIZE-01 (strong signal > weak signal), SIZE-02 (None at portfolio cap), SIZE-03 (delegates to PositionSizer)
- Full TDD cycle: RED (11 failures) -> GREEN (11 passes) -> REFACTOR (no changes needed)
- Zero regressions: 286/286 tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: DynamicSizingSettings config** - `2324056` (feat)
2. **Tasks 2-4: RED phase (tests + stub)** - `92b2361` (test)
3. **Tasks 5-6: GREEN phase (implementation)** - `11b175b` (feat)

_No refactor commit -- implementation was clean from GREEN phase._

## Files Created/Modified
- `src/bot/config.py` - Added DynamicSizingSettings class with SIZING_ prefix, added to AppSettings
- `src/bot/position/dynamic_sizer.py` - DynamicSizer class: compute_signal_budget + calculate_matching_quantity
- `tests/test_position/test_dynamic_sizer.py` - 11 tests across TestSignalBudget, TestPortfolioCap, TestDelegation

## Decisions Made
- DynamicSizingSettings does NOT duplicate max_position_size_usd (avoids configuration overlap pitfall from research). Instead, max_position_size_usd is injected into DynamicSizer constructor from TradingSettings.
- Linear interpolation: `fraction = min_frac + (max_frac - min_frac) * score`. Simple, transparent, configurable for parameter sweeps.
- No refactor commit needed: code was clean from GREEN phase (proper docstrings, type hints, structlog logging all included in initial implementation).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- DynamicSizer class ready for integration into orchestrator (plan 07-02)
- DynamicSizingSettings ready for injection via AppSettings.sizing
- PositionSizer delegation pattern established and tested
- Backtest engine integration will need to create DynamicSizer when composite mode + dynamic sizing enabled

## Self-Check: PASSED

All files exist, all commits verified, all tests passing (286/286).

---
*Phase: 07-dynamic-position-sizing*
*Completed: 2026-02-12*
