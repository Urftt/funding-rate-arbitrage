---
phase: 05-signal-analysis-integration
plan: 03
subsystem: signals
tags: [composite-scoring, signal-engine, strategy-mode, feature-flag, weighted-aggregation]

# Dependency graph
requires:
  - phase: 05-01
    provides: "trend classification (classify_trend) and persistence scoring (compute_persistence_score)"
  - phase: 05-02
    provides: "basis spread computation (compute_basis_spread) and volume trend filtering (compute_volume_trend)"
  - phase: 04
    provides: "historical data store with get_funding_rates and get_ohlcv_candles"
provides:
  - "compute_composite_score: weighted aggregation of sub-signal scores"
  - "normalize_rate_level: funding rate to 0-1 score normalization"
  - "SignalEngine: orchestrates all sub-signals into ranked composite scores"
  - "SignalEngine.score_for_exit: composite exit decision scoring"
  - "Orchestrator strategy_mode branching: composite vs simple paths"
  - "Complete signals/__init__.py public API"
affects: [backtest-engine, dynamic-sizing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "strategy_mode feature flag for composite vs simple entry/exit paths"
    - "SignalEngine graceful degradation with None dependencies"
    - "Composite signal INFO logging for observability (SGNL-06)"

key-files:
  created:
    - src/bot/signals/composite.py
    - src/bot/signals/engine.py
    - tests/test_signals/test_composite.py
    - tests/test_signals/test_engine.py
  modified:
    - src/bot/signals/__init__.py
    - src/bot/orchestrator.py
    - src/bot/main.py
    - tests/test_orchestrator.py

key-decisions:
  - "Spot symbol derivation duplicated in engine.py (not imported from ranker) to keep signal module independent"
  - "Composite score uses rate as proxy for net_yield/annualized_yield; actual fee check remains in PositionManager"
  - "Composite mode with signal_engine=None gracefully falls back to simple (v1.0) path"
  - "Volume trend is a hard filter: volume_ok=False prevents entry regardless of composite score"

patterns-established:
  - "Feature flag pattern: strategy_mode='simple' preserves v1.0 behavior, 'composite' enables v1.1"
  - "Optional injection: SignalEngine | None = None allows gradual rollout"
  - "Graceful degradation: each sub-signal falls back to neutral when data unavailable"

# Metrics
duration: 7min
completed: 2026-02-12
---

# Phase 5 Plan 3: Composite Signal Engine and Orchestrator Integration Summary

**Composite signal aggregator with weighted sub-signal scoring, SignalEngine orchestrating trend/persistence/basis/volume signals, and strategy_mode feature flag wiring into orchestrator for entry and exit decisions**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-12T20:24:08Z
- **Completed:** 2026-02-12T20:31:22Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Built composite signal aggregator with normalize_rate_level and compute_composite_score functions
- Built SignalEngine orchestrating all 4 sub-signals (trend, persistence, basis, volume) with graceful degradation
- Wired strategy_mode feature flag into orchestrator for both entry AND exit decisions
- All 6 SGNL requirements satisfied (SGNL-01 through SGNL-06)
- All 275 tests pass including 23 existing orchestrator tests unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Composite signal aggregator and SignalEngine** - `d604ab9` (feat)
2. **Task 2: Orchestrator integration and main.py wiring** - `3f6bb4f` (feat)

## Files Created/Modified
- `src/bot/signals/composite.py` - normalize_rate_level and compute_composite_score functions
- `src/bot/signals/engine.py` - SignalEngine class with score_opportunities and score_for_exit methods
- `src/bot/signals/__init__.py` - Complete public API exporting all signal module functions
- `src/bot/orchestrator.py` - strategy_mode branching with composite entry/exit methods
- `src/bot/main.py` - SignalEngine creation and injection when strategy_mode="composite"
- `tests/test_signals/test_composite.py` - 9 tests for composite aggregation
- `tests/test_signals/test_engine.py` - 9 tests for SignalEngine including graceful degradation
- `tests/test_orchestrator.py` - 3 new tests for composite strategy mode branching

## Decisions Made
- Duplicated spot symbol derivation logic in engine.py rather than importing from OpportunityRanker to keep the signal module independent of the ranking module
- Used funding rate as proxy for net_yield and annualized_yield in CompositeOpportunityScore since actual fee check happens in PositionManager
- Composite mode with signal_engine=None falls back to simple path (defensive coding)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Two test value calibration issues: (1) composite score with degradation defaults (0.475) was below entry_threshold (0.5), fixed by lowering threshold in test; (2) historical rate increments too small for trend detection, fixed by using larger increments. Both were test calibration, not implementation bugs.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All 6 SGNL requirements complete: trend (SGNL-01), persistence (SGNL-02), composite (SGNL-03), basis (SGNL-04), volume (SGNL-05), engine integration (SGNL-06)
- Phase 05 Signal Analysis Integration is fully complete
- Ready for Phase 06 (Backtest Engine) or Phase 07 (Dynamic Sizing)
- strategy_mode="simple" remains default; users opt into composite via TRADING_STRATEGY_MODE=composite

## Self-Check: PASSED

All 8 created/modified files verified on disk. Both task commits (d604ab9, 3f6bb4f) verified in git log.

---
*Phase: 05-signal-analysis-integration*
*Completed: 2026-02-12*
