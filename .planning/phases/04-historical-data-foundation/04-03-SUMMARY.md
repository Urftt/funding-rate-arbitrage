---
phase: 04-historical-data-foundation
plan: 03
subsystem: orchestrator, dashboard, data-pipeline
tags: [sqlite, asyncio, jinja2, htmx, websocket, historical-data, progress-callback]

# Dependency graph
requires:
  - phase: 04-historical-data-foundation
    plan: 02
    provides: "HistoricalDataStore, HistoricalDataFetcher with ensure_data_ready and incremental_update"
  - phase: 03-dashboard-analytics
    plan: 05
    provides: "FastAPI lifespan, uvicorn integration, dashboard update loop, base.html template"
provides:
  - "Orchestrator integration: _ensure_historical_data() blocks startup, incremental_update() runs per cycle"
  - "Dashboard Data Status widget with 4 states (disabled, starting, fetching, normal)"
  - "/api/data-status JSON endpoint for historical data status and fetch progress"
  - "WebSocket real-time data status panel updates via OOB swap"
  - "Complete end-to-end historical data pipeline: fetch on startup, persist in SQLite, resume on restart"
affects: [05-signal-analysis, 06-backtest-engine, 07-dynamic-sizing]

# Tech tracking
tech-stack:
  added: []
  patterns: [progress-callback-for-dashboard, optional-feature-via-none-injection, oob-swap-widget]

key-files:
  created:
    - src/bot/dashboard/templates/partials/data_status.html
  modified:
    - src/bot/orchestrator.py
    - src/bot/main.py
    - src/bot/dashboard/routes/api.py
    - src/bot/dashboard/update_loop.py
    - src/bot/dashboard/routes/pages.py
    - src/bot/dashboard/app.py
    - src/bot/dashboard/templates/index.html

key-decisions:
  - "Orchestrator waits up to 30s for funding monitor first poll before historical fetch (race condition fix)"
  - "Dashboard mode delegates SIGINT/SIGTERM to uvicorn for clean shutdown instead of custom signal handlers"
  - "KeyboardInterrupt suppressed in main() entry point for clean Ctrl+C experience"
  - "Data status widget uses 4-state Jinja2 conditional: disabled, starting, fetching progress, normal display"

patterns-established:
  - "Progress callback pattern: async callback passed to long-running operations, updates orchestrator state for dashboard polling"
  - "OOB swap widget pattern: new dashboard panels added as partials with hx-swap-oob, rendered in update loop"
  - "Optional v1.1 feature guard: `if component is None: return` at top of methods"

# Metrics
duration: 12min
completed: 2026-02-12
---

# Phase 4 Plan 3: Pipeline Integration & Dashboard Widget Summary

**Orchestrator wired to block on historical data startup, incremental update per cycle, and live Data Status dashboard widget with 4-state progress display**

## Performance

- **Duration:** ~12 min (including checkpoint verification)
- **Started:** 2026-02-12T11:50:00Z
- **Completed:** 2026-02-12T19:50:50Z
- **Tasks:** 3 (2 auto + 1 checkpoint:human-verify)
- **Files modified:** 8

## Accomplishments
- Wired HistoricalDataFetcher and HistoricalDataStore into Orchestrator with `| None = None` optional injection pattern
- Orchestrator blocks on `_ensure_historical_data()` during `start()`, then runs `incremental_update()` on each scan cycle
- Dashboard Data Status widget shows 4 states: disabled, starting, fetching progress (X/Y pairs with progress bar), normal (pairs tracked, total records, date range, last sync)
- Added `/api/data-status` JSON endpoint and WebSocket OOB swap updates
- End-to-end verified: 20 pairs tracked, 50,919 total records, Feb 2025 - Feb 2026 date range, instant resume on restart

## Task Commits

Each task was committed atomically:

1. **Task 1: Orchestrator integration and main.py wiring** - `89e2397` (feat)
2. **Task 2: Dashboard data status widget** - `10c4b8f` (feat)
3. **Task 3: Verify data pipeline end-to-end** - checkpoint:human-verify (approved)

**Post-checkpoint fixes:** `4fa2661` (fix) - timing race condition and clean shutdown

