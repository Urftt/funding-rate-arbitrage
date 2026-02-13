# Roadmap: Funding Rate Arbitrage Bot

## Milestones

- ✅ **v1.0 MVP** -- Phases 1-3 (shipped 2026-02-11)
- ✅ **v1.1 Strategy Intelligence** -- Phases 4-7 (shipped 2026-02-12)
- 🚧 **v1.2 Strategy Discovery** -- Phases 8-11 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-3) -- SHIPPED 2026-02-11</summary>

- [x] Phase 1: Core Trading Engine (5/5 plans) -- completed 2026-02-11
- [x] Phase 2: Multi-Pair Intelligence (4/4 plans) -- completed 2026-02-11
- [x] Phase 3: Dashboard & Analytics (5/5 plans) -- completed 2026-02-11

See `.planning/milestones/v1.0-ROADMAP.md` for full details.

</details>

<details>
<summary>✅ v1.1 Strategy Intelligence (Phases 4-7) -- SHIPPED 2026-02-12</summary>

- [x] Phase 4: Historical Data Foundation (3/3 plans) -- completed 2026-02-12
- [x] Phase 5: Signal Analysis & Integration (3/3 plans) -- completed 2026-02-12
- [x] Phase 6: Backtest Engine (4/4 plans) -- completed 2026-02-12
- [x] Phase 7: Dynamic Position Sizing (2/2 plans) -- completed 2026-02-12

See `.planning/milestones/v1.1-ROADMAP.md` for full details.

</details>

### 🚧 v1.2 Strategy Discovery (In Progress)

**Milestone Goal:** Enable learning-driven strategy development through historical pair analysis, profitability visualization, and iterative backtesting -- so the user can build intuition about what works before committing capital.

**Key constraints:** All features are read-only on existing data. Zero new Python dependencies. One CDN addition (boxplot plugin). One external API (CoinGecko free tier). No trading engine changes.

- [x] **Phase 8: Pair Analysis Foundation** - User can explore and compare pairs by historical funding rate profitability (completed 2026-02-13)
- [ ] **Phase 9: Trade Replay** - User can inspect individual backtest trades to understand why strategies win or lose
- [ ] **Phase 10: Strategy Builder & Visualization** - User can test strategies across multiple pairs and analyze rate distributions
- [ ] **Phase 11: Decision Context** - User can see actionable recommendations backed by historical evidence

## Phase Details

### Phase 8: Pair Analysis Foundation
**Goal**: User can browse all tracked pairs ranked by historical profitability, drill into per-pair statistics, and filter by time range
**Depends on**: Phase 7 (historical data store and backtest infrastructure from v1.1)
**Requirements**: EXPR-01, EXPR-02, EXPR-03, EXPR-05, EXPR-06
**Success Criteria** (what must be TRUE):
  1. User can view a ranking table of all tracked pairs sorted by fee-adjusted yield, with columns for avg rate, median, std dev, and % positive periods
  2. User can click any pair to see a funding rate time series chart showing rate history over time
  3. User can switch between date ranges (7d, 30d, 90d, all) and the ranking table and charts update accordingly
  4. User can see annualized yield figures that account for trading fees, with per-period net yield visible for context
  5. Pairs with insufficient data are flagged or excluded so rankings are not misleading
**Plans:** 2 plans

Plans:
- [x] 08-01: PairAnalyzer service and API endpoints
- [x] 08-02: Pair explorer page with ranking table, time series chart, and date range filtering

### Phase 9: Trade Replay
**Goal**: User can inspect individual simulated trades from backtest results to understand entry/exit reasoning, holding periods, and fee-adjusted profitability
**Depends on**: Phase 7 (backtest engine from v1.1); independent of Phase 8
**Requirements**: TRPL-01, TRPL-02, TRPL-03, TRPL-04, TRPL-05
**Success Criteria** (what must be TRUE):
  1. Backtest results include per-trade detail (entry/exit times, prices, funding collected, fees paid, net P&L) surfaced from PnLTracker data
  2. User can view a trade log table with expandable rows showing full P&L breakdown per trade
  3. User can see win/loss categorization with summary stats (win rate, avg win size, avg loss size, best/worst trade)
  4. User can see trade entry/exit markers overlaid on the equity curve chart
  5. User can view a trade P&L distribution histogram showing how many trades fell at each profit/loss level
