---
phase: 01-core-trading-engine
plan: 03
subsystem: pnl
tags: [decimal, tdd, fee-calculator, position-sizing, bybit-fees]

# Dependency graph
requires:
  - phase: 01-01
    provides: "FeeSettings, TradingSettings config; Decimal-for-money pattern"
provides:
  - "FeeCalculator: entry/exit/round-trip fee computation, break-even rate, profitability check, funding payment calc"
  - "PositionSizer: quantity calculation with exchange constraints (min_qty, qty_step, min_notional, max_position_size_usd)"
  - "InstrumentInfo dataclass and round_to_step utility in exchange/types.py"
affects: [01-04, 01-05, orchestrator, execution-layer]

# Tech tracking
tech-stack:
  added: []
  patterns: [tdd-red-green, decimal-division, round-to-step-down, coarser-step-matching]

key-files:
  created:
    - src/bot/pnl/fee_calculator.py
    - src/bot/position/sizing.py
    - src/bot/exchange/types.py
    - tests/test_pnl/__init__.py
    - tests/test_pnl/test_fee_calculator.py
    - tests/test_position/__init__.py
    - tests/test_position/test_sizing.py
  modified: []

key-decisions:
  - "FeeCalculator.is_profitable uses same entry_price for estimated exit fees (conservative approximation)"
  - "PositionSizer.calculate_matching_quantity uses max(spot_step, perp_step) for cross-leg alignment"
  - "validate_matching_quantity uses 2% relative tolerance (matching delta_drift_tolerance from TradingSettings)"

patterns-established:
  - "TDD cycle: RED (failing tests) -> GREEN (minimal implementation) -> commit each phase"
  - "round_to_step always rounds DOWN using integer division to prevent exceeding limits"
  - "InstrumentInfo as shared exchange constraint type used by position sizing"
  - "Funding payment sign: positive = income, negative = expense (Bybit convention encoded)"

# Metrics
duration: 5min
completed: 2026-02-11
---

# Phase 1 Plan 03: Fee Calculator and Position Sizing Summary

**Decimal-precision fee calculator with Bybit convention funding payments, and position sizer with exchange constraint validation (min_qty, qty_step, min_notional)**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-11T20:00:03Z
- **Completed:** 2026-02-11T20:04:51Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- FeeCalculator computing entry/exit/round-trip fees, break-even funding rate, profitability check, and funding payments -- all Decimal, verified at 0.31% round-trip matching research numbers
- PositionSizer calculating max valid quantities respecting config limits, balance, min_qty, qty_step, and min_notional with always-down rounding
- calculate_matching_quantity ensuring both spot and perp legs use identical base quantity via coarser step alignment
- Funding payment calculation correctly encoding Bybit convention: positive rate + short position = income (Pitfall #1 from research)
- 26 passing tests covering all numerical edge cases with exact Decimal assertions

## Task Commits

Each task was committed atomically (TDD: test + implementation):

1. **Task 1 RED: Fee calculator failing tests** - `68bcada` (test)
2. **Task 1 GREEN: FeeCalculator implementation** - `aa78520` (feat)
3. **Task 2 RED: Position sizer failing tests** - `4e9dac0` (test)
4. **Task 2 GREEN: PositionSizer implementation** - `4dbfc0e` (feat)

## Files Created/Modified
- `src/bot/exchange/types.py` - InstrumentInfo dataclass (exchange constraints) and round_to_step utility
- `src/bot/pnl/fee_calculator.py` - FeeCalculator: entry/exit/round-trip fees, break-even rate, profitability check, funding payments
- `src/bot/position/sizing.py` - PositionSizer: calculate_quantity, calculate_matching_quantity, validate_matching_quantity
- `tests/test_pnl/__init__.py` - Test package init
- `tests/test_pnl/test_fee_calculator.py` - 12 tests covering all fee calculator methods with exact Decimal values
- `tests/test_position/__init__.py` - Test package init
- `tests/test_position/test_sizing.py` - 14 tests covering sizing, constraints, step rounding, and matching validation

## Decisions Made
- **Conservative profitability estimate:** `is_profitable` uses the same entry_price for estimated exit fees rather than predicting future prices. This ensures the profitability check is conservative (actual fees may be slightly different if prices move).
- **Coarser step for matching:** `calculate_matching_quantity` uses `max(spot_step, perp_step)` to ensure the resulting quantity is valid on both instruments. This is the simplest correct approach.
- **2% tolerance for fill validation:** `validate_matching_quantity` defaults to 2% relative drift tolerance, matching the `delta_drift_tolerance` in TradingSettings.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created src/bot/exchange/types.py with InstrumentInfo and round_to_step**
- **Found during:** Task 1 (fee calculator test setup)
- **Issue:** Plan references `InstrumentInfo` from `exchange/types.py` but this file did not exist (01-01 only created package stubs)
- **Fix:** Created types.py with InstrumentInfo dataclass and round_to_step utility function
- **Files modified:** src/bot/exchange/types.py
- **Verification:** Both FeeCalculator and PositionSizer import and use it successfully
- **Committed in:** 68bcada (part of Task 1 RED commit)

---

**Total deviations:** 1 auto-fixed (1 blocking dependency)
**Impact on plan:** Necessary pre-requisite. InstrumentInfo was referenced in the plan's key_links but the file didn't exist. No scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- FeeCalculator ready for use by orchestrator (profitability gating) and PnL tracker
- PositionSizer ready for use by execution layer (order quantity calculation)
- InstrumentInfo ready for exchange client to populate from `/v5/market/instruments-info`
- All tests pass, zero float usage confirmed in both modules

## Self-Check: PASSED

- All 8 created files verified present on disk
- All 4 task commits verified in git log (68bcada, aa78520, 4e9dac0, 4dbfc0e)
- 26 tests collected and passing
- Zero float() calls in fee_calculator.py and sizing.py
- Round-trip fee verified at 0.31% matching research numbers

---
*Phase: 01-core-trading-engine*
*Completed: 2026-02-11*
