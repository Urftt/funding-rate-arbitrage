---
phase: 01-core-trading-engine
plan: 05
subsystem: integration
tags: [pnl-tracking, funding-simulation, orchestrator, bot-loop, papr-02, papr-03, delta-neutral]

# Dependency graph
requires:
  - phase: 01-01
    provides: "Models (Position, FundingRateData, OrderResult), config (AppSettings), structlog logging"
  - phase: 01-02
    provides: "ExchangeClient, TickerService price cache, FundingMonitor, BybitClient"
  - phase: 01-03
    provides: "FeeCalculator with funding payment calculation, PositionSizer"
  - phase: 01-04
    provides: "Executor ABC, PaperExecutor, LiveExecutor, PositionManager, DeltaValidator"
provides:
  - "PnLTracker: per-position P&L tracking with funding payment history (PAPR-03)"
  - "Funding settlement simulation on 8h schedule for paper trading"
  - "Orchestrator: main bot loop integrating all Phase 1 components"
  - "main.py: full dependency wiring with SIGINT/SIGTERM graceful shutdown"
  - "PAPR-02 verified: parameterized test proves identical orchestrator behavior with both executor types"
  - "Complete paper trading bot: start -> monitor rates -> open/close positions -> track P&L"
affects: [phase-2-api, phase-2-autonomous-trading, phase-2-monitoring]

# Tech tracking
tech-stack:
  added: []
  patterns: [funding-settlement-simulation, orchestrator-state-machine, dependency-injection-wiring, signal-handler-graceful-shutdown]

key-files:
  created:
    - src/bot/pnl/tracker.py
    - src/bot/orchestrator.py
    - tests/test_pnl/test_tracker.py
    - tests/test_orchestrator.py
  modified:
    - src/bot/main.py

key-decisions:
  - "PnLTracker.get_total_pnl takes unrealized_pnl as parameter rather than async-fetching prices, enabling synchronous P&L checks in the orchestrator loop"
  - "Orchestrator Phase 1 is monitor-only: logs opportunities and P&L but does NOT auto-open positions (Phase 2 adds autonomous trading)"
  - "Funding settlement uses time.time() elapsed check (not exchange timestamps) for paper trading simplicity"

patterns-established:
  - "Orchestrator dependency injection: all components injected via constructor, no global state"
  - "Funding settlement simulation: PnLTracker.simulate_funding_settlement called on 8h schedule by orchestrator"
  - "Signal handler pattern: asyncio loop.add_signal_handler with create_task(orchestrator.stop())"
  - "PAPR-02 verification: parameterized pytest runs identical scenario with both executor types"

# Metrics
duration: 5min
completed: 2026-02-11
---

# Phase 1 Plan 05: P&L Tracking and Orchestrator Integration Summary

**P&L tracker with per-position funding payment simulation and orchestrator wiring all Phase 1 components into a complete paper trading bot loop**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-11T20:16:50Z
- **Completed:** 2026-02-11T20:22:41Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- PnLTracker with per-position P&L tracking: entry/exit fees, cumulative funding payments, unrealized P&L, net P&L breakdown, and portfolio summary aggregation (PAPR-03)
- Funding settlement simulation on 8h schedule for paper trading, processing all open positions with current funding rates from the monitor
- Orchestrator integrating all Phase 1 components (settings, exchange, funding monitor, ticker service, position manager, P&L tracker, delta validator, fee calculator) into a single monitoring loop
- main.py with complete dependency wiring, paper/live executor selection, and SIGINT/SIGTERM graceful shutdown
- PAPR-02 verified end-to-end: parameterized test proves Orchestrator and PositionManager produce identical behavior with PaperExecutor and LiveExecutor -- no executor type branching in either class
- 135 total tests passing across all Phase 1 modules (31 new: 18 P&L tracker + 13 orchestrator)

## Task Commits

Each task was committed atomically:

1. **Task 1: P&L tracker with funding fee simulation** - `5cfdb90` (feat)
2. **Task 2: Orchestrator and main entry point** - `ab91657` (feat)

## Files Created/Modified
- `src/bot/pnl/tracker.py` - PnLTracker: per-position P&L with funding payments, settlement simulation, portfolio summary
- `src/bot/orchestrator.py` - Orchestrator: main bot loop, funding settlement scheduling, manual open/close convenience methods, status reporting
- `src/bot/main.py` - Updated: full dependency wiring with executor selection and signal handlers
- `tests/test_pnl/test_tracker.py` - 18 tests: record_open, funding payments, unrealized P&L, total P&L breakdown, portfolio summary, settlement simulation
- `tests/test_orchestrator.py` - 13 tests: lifecycle, funding settlement timing, open/close delegation, status, PAPR-02 parameterized verification

## Decisions Made
- **PnLTracker.get_total_pnl synchronous design:** Takes unrealized_pnl as a parameter rather than async-fetching prices internally. This allows the orchestrator's synchronous monitoring loop to call get_total_pnl without awaiting, while the caller can separately compute unrealized P&L when needed. Simpler for Phase 1 where the orchestrator just logs status.
- **Orchestrator Phase 1 is monitor-only:** Deliberately does NOT auto-open positions. It monitors funding rates, logs opportunities, tracks existing position P&L, and simulates funding settlement. Autonomous trading logic is a Phase 2 concern.
- **Funding settlement time tracking:** Uses `time.time()` elapsed check rather than exchange funding timestamps. For paper trading, this is sufficient and avoids complexity of parsing exchange settlement schedules.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 1 Core Trading Engine is COMPLETE: all 5 plans executed
- Paper trading bot can: connect to exchange, monitor funding rates, open/close delta-neutral positions, track P&L with funding settlement simulation, graceful shutdown
- Ready for Phase 2: API layer, autonomous trading logic, monitoring dashboard
- PAPR-02 (swappable executor) verified -- live mode requires only configuration change
- PAPR-03 (P&L with funding) implemented and tested

## Self-Check: PASSED

- All 5 created/modified files verified present on disk
- Commit 5cfdb90 verified in git log (Task 1)
- Commit ab91657 verified in git log (Task 2)
- All 135 tests pass (18 P&L tracker + 13 orchestrator + 104 existing)

---
*Phase: 01-core-trading-engine*
*Completed: 2026-02-11*
