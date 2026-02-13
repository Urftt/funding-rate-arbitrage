# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-13)

**Core value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.
**Current focus:** v1.2 Strategy Discovery -- Phase 11 (Decision Context)

## Current Position

Milestone: v1.2 Strategy Discovery
Phase: 11 of 11 (Decision Context)
Plan: 2 of 2 in current phase
Status: Complete
Last activity: 2026-02-13 -- Completed 11-02 (Decision Context UI)

Progress: [██████████████████████████████] 100% (37/37 plans across all milestones; 11/11 v1.2 plans)

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
- Total plans completed: 11
- Total execution time: ~35min

**By Phase (v1.2):**

| Phase | Plans | Duration | Status |
|-------|-------|----------|--------|
| 8. Pair Analysis Foundation | 2/2 | 6min | Complete |
| 9. Trade Replay | 3/3 | 8min | Complete |
| 10. Strategy Builder Visualization | 3/3 | 13min | Complete |
| 11. Decision Context | 2/2 | 8min | Complete |

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
- Boxplot CDN loaded in pairs.html head block only (not base.html) to avoid loading on other pages (10-03)
- MarketCapService uses stdlib urllib.request to avoid adding new Python dependencies (10-03)
- Server-side histogram binning with Decimal precision for percentage labels (10-03)
- CoinGecko data fetched on page load with graceful degradation if unavailable (10-03)
- Tier column shown in ranking table only when CoinGecko data loads successfully (10-03)
- Used set_latest_signals pattern for decoupled signal injection avoiding coupling to markets dict (11-01)
- Summary route registered before symbol:path route for correct FastAPI matching (11-01)
- DecisionEngine only created when data_store is available, same guard as PairAnalyzer (11-01)
- Empty weights dict in SignalBreakdown since CompositeSignal does not carry weight config (11-01)
- Used CSS group-hover tooltips instead of JS tooltip library for zero-dependency glossary (11-02)
- Blue/cyan/amber/gray palette for decision badges to avoid collision with green/red rate colors (11-02)
- Cards sorted by recommendation quality for quick visual scanning (11-02)
- Decision contexts fetched in both WebSocket update loop and dashboard index for consistent experience (11-02)

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
Stopped at: Completed 11-02-PLAN.md (Decision Context UI) -- Phase 11 complete, v1.2 milestone complete
Resume file: None
Next step: All plans complete. v1.2 Strategy Discovery milestone finished.
