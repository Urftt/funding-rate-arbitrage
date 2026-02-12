# Roadmap: Funding Rate Arbitrage Bot

## Milestones

- ✅ **v1.0 MVP** -- Phases 1-3 (shipped 2026-02-11)
- 🚧 **v1.1 Strategy Intelligence** -- Phases 4-7 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-3) -- SHIPPED 2026-02-11</summary>

- [x] Phase 1: Core Trading Engine (5/5 plans) -- completed 2026-02-11
- [x] Phase 2: Multi-Pair Intelligence (4/4 plans) -- completed 2026-02-11
- [x] Phase 3: Dashboard & Analytics (5/5 plans) -- completed 2026-02-11

See `.planning/milestones/v1.0-ROADMAP.md` for full details.

</details>

### 🚧 v1.1 Strategy Intelligence (In Progress)

**Milestone Goal:** Evolve the bot from simple threshold-based trading to an intelligent strategy engine that considers funding rate trends, historical patterns, and market conditions -- validated through backtesting. Done when backtest demonstrates improved returns vs v1.0's simple threshold strategy.

- [x] **Phase 4: Historical Data Foundation** - Fetch, store, and persist historical funding rate and price data from Bybit (completed 2026-02-12)
- [ ] **Phase 5: Signal Analysis & Integration** - Compute composite entry/exit signals from trends and persistence, wire into orchestrator
- [ ] **Phase 6: Backtest Engine** - Replay historical data through strategy pipeline with parameter optimization and results visualization
- [ ] **Phase 7: Dynamic Position Sizing** - Scale position sizes by signal conviction within risk constraints

## Phase Details

### Phase 4: Historical Data Foundation
**Goal**: Bot has a reliable, persistent store of historical funding rate and price data that survives restarts and handles Bybit API quirks
**Depends on**: Phase 3 (v1.0 complete)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04
**Success Criteria** (what must be TRUE):
  1. Bot can fetch 90 days of historical funding rates for any Bybit perpetual pair and store them locally
  2. Bot can fetch historical OHLCV price data for any pair and store it alongside funding rates
  3. Historical data survives bot restarts without re-fetching (SQLite persistence)
  4. Resuming a fetch after interruption continues from the last stored record, not from scratch
  5. API rate limits are respected automatically (no 429 errors during bulk fetches)
**Plans:** 3 plans

Plans:
- [x] 04-01-PLAN.md -- Data models, database, config, pair selector, exchange client extensions
- [x] 04-02-PLAN.md -- HistoricalDataStore and HistoricalDataFetcher (data pipeline core)
- [x] 04-03-PLAN.md -- Orchestrator integration, main.py wiring, dashboard data status widget

### Phase 5: Signal Analysis & Integration
**Goal**: Bot makes entry/exit decisions using composite signals (funding rate trends, persistence, basis spread, volume) instead of simple thresholds, with a feature flag to revert to v1.0 behavior
**Depends on**: Phase 4
**Requirements**: SGNL-01, SGNL-02, SGNL-03, SGNL-04, SGNL-05, SGNL-06
**Success Criteria** (what must be TRUE):
  1. Bot detects whether a funding rate is trending up, down, or stable and uses this in entry decisions
  2. Bot scores how long a rate has stayed elevated and factors persistence into opportunity ranking
  3. Bot computes a composite signal score combining rate level, trend, persistence, basis spread, and volume -- visible in logs
  4. Composite signal replaces simple threshold for entry/exit decisions in the orchestrator scan cycle
  5. Setting `strategy_mode: simple` in config reverts all decisions to v1.0 threshold behavior (existing tests pass unchanged)
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD
- [ ] 05-03: TBD

### Phase 6: Backtest Engine
**Goal**: User can replay historical data through the full strategy pipeline to compare v1.0 vs v1.1 performance and optimize signal parameters
**Depends on**: Phase 5
**Requirements**: BKTS-01, BKTS-02, BKTS-03, BKTS-04, BKTS-05
**Success Criteria** (what must be TRUE):
  1. User can run a backtest over a date range and see realistic P&L results (including fees) without look-ahead bias
  2. Backtest reuses production FeeCalculator, PnLTracker, and PositionManager -- no separate simulation math
  3. User can sweep over entry/exit thresholds and signal weights to find optimal parameters
  4. Dashboard shows backtest results with equity curve and parameter comparison heatmap
  5. User can run both v1.0 (simple threshold) and v1.1 (composite signal) strategies side-by-side for direct comparison
**Plans**: TBD

Plans:
- [ ] 06-01: TBD
- [ ] 06-02: TBD
- [ ] 06-03: TBD

### Phase 7: Dynamic Position Sizing
**Goal**: Position sizes scale with signal conviction so higher-confidence opportunities get larger allocations, constrained by portfolio-level risk limits
**Depends on**: Phase 6
**Requirements**: SIZE-01, SIZE-02, SIZE-03
**Success Criteria** (what must be TRUE):
  1. A pair with a strong composite signal gets a measurably larger position than a pair with a weak signal (given identical exchange constraints)
  2. Total portfolio exposure across all open positions never exceeds the configured limit, regardless of individual signal strengths
  3. Dynamic sizer delegates to the existing PositionSizer for exchange constraint validation (qty_step, min_notional) -- no duplicate logic
**Plans**: TBD

Plans:
- [ ] 07-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 4 -> 5 -> 6 -> 7

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Core Trading Engine | v1.0 | 5/5 | Complete | 2026-02-11 |
| 2. Multi-Pair Intelligence | v1.0 | 4/4 | Complete | 2026-02-11 |
| 3. Dashboard & Analytics | v1.0 | 5/5 | Complete | 2026-02-11 |
| 4. Historical Data Foundation | v1.1 | 3/3 | Complete | 2026-02-12 |
| 5. Signal Analysis & Integration | v1.1 | 0/TBD | Not started | - |
| 6. Backtest Engine | v1.1 | 0/TBD | Not started | - |
| 7. Dynamic Position Sizing | v1.1 | 0/TBD | Not started | - |
