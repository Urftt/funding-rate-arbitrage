---
phase: 03-dashboard-analytics
plan: 04
subsystem: dashboard
tags: [fastapi, jinja2, htmx, tailwind, websocket, routes, templates, oob-swap]

# Dependency graph
requires:
  - phase: 03-dashboard-analytics
    provides: "App factory, WebSocket hub, base template (Plan 01); DashboardSettings, RuntimeConfig, PnLTracker extensions (Plan 02); Analytics functions (Plan 03)"
provides:
  - "Page route GET / serving full dashboard with all 7 DASH panels"
  - "JSON API routes: /api/positions, /api/funding-rates, /api/trade-history, /api/status, /api/balance, /api/analytics"
  - "Action routes: POST /actions/bot/stop, /actions/bot/start, /actions/config"
  - "8 Jinja2 templates: index.html + 7 partials with unique OOB-swap IDs"
  - "dashboard_update_loop() for periodic WebSocket broadcast of rendered partials"
affects: [03-05-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "OOB swap pattern: each partial wrapped in div with unique id for hx-swap-oob=true WebSocket push"
    - "Request.app.state pattern: all route handlers read bot components from app.state"
    - "Action routes return HTML partials (not JSON) for HTMX swap targeting"
    - "Decimal serialization: API routes use str() for all Decimal values in JSON"

key-files:
  created:
    - src/bot/dashboard/routes/pages.py
    - src/bot/dashboard/routes/api.py
    - src/bot/dashboard/routes/actions.py
    - src/bot/dashboard/templates/index.html
    - src/bot/dashboard/templates/partials/bot_status.html
    - src/bot/dashboard/templates/partials/balance.html
    - src/bot/dashboard/templates/partials/analytics.html
    - src/bot/dashboard/templates/partials/positions.html
    - src/bot/dashboard/templates/partials/funding_rates.html
    - src/bot/dashboard/templates/partials/trade_history.html
    - src/bot/dashboard/templates/partials/config_form.html
    - src/bot/dashboard/update_loop.py
  modified:
    - src/bot/dashboard/app.py

key-decisions:
  - "Action routes return HTML partials (not JSON) so HTMX can swap panel content directly"
  - "API routes serialize all Decimal values to strings to avoid JSON serialization errors"
  - "Inline JS for timestamp formatting in trade history (avoids custom Jinja2 filter complexity)"
  - "WebSocket update loop renders partials via Jinja2 env.get_template() to avoid Request dependency"

patterns-established:
  - "Panel ID convention: {name}-panel (bot-status-panel, balance-panel, etc.) for OOB targeting"
  - "Config form pattern: POST returns partial with message/error for inline feedback"
  - "Dark theme cards: bg-dash-card rounded-lg p-4 border border-dash-border"

# Metrics
duration: 3min
completed: 2026-02-11
---

# Phase 3 Plan 4: Dashboard Routes & Templates Summary

**Full dashboard UI with page/API/action routes, 7 HTMX partials covering all DASH requirements, and WebSocket update loop for real-time refresh**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-11T21:42:28Z
- **Completed:** 2026-02-11T21:46:07Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments
- Page route (GET /) gathers all bot data and renders full dashboard with 7 panels
- 6 JSON API endpoints covering positions, funding rates, trade history, status, balance, and analytics
- 3 action routes for bot stop/start and runtime config updates with HTMX partial responses
- 8 Jinja2 templates (1 index + 7 partials) with dark theme, Tailwind CSS, and unique OOB-swap IDs
- WebSocket update loop function for periodic broadcast of all rendered partials
- All 206 existing tests pass without regression

## Task Commits

Each task was committed atomically:

1. **Task 1: Create page routes, API routes, and action routes** - `84611ef` (feat)
2. **Task 2: Create all Jinja2 templates and WebSocket update loop** - `3f8f1b3` (feat)

## Files Created/Modified
- `src/bot/dashboard/routes/pages.py` - GET / page route serving full dashboard with all data
- `src/bot/dashboard/routes/api.py` - JSON API endpoints for all DASH data requirements
- `src/bot/dashboard/routes/actions.py` - POST endpoints for bot control and config updates
- `src/bot/dashboard/app.py` - Registers pages, api, actions routers; removed placeholder root
- `src/bot/dashboard/templates/index.html` - Main dashboard page extending base.html with grid layout
- `src/bot/dashboard/templates/partials/bot_status.html` - DASH-04: running/stopped badge, start/stop buttons, emergency alert
- `src/bot/dashboard/templates/partials/balance.html` - DASH-05: net P&L, funding collected, fees paid
- `src/bot/dashboard/templates/partials/analytics.html` - DASH-07: Sharpe ratio, max drawdown, win rate
- `src/bot/dashboard/templates/partials/positions.html` - DASH-01: open positions table with P&L breakdown
- `src/bot/dashboard/templates/partials/funding_rates.html` - DASH-02: funding rates table with percentage formatting
- `src/bot/dashboard/templates/partials/trade_history.html` - DASH-03: closed positions with cumulative profit
- `src/bot/dashboard/templates/partials/config_form.html` - DASH-06: strategy parameter form with HTMX submit
- `src/bot/dashboard/update_loop.py` - Periodic WebSocket broadcast rendering all partials

## Decisions Made
- Action routes return HTML partials (not JSON) so HTMX can swap panel content directly without client-side rendering
- All Decimal values serialized as strings in JSON API responses to avoid serialization errors
- Used inline JavaScript for timestamp formatting in trade history (simpler than a custom Jinja2 filter)
- WebSocket update loop uses Jinja2 env.get_template() + render() directly (avoids needing a Request object)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All routes and templates ready for Plan 05 integration (lifespan wiring, server startup)
- dashboard_update_loop() ready to be started as asyncio task in app lifespan
- 15 routes registered: /, 6 API, 3 actions, /ws, plus FastAPI auto-generated docs/openapi
- All partials have unique IDs matching OOB swap targets in update_loop.py

## Self-Check: PASSED

All files verified present. All commits verified in git log.

---
*Phase: 03-dashboard-analytics*
*Completed: 2026-02-11*
