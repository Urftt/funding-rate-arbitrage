---
phase: 11-decision-context
plan: 01
subsystem: analytics
tags: [decision-engine, percentile, bisect, action-label, funding-rate, api]

# Dependency graph
requires:
  - phase: 08-pair-analysis-foundation
    provides: PairAnalyzer service with get_pair_stats() and historical rate queries
  - phase: 05-signal-analysis-integration
    provides: SignalEngine with CompositeSignal, classify_trend from bot.signals.trend
  - phase: 01-core-trading-engine
    provides: FundingMonitor with get_all_funding_rates() and get_funding_rate()
provides:
  - DecisionEngine service class with RateContext, SignalBreakdown, ActionLabel, DecisionContext dataclasses
  - compute_rate_percentile function using bisect for O(log n) percentile rank
  - classify_action function with 5 threshold tiers and evidence-based reasons
  - GET /api/decision/{symbol} endpoint for single pair decision context
  - GET /api/decision/summary endpoint for all pairs with live rates
  - DecisionEngine wired in main.py lifespan when data_store available
affects: [11-02-PLAN, dashboard-ui, decision-summary-page]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DecisionEngine service bridging multiple data sources into structured context"
    - "bisect-based percentile rank computation on sorted Decimal lists"
    - "TTL cache pattern for expensive cross-service computations"
    - "set_latest_signals for decoupled signal injection"

key-files:
  created:
    - src/bot/analytics/decision_engine.py
  modified:
    - src/bot/dashboard/routes/api.py
    - src/bot/dashboard/app.py
    - src/bot/main.py

key-decisions:
  - "Used set_latest_signals pattern instead of calling SignalEngine directly to avoid coupling to markets dict"
  - "Summary route registered before symbol:path route for correct FastAPI matching"
  - "DecisionEngine only created when data_store is available (same guard as PairAnalyzer)"
  - "Empty weights dict in SignalBreakdown since CompositeSignal does not carry weight config"

patterns-established:
  - "DecisionEngine: bridge pattern combining PairAnalyzer + SignalEngine + FundingMonitor into DecisionContext"
  - "bisect percentile: compute_rate_percentile(current, sorted_list) -> Decimal 0-100"
  - "classify_action: P75/P50/P25 quartile thresholds with evidence-based reasons"

# Metrics
duration: 4min
completed: 2026-02-13
---

# Phase 11 Plan 01: DecisionEngine Backend Summary

**DecisionEngine service computing rate percentiles via bisect, action label classification with P75/P50/P25 thresholds, and two API endpoints for decision context**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-13T16:09:23Z
- **Completed:** 2026-02-13T16:13:30Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- DecisionEngine service bridging PairAnalyzer, SignalEngine, and FundingMonitor into structured DecisionContext objects
- Percentile rank computation using bisect for O(log n) lookup on sorted historical rates
- Action label classification with 5 tiers (Strong/Moderate/Below/Not Recommended/Insufficient) and evidence-based reasons
- Two API endpoints: GET /api/decision/summary and GET /api/decision/{symbol} with range filtering
- TTL caching (120s default) to prevent redundant computation during dashboard update cycles
- All 296 existing tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: DecisionEngine service with dataclasses and computation logic** - `4bffc08` (feat)
2. **Task 2: API endpoints and app/main wiring for DecisionEngine** - `8a3e3dc` (feat)

## Files Created/Modified
- `src/bot/analytics/decision_engine.py` - DecisionEngine service with RateContext, SignalBreakdown, ActionLabel, DecisionContext dataclasses, compute_rate_percentile, classify_action
- `src/bot/dashboard/routes/api.py` - GET /api/decision/summary and GET /api/decision/{symbol} endpoints
- `src/bot/dashboard/app.py` - app.state.decision_engine placeholder
- `src/bot/main.py` - DecisionEngine import and wiring in lifespan

## Decisions Made
- Used `set_latest_signals()` pattern for decoupled signal injection instead of calling SignalEngine directly (avoids coupling to markets dict which would require exchange client)
- Registered `/decision/summary` route BEFORE `/decision/{symbol:path}` so FastAPI matches "summary" as a route, not as a symbol path parameter
- DecisionEngine only instantiated when `data_store` is available (same guard pattern as PairAnalyzer wiring)
- SignalBreakdown weights dict left empty because CompositeSignal does not carry the weight configuration; weights can be added later if needed
- Used last 30 rate values for trend classification (matching research recommendation)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- DecisionEngine backend is complete and ready for Plan 11-02 (UI integration: percentile badges, trend arrows, action labels, summary page)
- API endpoints are live and return structured JSON ready for frontend consumption
- Signal breakdown will be populated when update loop calls `set_latest_signals()` (wiring in 11-02)

---
*Phase: 11-decision-context*
*Completed: 2026-02-13*
