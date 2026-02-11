---
phase: 03-dashboard-analytics
plan: 02
subsystem: api
tags: [pydantic-settings, dataclass, runtime-config, dashboard, pnl-tracker]

# Dependency graph
requires:
  - phase: 02-multi-pair-intelligence
    provides: "Orchestrator with autonomous cycle, PnLTracker, AppSettings"
provides:
  - "DashboardSettings for server config (host, port, enabled, update_interval)"
  - "RuntimeConfig mutable overlay for strategy parameter overrides"
  - "PnLTracker.get_closed_positions() for trade history (DASH-03)"
  - "PnLTracker.get_open_position_pnls() and get_all_position_pnls() for analytics"
  - "PositionPnL exit prices and perp_symbol fields"
  - "Orchestrator.restart() for dashboard start/stop (DASH-04)"
  - "Orchestrator runtime_config property and _apply_runtime_config (DASH-06)"
  - "Orchestrator.is_running property"
affects: [03-03-analytics-engine, 03-04-dashboard-routes, 03-05-websocket-updates]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RuntimeConfig dataclass overlay applied at cycle start (not BaseSettings -- mutable)"
    - "Background task restart via asyncio.create_task for non-blocking dashboard control"

key-files:
  created: []
  modified:
    - "src/bot/config.py"
    - "src/bot/pnl/tracker.py"
    - "src/bot/orchestrator.py"

key-decisions:
  - "RuntimeConfig is a dataclass (not BaseSettings) because it holds mutable runtime state"
  - "restart() creates background task so dashboard route caller does not block"
  - "stop() always closes positions (safer default for trading bot); restart() re-enters loop"

patterns-established:
  - "RuntimeConfig overlay: non-None fields override settings at cycle start"
  - "get_closed_positions/get_open_position_pnls for dashboard data queries"

# Metrics
duration: 3min
completed: 2026-02-11
---

# Phase 3 Plan 2: Data Layer Extensions Summary

**DashboardSettings, RuntimeConfig overlay, PnLTracker trade history methods, and Orchestrator restart/runtime-config for dashboard control**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-11T21:36:16Z
- **Completed:** 2026-02-11T21:39:18Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- DashboardSettings with DASHBOARD_ env prefix provides server config (host, port, enabled, update_interval)
- RuntimeConfig mutable dataclass allows dashboard to override strategy parameters without restart
- PnLTracker extended with get_closed_positions(), get_open_position_pnls(), get_all_position_pnls() for trade history and analytics
- PositionPnL gains spot_exit_price, perp_exit_price, perp_symbol fields for DASH-03 and DASH-07
- Orchestrator.restart() re-enters run loop as background task for dashboard start/stop (DASH-04)
- RuntimeConfig applied at each autonomous cycle start (DASH-06)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DashboardSettings, RuntimeConfig, and extend PnLTracker** - `8580be8` (feat)
2. **Task 2: Add orchestrator restart capability and RuntimeConfig integration** - `d362c21` (feat)

## Files Created/Modified
- `src/bot/config.py` - Added DashboardSettings (BaseSettings), RuntimeConfig (dataclass), dashboard field on AppSettings
- `src/bot/pnl/tracker.py` - Added exit price/perp_symbol fields to PositionPnL, get_closed_positions/get_open_position_pnls/get_all_position_pnls methods
- `src/bot/orchestrator.py` - Added RuntimeConfig import, _apply_runtime_config, restart, _run_loop_with_cleanup, is_running, runtime_config property

## Decisions Made
- RuntimeConfig is a dataclass (not BaseSettings) because it holds mutable runtime state that changes during execution
- restart() uses asyncio.create_task so the dashboard route handler returns immediately without blocking
- stop() always closes positions (safe default for trading); restart() simply re-enters the loop

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Data layer ready for Plan 03 (analytics engine) to consume get_all_position_pnls() and get_closed_positions()
- Dashboard routes (Plan 04) can use DashboardSettings, RuntimeConfig, and Orchestrator.restart()
- WebSocket updates (Plan 05) can use DashboardSettings.update_interval and is_running property
- All 182 existing tests pass without modification

## Self-Check: PASSED

All files found, all commits verified.

---
*Phase: 03-dashboard-analytics*
*Completed: 2026-02-11*
