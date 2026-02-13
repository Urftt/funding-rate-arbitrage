---
phase: 11-decision-context
plan: 02
subsystem: ui
tags: [decision-context, percentile-badge, trend-arrow, action-label, signal-breakdown, glossary-tooltip, dashboard]

# Dependency graph
requires:
  - phase: 11-decision-context
    provides: DecisionEngine service with get_all_decision_contexts(), RateContext, SignalBreakdown, ActionLabel, DecisionContext dataclasses, and /api/decision/summary endpoint
  - phase: 01-core-trading-engine
    provides: FundingMonitor with get_all_funding_rates() for live rate display
provides:
  - Enhanced funding rates panel with percentile badge, trend arrow, and action label columns
  - Signal breakdown partial with bar chart visualization of sub-signals
  - Decision summary page (/decision) with sorted pair cards and glossary tooltips
  - Navigation bar Decision link
  - WebSocket update loop integration passing decision_contexts to funding rates template
affects: [dashboard-ui, decision-workflow]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Glossary tooltip macro using CSS group-hover for zero-JS tooltips"
    - "IIFE fetch pattern for decision summary page data loading"
    - "Graceful degradation: empty columns when decision engine unavailable"
    - "Blue-tone palette for decision context badges (distinct from green/red rate colors)"

key-files:
  created:
    - src/bot/dashboard/templates/decision.html
    - src/bot/dashboard/templates/partials/signal_breakdown.html
  modified:
    - src/bot/dashboard/templates/partials/funding_rates.html
    - src/bot/dashboard/templates/base.html
    - src/bot/dashboard/update_loop.py
    - src/bot/dashboard/routes/pages.py

key-decisions:
  - "Used CSS group-hover tooltips instead of JS tooltip library for zero-dependency glossary"
  - "Blue/cyan/amber/gray palette for decision badges to avoid collision with green/red rate colors"
  - "Cards sorted by recommendation quality: Strong > Moderate > Below > Not recommended > Insufficient"
  - "Decision contexts fetched in both update_loop (WebSocket) and dashboard_index (initial load) for consistent experience"

patterns-established:
  - "Glossary tooltip: Jinja2 macro with CSS group-hover for hover explanations"
  - "Decision card: JS-rendered pair cards from /api/decision/summary with sort-by-label-quality"
  - "Graceful degradation: decision_contexts defaults to empty dict when engine unavailable"

# Metrics
duration: 4min
completed: 2026-02-13
---

# Phase 11 Plan 02: Decision Context UI Summary

**Enhanced funding rates panel with percentile badges, trend arrows, and action labels; dedicated /decision summary page with signal breakdown bars, sorted pair cards, and glossary tooltips**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-13T16:15:47Z
- **Completed:** 2026-02-13T16:19:21Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Funding rates panel enhanced with 3 new columns: percentile badge (P0-P100 with blue/cyan/amber/gray tiers), trend arrow (rising/stable/falling), and action label (Strong/Moderate/Below/Not recommended/Insufficient)
- Decision summary page at /decision with sorted pair cards showing rate context, signal breakdown bars, action labels with confidence and evidence-based reasons
- Glossary tooltip bar with CSS-only hover tooltips explaining Percentile, Trend, Composite Score, Action Label, Confidence, Ann. Yield, Persistence, and Basis Spread
- Signal breakdown partial with horizontal bar chart visualization for rate level, trend, persistence, and basis sub-signals
- WebSocket update loop passes decision_contexts to funding rates template for real-time updates every 5 seconds
- Navigation bar updated with Decision link; all 296 existing tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Enhanced funding rates panel with decision context and WebSocket update loop integration** - `2b08aba` (feat)
2. **Task 2: Decision summary page with signal breakdown, glossary tooltips, and navigation** - `e640711` (feat)

## Files Created/Modified
- `src/bot/dashboard/templates/partials/funding_rates.html` - Added Pctl, Trend, Action columns with color-coded badges and graceful degradation
- `src/bot/dashboard/templates/partials/signal_breakdown.html` - Reusable partial with composite score, sub-signal bar charts, and volume filter
- `src/bot/dashboard/templates/decision.html` - Decision summary page with glossary tooltips, loading state, and JS-rendered pair cards
- `src/bot/dashboard/templates/base.html` - Added Decision nav link after Backtest
- `src/bot/dashboard/update_loop.py` - Fetch decision_contexts from DecisionEngine and pass to funding rates template render
- `src/bot/dashboard/routes/pages.py` - Added decision_contexts to dashboard index context and new GET /decision route

## Decisions Made
- Used CSS group-hover tooltips (Jinja2 macro) instead of a JS tooltip library for zero-dependency glossary implementation
- Blue/cyan/amber/gray palette for decision context badges to avoid collision with green/red rate value colors (per research anti-pattern guidance)
- Cards sorted by recommendation quality (Strong first, Insufficient last) for quick visual scanning
- Decision contexts fetched in both WebSocket update loop and dashboard index initial render for consistent user experience on page load and during real-time updates

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 11 (Decision Context) is now complete with both backend (Plan 01) and frontend (Plan 02)
- Full decision context workflow: DecisionEngine computes contexts -> API endpoints serve JSON -> Dashboard displays badges/cards
- v1.2 Strategy Discovery milestone is complete (all 11 phases, all plans executed)

## Self-Check: PASSED

- All 6 files verified present on disk
- Commit `2b08aba` (Task 1) verified in git log
- Commit `e640711` (Task 2) verified in git log
- All 296 tests pass with no regressions

---
*Phase: 11-decision-context*
*Completed: 2026-02-13*
