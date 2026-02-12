---
phase: 05-signal-analysis-integration
plan: 02
subsystem: signals
tags: [basis-spread, volume-trend, index-price, decimal, ohlcv, bybit]

# Dependency graph
requires:
  - phase: 04-historical-data-foundation
    provides: "OHLCVCandle model and historical candle data for volume trend detection"
  - phase: 05-signal-analysis-integration/01
    provides: "Signal data models (CompositeSignal, TrendDirection) and package init"
provides:
  - "compute_basis_spread and normalize_basis_score functions in basis.py"
  - "compute_volume_trend function in volume.py"
  - "Index price extraction from Bybit tickers in FundingMonitor"
  - "get_index_price getter on FundingMonitor for direct access"
affects: [05-signal-analysis-integration/03, signal-engine, composite-scoring]

# Tech tracking
tech-stack:
  added: []
  patterns: [pure-function-signals, graceful-degradation, hard-filter-pattern]

key-files:
  created:
    - src/bot/signals/basis.py
    - src/bot/signals/volume.py
    - tests/test_signals/test_basis.py
    - tests/test_signals/test_volume.py
  modified:
    - src/bot/market_data/funding_monitor.py

key-decisions:
  - "Index prices cached in separate dict on FundingMonitor (not modifying FundingRateData v1.0 type)"
  - "Volume trend is a hard filter: volume_ok=False rejects pair regardless of composite score"
  - "Graceful degradation: insufficient candle data returns True (don't reject for lack of data)"

patterns-established:
  - "Pure function signals: stateless computation modules taking typed inputs, returning Decimal/bool"
  - "Hard filter pattern: volume_ok=False bypasses composite scoring to reject pairs"
  - "Spot symbol derivation: split on ':' to convert perpetual to spot symbol"

# Metrics
duration: 4min
completed: 2026-02-12
---

# Phase 5 Plan 2: Basis Spread and Volume Trend Signals Summary

**Basis spread (perp vs spot) and volume trend (OHLCV decline detection) sub-signal modules with index price extraction from Bybit tickers**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-12T20:16:55Z
- **Completed:** 2026-02-12T20:20:37Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Created `basis.py` with `compute_basis_spread` (safe Decimal division) and `normalize_basis_score` (0-1 clamping)
- Created `volume.py` with `compute_volume_trend` detecting declining volume from OHLCV candle history
- Enhanced FundingMonitor to extract `indexPrice` from Bybit ticker info and store in TickerService under derived spot symbol
- 24 new tests covering all edge cases (zero/negative prices, insufficient data, boundary conditions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Basis spread and volume trend computation modules** - `6cc24bf` (feat)
2. **Task 2: Extract index price from Bybit tickers for basis spread** - `a3b3bd5` (feat)

## Files Created/Modified
- `src/bot/signals/basis.py` - compute_basis_spread and normalize_basis_score pure functions
- `src/bot/signals/volume.py` - compute_volume_trend using OHLCVCandle history for decline detection
- `tests/test_signals/test_basis.py` - 14 tests for basis spread computation and normalization
- `tests/test_signals/test_volume.py` - 10 tests for volume trend detection with edge cases
- `src/bot/market_data/funding_monitor.py` - Added indexPrice extraction, _index_prices cache, get_index_price getter

## Decisions Made
- Index prices stored in a separate `_index_prices` dict on FundingMonitor rather than modifying the v1.0 `FundingRateData` dataclass
- Volume trend is a hard filter per research: `volume_ok=False` means the pair is rejected regardless of composite score
- Graceful degradation for insufficient candle data (returns True to avoid rejecting pairs due to missing data)
- Spot symbol derived by splitting on `:` (e.g., `BTC/USDT:USDT` -> `BTC/USDT`), matching existing OpportunityRanker pattern

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Basis spread and volume trend modules ready for integration into SignalEngine (Plan 03)
- FundingMonitor now provides index prices for basis computation via TickerService
- All functions are pure, stateless, and Decimal-based -- ready for composite scoring

## Self-Check: PASSED

All created files verified present. All commit hashes verified in git log.

---
*Phase: 05-signal-analysis-integration*
*Plan: 02*
*Completed: 2026-02-12*
