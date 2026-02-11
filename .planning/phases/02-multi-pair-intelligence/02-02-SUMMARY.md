---
phase: 02-multi-pair-intelligence
plan: 02
subsystem: market-data, ranking
tags: [tdd, decimal, funding-rate, net-yield, opportunity-scoring, fee-amortization]

# Dependency graph
requires:
  - phase: 02-multi-pair-intelligence
    plan: 01
    provides: "OpportunityScore dataclass, FeeSettings, ExchangeClient.get_markets"
  - phase: 01-core-trading-engine
    provides: "FundingRateData model, FeeCalculator"
provides:
  - "OpportunityRanker class with rank_opportunities method"
  - "Net yield scoring: funding_rate - amortized_round_trip_fee"
  - "Annualized yield with interval_hours normalization (4h/8h)"
  - "Filtering by min_rate, min_volume_24h, spot pair availability"
  - "Spot symbol derivation via ccxt markets dict"
affects: [02-04-orchestrator-v2]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED/GREEN/REFACTOR for pure computation modules"
    - "Spot symbol derivation via markets dict lookup (not string manipulation)"
    - "Amortized fee = round_trip_fee_pct / min_holding_periods"

key-files:
  created:
    - src/bot/market_data/opportunity_ranker.py
    - tests/test_market_data/test_opportunity_ranker.py
  modified:
    - src/bot/market_data/__init__.py

key-decisions:
  - "Net yield formula uses Decimal arithmetic exclusively -- no float conversions"
  - "Spot symbol derived from markets dict base/quote fields, not string manipulation"
  - "Inactive spot markets treated same as missing -- pair excluded"

patterns-established:
  - "Pure computation modules tested via TDD with exact Decimal assertions"
  - "Market dict lookup pattern for spot/perp symbol mapping"

# Metrics
duration: 3min
completed: 2026-02-11
---

# Phase 2 Plan 2: OpportunityRanker Net Yield Scoring Summary

**TDD-built OpportunityRanker scoring pairs by net yield after amortized fees, with interval normalization and spot/volume/rate filtering**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-11T20:57:10Z
- **Completed:** 2026-02-11T20:59:57Z
- **Tasks:** 3 (TDD RED, GREEN, REFACTOR)
- **Files modified:** 3

## Accomplishments
- OpportunityRanker with rank_opportunities method scoring pairs by net yield after amortized round-trip fees
- 14 tests covering all 8 specified test cases plus edge cases (inactive spot, custom holding periods)
- Annualized yield correctly normalizes for different funding intervals (4h vs 8h)
- Filtering pipeline: min_rate -> min_volume -> spot availability -> score -> sort

## Task Commits

Each task was committed atomically (TDD):

1. **RED: Failing tests** - `d884b3c` (test) - 14 test cases across 9 test classes
2. **GREEN: Implementation** - `9cb8a28` (feat) - OpportunityRanker with rank_opportunities
3. **REFACTOR: Package export** - `416d3dc` (refactor) - Export from market_data __init__

## Files Created/Modified
- `src/bot/market_data/opportunity_ranker.py` - OpportunityRanker class with net yield scoring, spot derivation, filtering
- `tests/test_market_data/test_opportunity_ranker.py` - 14 tests covering formula correctness, filters, sorting, edge cases
- `src/bot/market_data/__init__.py` - Added OpportunityRanker to package exports

## Decisions Made
- Net yield formula uses Decimal throughout -- consistent with project convention (no float for monetary values)
- Spot symbol derived from markets dict base/quote fields rather than string manipulation of perp symbol -- reliable across any exchange naming convention
- Inactive spot markets treated as unavailable (same as missing) -- conservative approach prevents trading pairs without liquid spot leg

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Pure computation module with no external dependencies.

## Next Phase Readiness
- OpportunityRanker ready for OrchestratorV2 (02-04) integration
- Accepts FundingRateData from FundingMonitor and markets dict from ExchangeClient.get_markets
- Returns sorted OpportunityScore list for position entry decisions

## Self-Check: PASSED

- All 3 files verified present on disk
- Commit d884b3c (RED) verified in git log
- Commit 9cb8a28 (GREEN) verified in git log
- Commit 416d3dc (REFACTOR) verified in git log
- Full test suite: 163 tests pass, 0 failures

---
*Phase: 02-multi-pair-intelligence*
*Completed: 2026-02-11*