## Files Created/Modified
- `src/bot/orchestrator.py` - Added optional data_fetcher/data_store/historical_settings constructor params, _ensure_historical_data() with 30s funding rate wait, incremental_update() in cycle step 0.5, data_fetch_progress property
- `src/bot/main.py` - Wired HistoricalDatabase/HistoricalDataStore/HistoricalDataFetcher creation, lifespan connect/close, app.state.data_store, clean shutdown signal handling, KeyboardInterrupt suppression
- `src/bot/dashboard/templates/partials/data_status.html` - New 4-state data status widget (disabled, starting, fetching, normal) with Tailwind styling and progress bar
- `src/bot/dashboard/routes/api.py` - Added /api/data-status endpoint returning status dict with optional fetch_progress
- `src/bot/dashboard/update_loop.py` - Added data status panel to WebSocket broadcast loop with OOB swap
- `src/bot/dashboard/routes/pages.py` - Added data_status and fetch_progress context to initial page render
- `src/bot/dashboard/app.py` - Added timestamp_to_date and time_ago Jinja2 template filters
- `src/bot/dashboard/templates/index.html` - Updated top row grid from 3-col to 4-col, added data-status-panel div

## Decisions Made
- Orchestrator waits up to 30s (polling every 0.5s) for funding monitor's first poll before proceeding with historical data fetch -- prevents race condition where start() calls _ensure_historical_data before any rates are available
- Dashboard mode (uvicorn) only registers SIGUSR1 signal handler; SIGINT/SIGTERM are left to uvicorn which triggers lifespan cleanup for clean shutdown
- KeyboardInterrupt caught in main() entry point to suppress traceback on Ctrl+C
- Data status widget rendered with 4 Jinja2 conditional states rather than JavaScript state machine, keeping the HTMX-first approach consistent

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed race condition in _ensure_historical_data timing**
- **Found during:** Task 3 checkpoint verification (by orchestrator agent)
- **Issue:** _ensure_historical_data() called immediately after funding_monitor.start(), but the monitor's first poll is async and may not have completed yet. First invocation would log "no rates" and skip the fetch entirely.
- **Fix:** Added polling loop that waits up to 30s (60 iterations x 0.5s sleep) for get_all_funding_rates() to return data before proceeding
- **Files modified:** src/bot/orchestrator.py
- **Verification:** Bot starts and waits for rates, then fetches all 20 pairs successfully
- **Committed in:** 4fa2661

**2. [Rule 1 - Bug] Fixed SIGINT handler conflict in dashboard mode**
- **Found during:** Task 3 checkpoint verification (by orchestrator agent)
- **Issue:** In dashboard mode, custom SIGINT/SIGTERM handlers from _setup_signal_handlers() conflicted with uvicorn's own signal handling, preventing clean shutdown. Ctrl+C would not cleanly stop the server.
- **Fix:** Dashboard lifespan now only registers SIGUSR1 for emergency stop; SIGINT/SIGTERM are left to uvicorn which triggers lifespan cleanup -> orchestrator.stop() -> exchange close
- **Files modified:** src/bot/main.py
- **Verification:** Ctrl+C cleanly shuts down bot, orchestrator, and uvicorn without error

**3. [Rule 1 - Bug] Suppressed KeyboardInterrupt traceback in main()**
- **Found during:** Task 3 checkpoint verification (by orchestrator agent)
- **Issue:** asyncio.run() raises KeyboardInterrupt when Ctrl+C is pressed, producing an ugly traceback even though shutdown is clean
- **Fix:** Wrapped asyncio.run(run()) in try/except KeyboardInterrupt: pass
- **Files modified:** src/bot/main.py
- **Verification:** Ctrl+C exits cleanly with no traceback
- **Committed in:** 4fa2661 (same commit as fix 2)

---

**Total deviations:** 3 auto-fixed (3 bugs found during verification)
**Impact on plan:** All fixes necessary for correct operation. No scope creep. Fixes were made by the orchestrator agent during checkpoint verification before user approval.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None - no external service configuration required. Historical data feature is controlled by the existing `HISTORICAL_ENABLED` environment variable (default: true).

## Next Phase Readiness
- Phase 4 (Historical Data Foundation) is fully complete: data models, database, store, fetcher, orchestrator integration, and dashboard widget all operational
- HistoricalDataStore.get_funding_rates() and get_ohlcv_candles() ready for signal analysis (Phase 5)
- Backtest engine (Phase 6) can query historical data via the store
- Dynamic sizing (Phase 7) can use historical volatility data
- All phase success criteria met: startup block, incremental updates, dashboard visibility, SQLite persistence, optional feature flag

## Self-Check: PASSED

All 8 files verified present. All 3 commit hashes (89e2397, 10c4b8f, 4fa2661) found in git log.

---
*Phase: 04-historical-data-foundation*
*Completed: 2026-02-12*
