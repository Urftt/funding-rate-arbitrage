---
phase: 02-multi-pair-intelligence
plan: 04
subsystem: orchestrator, integration
tags: [autonomous-trading, scan-rank-decide-execute, signal-handling, asyncio-lock, risk-integration, emergency-stop]

# Dependency graph
requires:
  - phase: 02-multi-pair-intelligence
    plan: 02
    provides: "OpportunityRanker with rank_opportunities for pair scoring"
  - phase: 02-multi-pair-intelligence
    plan: 03
    provides: "RiskManager with check_can_open/check_margin_ratio, EmergencyController with trigger"
  - phase: 01-core-trading-engine
    provides: "Orchestrator Phase 1, main.py wiring, PositionManager, PnLTracker, FundingMonitor"
provides:
  - "Autonomous scan-rank-decide-execute orchestrator loop"
  - "Automatic position open on top-ranked pairs within risk limits"
  - "Automatic position close when funding rate drops below exit threshold"
  - "Margin ratio monitoring with emergency stop on critical"
  - "Signal handlers: SIGUSR1 emergency, SIGINT/SIGTERM graceful shutdown"
  - "Full Phase 2 component wiring in main.py"
affects: [03-backtesting, 03-live-readiness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Autonomous cycle under asyncio.Lock to prevent overlapping iterations"
    - "Circular dependency resolution via set_emergency_controller post-construction"
    - "Signal-based emergency stop: SIGUSR1 triggers EmergencyController"
    - "Scan-rank-decide-execute pattern: FundingMonitor -> OpportunityRanker -> RiskManager -> PositionManager"

key-files:
  created: []
  modified:
    - src/bot/orchestrator.py
    - src/bot/main.py
    - tests/test_orchestrator.py

key-decisions:
  - "Emergency controller injected post-construction to resolve circular dependency (orchestrator needs emergency, emergency needs orchestrator.stop)"
  - "Cycle lock uses asyncio.Lock (not Semaphore) for strict mutual exclusion"
  - "Graceful stop closes all positions before setting _running=False"

patterns-established:
  - "Autonomous trading cycle: scan -> rank -> close unprofitable -> open profitable -> check margin -> log status"
  - "Signal handler pattern: loop.add_signal_handler with asyncio.create_task for async callbacks"

# Metrics
duration: 6min
completed: 2026-02-11
---

# Phase 2 Plan 4: Autonomous Orchestrator V2 & Full Phase 2 Wiring Summary

**Autonomous scan-rank-decide-execute orchestrator loop with risk-gated position management, margin monitoring, and signal-based emergency stop**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-11T21:03:36Z
- **Completed:** 2026-02-11T21:09:35Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Orchestrator rewritten from passive monitor to autonomous trading loop that scans funding rates, ranks opportunities by net yield, opens profitable positions within risk limits, and closes unprofitable ones each cycle
- Full Phase 2 component wiring in main.py: OpportunityRanker, RiskManager, EmergencyController, and signal handlers for SIGUSR1 (emergency), SIGINT/SIGTERM (graceful shutdown)
- 23 orchestrator tests covering autonomous cycle (open/close/skip), margin monitoring, graceful shutdown, cycle lock, and PAPR-02 executor swap invariants
- All 182 tests pass across the full test suite

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite Orchestrator with autonomous scan-rank-decide-execute cycle** - `e4e7fb5` (feat)
2. **Task 2: Wire Phase 2 components in main.py with signal-based emergency stop** - `cbe0fc7` (feat)

## Files Created/Modified
- `src/bot/orchestrator.py` - Autonomous cycle: _autonomous_cycle, _close_unprofitable_positions, _open_profitable_positions, _check_margin_ratio, _log_position_status; updated constructor with risk_manager/ranker/emergency_controller; cycle lock; graceful stop with position close
- `src/bot/main.py` - Wired OpportunityRanker (step 12), RiskManager (step 13), EmergencyController (step 15); SIGUSR1/SIGINT/SIGTERM signal handlers; startup risk config logging
- `tests/test_orchestrator.py` - 10 new tests for autonomous cycle (open/close/skip), margin monitoring, graceful shutdown, cycle lock, no-rates early return; updated existing fixtures for new constructor args

## Decisions Made
- Emergency controller injected via set_emergency_controller() after Orchestrator construction to resolve circular dependency (emergency needs orchestrator.stop callback, orchestrator needs emergency controller reference)
- asyncio.Lock used for cycle lock (strict mutual exclusion, not counting semaphore) to guarantee exactly zero overlapping autonomous cycles
- Graceful stop iterates all open positions and closes each before setting _running=False, with per-position error handling so one failure doesn't prevent closing others

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test for rate_unavailable requiring at least one funding rate**
- **Found during:** Task 1 (test verification)
- **Issue:** Test for "closes position when rate unavailable" had no funding rates in monitor cache, causing _autonomous_cycle to return early at SCAN step before reaching _close_unprofitable_positions
- **Fix:** Added a funding rate entry for a different symbol (SOL/USDT:USDT) so the cycle proceeds past SCAN, while the position's symbol (BTC/USDT:USDT) remains without rate data
- **Files modified:** tests/test_orchestrator.py
- **Verification:** Test passes and correctly verifies close_position is called when rate is unavailable
- **Committed in:** e4e7fb5 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug in test logic)
**Impact on plan:** Test correction needed to match autonomous cycle control flow. No scope creep.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. All risk parameters have sensible defaults via RISK_ environment variables.

## Next Phase Readiness
- Phase 2 (Multi-Pair Intelligence) is complete: all 4 plans executed
- Bot is fully autonomous: scans, ranks, opens, closes, monitors margin, handles emergencies
- Ready for Phase 3: backtesting, live deployment hardening, or monitoring dashboard

## Self-Check: PASSED

- All 3 modified files verified present on disk
- Commit e4e7fb5 (Task 1) verified in git log
- Commit cbe0fc7 (Task 2) verified in git log
- Full test suite: 182 tests pass, 0 failures

---
*Phase: 02-multi-pair-intelligence*
*Completed: 2026-02-11*