**Plans**: TBD

Plans:
- [ ] 09-01: BacktestTrade model and trade-level data extraction
- [ ] 09-02: Trade log UI and win/loss statistics
- [ ] 09-03: Trade markers on equity curve and P&L distribution chart

### Phase 10: Strategy Builder & Visualization
**Goal**: User can test parameter configurations across multiple pairs simultaneously, compare results, and explore rate distributions with statistical depth
**Depends on**: Phase 8 (pair explorer page, PairAnalyzer), Phase 9 (trade-level backtest output)
**Requirements**: EXPR-04, EXPR-07, EXPR-08, EXPR-09, STRT-01, STRT-02, STRT-03, STRT-04
**Success Criteria** (what must be TRUE):
  1. User can select multiple pairs and run the same backtest parameters across all of them, seeing a unified comparison table (pair, net P&L, Sharpe, win rate) with aggregate summary ("X of Y pairs profitable")
  2. User can apply preset strategy templates (conservative, balanced, aggressive) that pre-fill backtest parameters
  3. User can view a funding rate distribution histogram for any individual pair
  4. User can compare rate distributions across pairs via box plots on a single chart
  5. User can filter pairs by market cap tier (mega, large, mid, small) using CoinGecko data, and see a historical performance summary card
**Plans**: TBD

Plans:
- [ ] 10-01: Multi-pair backtest execution and comparison table
- [ ] 10-02: Strategy presets and aggregate summaries
- [ ] 10-03: Distribution histograms, box plots, and market cap filtering

### Phase 11: Decision Context
**Goal**: User can see actionable, evidence-backed recommendations on existing dashboard panels that answer "should I trade this pair?"
**Depends on**: Phase 8 (pair statistics for percentiles and trends)
**Requirements**: DCSN-01, DCSN-02, DCSN-03, DCSN-04, DCSN-05
**Success Criteria** (what must be TRUE):
  1. User can see contextual rate indicators on the funding rates panel showing where the current rate sits historically (percentile) and its trend direction
  2. User can see a signal score breakdown showing how each sub-signal (trend, persistence, basis, volume) contributes to the composite score
  3. User can see recommended action labels ("Strong opportunity", "Below average", "Not recommended") derived from historical evidence
  4. User can hover over key metrics to see glossary tooltips explaining what each number means
  5. User can view a "should I trade?" summary page that aggregates historical evidence with confidence ranges into a clear recommendation
**Plans**: TBD

Plans:
- [ ] 11-01: Rate percentile indicators and signal breakdown
- [ ] 11-02: Action labels, glossary tooltips, and summary page

## Progress

**Execution Order:**
Phases execute in numeric order: 8 → 9 → 10 → 11
(Phase 9 is independent of Phase 8, but sequential execution is simpler for a solo developer)

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Core Trading Engine | v1.0 | 5/5 | Complete | 2026-02-11 |
| 2. Multi-Pair Intelligence | v1.0 | 4/4 | Complete | 2026-02-11 |
| 3. Dashboard & Analytics | v1.0 | 5/5 | Complete | 2026-02-11 |
| 4. Historical Data Foundation | v1.1 | 3/3 | Complete | 2026-02-12 |
| 5. Signal Analysis & Integration | v1.1 | 3/3 | Complete | 2026-02-12 |
| 6. Backtest Engine | v1.1 | 4/4 | Complete | 2026-02-12 |
| 7. Dynamic Position Sizing | v1.1 | 2/2 | Complete | 2026-02-12 |
| 8. Pair Analysis Foundation | v1.2 | 2/2 | Complete | 2026-02-13 |
| 9. Trade Replay | v1.2 | 0/3 | Not started | - |
| 10. Strategy Builder & Visualization | v1.2 | 0/3 | Not started | - |
| 11. Decision Context | v1.2 | 0/2 | Not started | - |
