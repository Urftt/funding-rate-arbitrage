---
phase: 02-multi-pair-intelligence
plan: 03
subsystem: risk
tags: [risk-management, margin-monitoring, emergency-stop, asyncio, retry]

# Dependency graph
requires:
  - phase: 01-core-trading-engine
    provides: "Position model, PositionManager, PnLTracker, ExchangeClient ABC"
  - phase: 02-01
    provides: "RiskSettings with per-pair/margin thresholds, simulate_paper_margin, fetch_wallet_balance_raw"
provides:
  - "RiskManager with RISK-01 per-pair size, RISK-02 max positions, RISK-05 margin monitoring"
  - "EmergencyController with RISK-03 concurrent close-all and retry"
affects: [02-04-orchestrator-v2]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sync check_can_open for pre-trade validation, async check_margin_ratio for runtime monitoring"
    - "asyncio.gather for concurrent position close with return_exceptions=True"
    - "Linear backoff retry (1*attempt seconds) for failed position closes"
    - "TYPE_CHECKING guard for circular import avoidance in risk module"

key-files:
  created:
    - src/bot/risk/emergency.py
    - tests/test_risk/__init__.py
    - tests/test_risk/test_manager.py
    - tests/test_risk/test_emergency.py
  modified:
    - src/bot/risk/manager.py

key-decisions:
  - "RiskManager accepts optional paper_margin_fn callable instead of direct PaperExecutor dependency"
  - "EmergencyController records P&L via pnl_tracker.record_close during emergency close"
  - "Linear backoff (not exponential) for emergency close retries -- simplicity in emergency path"

patterns-established:
  - "Risk checks return (bool, str) tuples for uniform allow/reject interface"
  - "Emergency controller uses triggered guard flag to prevent re-entry"

# Metrics
duration: 4min
completed: 2026-02-11
---

# Phase 2 Plan 3: Risk Manager & Emergency Controller Summary

**Comprehensive RiskManager with per-pair limits, margin monitoring, and EmergencyController with concurrent close-all and 3-retry backoff**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-11T20:57:37Z
- **Completed:** 2026-02-11T21:01:22Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Expanded RiskManager from Phase 1 stub into full pre-trade and runtime risk engine (RISK-01, RISK-02, RISK-05)
- Built EmergencyController with concurrent asyncio.gather close-all, 3-retry linear backoff, and CRITICAL logging for stuck positions
- 23 tests covering all risk check branches, margin monitoring, emergency close scenarios, and edge cases

## Task Commits

Each task was committed atomically:

1. **Task 1: Expand RiskManager with per-pair limits, max positions, and margin monitoring** - `a2349bd` (feat)
2. **Task 2: Build EmergencyController with concurrent close-all and retry** - `379eafa` (feat)

## Files Created/Modified
- `src/bot/risk/manager.py` - Expanded RiskManager: check_can_open (RISK-01, RISK-02, duplicate), check_margin_ratio (RISK-05), is_margin_critical
- `src/bot/risk/emergency.py` - EmergencyController: trigger, _close_with_retry, triggered property, reset
- `tests/test_risk/__init__.py` - Test package init
- `tests/test_risk/test_manager.py` - 14 tests for all RiskManager check scenarios
- `tests/test_risk/test_emergency.py` - 9 tests for emergency close including partial failure and retry

## Decisions Made
- RiskManager accepts optional `paper_margin_fn` callable for paper mode margin simulation rather than importing PaperExecutor directly (avoids coupling)
- EmergencyController records P&L during emergency close via pnl_tracker.record_close using filled prices from close results
- Used linear backoff `sleep(1 * (attempt + 1))` for retry simplicity in emergency path (not exponential)
- check_can_open is synchronous (pure validation), check_margin_ratio is async (exchange I/O)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed lint errors: imports from collections.abc**
- **Found during:** Task 2 (lint verification)
- **Issue:** ruff UP035 flagged `Callable` and `Awaitable` imported from `typing` instead of `collections.abc`
- **Fix:** Moved imports to `from collections.abc import Callable, Awaitable` in both manager.py and emergency.py
- **Files modified:** src/bot/risk/manager.py, src/bot/risk/emergency.py
- **Verification:** `ruff check src/bot/risk/` passes clean
- **Committed in:** 379eafa (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Trivial import fix required by project linting rules. No scope creep.

## Issues Encountered
- Pre-existing broken test `tests/test_market_data/test_opportunity_ranker.py` imports `OpportunityRanker` which does not exist yet (from plan 02-02). Not related to this plan. Excluded from regression runs.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- RiskManager and EmergencyController ready for plan 02-04 (Orchestrator V2) integration
- RiskManager.check_can_open provides the pre-trade gate; check_margin_ratio provides runtime monitoring
- EmergencyController.trigger provides the emergency stop path for margin critical and user-triggered stops

---
*Phase: 02-multi-pair-intelligence*
*Completed: 2026-02-11*
