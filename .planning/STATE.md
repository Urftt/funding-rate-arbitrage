# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-13)

**Core value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.
**Current focus:** v1.2 Strategy Discovery -- Phase 10 (Strategy Builder Visualization) IN PROGRESS

## Current Position

Milestone: v1.2 Strategy Discovery
Phase: 10 of 11 (Strategy Builder Visualization)
Plan: 3 of 3 in current phase
Status: In Progress
Last activity: 2026-02-13 -- Completed 10-01 (Multi-Pair Backtest)

Progress: [█████████████████████████████░] 92% (34/37 plans across all milestones; 8/11 v1.2 plans)

## Performance Metrics

**Velocity (v1.0):**
- Total plans completed: 14
- Total execution time: ~1 day

**Velocity (v1.1):**
- Total plans completed: 12
- Total execution time: ~54min

**By Phase (v1.1):**

| Phase | Plans | Duration | Status |
|-------|-------|----------|--------|
| 4. Historical Data Foundation | 3/3 | 19min | Complete |
| 5. Signal Analysis Integration | 3/3 | 11min | Complete |
| 6. Backtest Engine | 4/4 | 18min | Complete |
| 7. Dynamic Position Sizing | 2/2 | 6min | Complete |

**Velocity (v1.2):**
- Total plans completed: 8
- Total execution time: ~22min

**By Phase (v1.2):**

| Phase | Plans | Duration | Status |
|-------|-------|----------|--------|
| 8. Pair Analysis Foundation | 2/2 | 6min | Complete |
| 9. Trade Replay | 3/3 | 8min | Complete |
| 10. Strategy Builder Visualization | 2/3 | 8min | In Progress |

## Accumulated Context

### Decisions

All decisions logged in PROJECT.md Key Decisions table.
- Reused OpportunityRanker fee formula for PairAnalyzer consistency (08-01)
- Used Counter for dominant interval_hours detection rather than assuming 8h (08-01)
- Sorted ranking with sufficient-data pairs first, then by yield descending (08-01)
- Used IIFE pattern from backtest.html for JS encapsulation consistency (08-02)
- Attached _showDetail to window for onclick access from innerHTML-built rows (08-02)
- Formatted all Decimal strings as percentages (* 100) with 4 decimal places (08-02)
- Used TYPE_CHECKING import for PositionPnL to avoid circular imports (09-01)
- Fixed total_trades to count round-trip trades instead of open+close events (09-01)
- Dynamic histogram bin count adapts to trade count: min(10, max(3, len(trades) // 3)) (09-01)
- avg_loss computed as absolute value for positive display magnitude (09-01)
- Used onclick toggle on nextElementSibling for expandable trade rows (09-02)
- Avg loss displayed with -$ prefix since server provides absolute value magnitude (09-02)
- Trade log/stats hidden in compare/sweep modes, shown only for single backtests (09-02)
- Trade markers use timestamp-to-index lookup for O(1) equity curve position mapping (09-03)
- Scatter datasets conditionally added only when trades exist for graceful degradation (09-03)
- Histogram hidden in compare/sweep modes; sweep best result passes trades for markers (09-03)
- Preset param values stored as strings for direct JSON/form compatibility (10-02)
- Presets fetched on page load with graceful degradation if endpoint unavailable (10-02)
- Sequential pair execution (not parallel) to avoid database contention in multi-pair mode (10-01)
- Compact results discard equity curve and trades for memory efficiency in multi-pair mode (10-01)
- Error rows show descriptive error text with fallback to "No data" (10-01)

### Pending Todos

None.

### Blockers/Concerns

- Bybit fee structures need verification (carried from v1.0)
- Look-ahead bias risk in backtesting (predicted vs settled funding rates differ)
- CoinGecko symbol mapping may fail for some Bybit pairs -- treat market cap as optional enhancement
- Pairs with insufficient historical data may produce misleading rankings -- enforce minimum data thresholds
- SQL aggregate queries on 50K+ records may need index optimization

## Session Continuity

Last session: 2026-02-13
Stopped at: Completed 10-01-PLAN.md (Multi-Pair Backtest)
Resume file: None
Next step: Execute 10-03-PLAN.md
