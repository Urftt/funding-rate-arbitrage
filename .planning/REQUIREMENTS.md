# Requirements: Funding Rate Arbitrage Bot

**Defined:** 2026-02-13
**Core Value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.

## v1.2 Requirements

Requirements for milestone v1.2 Strategy Discovery. Each maps to roadmap phases.

### Pair Explorer

- [ ] **EXPR-01**: User can view a ranking table of all tracked pairs sorted by fee-adjusted historical yield
- [ ] **EXPR-02**: User can see per-pair statistics (avg rate, median, std dev, percentiles, % positive periods)
- [ ] **EXPR-03**: User can view a funding rate time series chart for any pair
- [ ] **EXPR-04**: User can view a rate distribution histogram for any pair
- [ ] **EXPR-05**: User can filter the ranking table by date range (7d, 30d, 90d, all)
- [ ] **EXPR-06**: User can see fee-adjusted annualized yield with per-period net yield context
- [ ] **EXPR-07**: User can compare rate distributions across pairs via box plots
- [ ] **EXPR-08**: User can filter pairs by market cap tier (mega, large, mid, small)
- [ ] **EXPR-09**: User can see a historical performance summary card ("X pairs averaged Y% yield after fees")

### Trade Replay

- [ ] **TRPL-01**: Backtest results include per-trade data (entry/exit times, prices, funding collected, fees, net P&L)
- [ ] **TRPL-02**: User can view a trade log table with expandable per-trade P&L breakdown
- [ ] **TRPL-03**: User can see win/loss trade categorization with summary statistics
- [ ] **TRPL-04**: User can see trade entry/exit markers overlaid on the equity curve or rate chart
- [ ] **TRPL-05**: User can view a trade P&L distribution histogram (how many trades at each profit/loss level)

### Strategy Builder

- [ ] **STRT-01**: User can run the same backtest parameters across multiple selected pairs simultaneously
- [ ] **STRT-02**: User can compare multi-pair results in a unified table (pair, net P&L, Sharpe, win rate)
- [ ] **STRT-03**: User can apply preset strategy templates (conservative, balanced, aggressive) to pre-fill parameters
- [ ] **STRT-04**: User can see "X of Y pairs profitable" aggregate summary for a configuration

### Decision View

- [ ] **DCSN-01**: User can see contextual rate indicators (current rate percentile, trend direction) on the funding rates panel
- [ ] **DCSN-02**: User can see a signal score breakdown display (sub-signal contributions)
- [ ] **DCSN-03**: User can see recommended action labels ("Strong opportunity", "Below average", "Not recommended")
- [ ] **DCSN-04**: User can see funding rate glossary tooltips explaining key metrics
- [ ] **DCSN-05**: User can see an overall "should I trade?" summary page with historical evidence and confidence ranges

## Future Requirements

Deferred to future releases. Tracked but not in current roadmap.

### Learning & Replay

- **LRPL-01**: User can step through a backtest trade-by-trade seeing market state at each decision
- **LRPL-02**: User can see rate regime annotations on historical charts ("Bull market", "Consolidation")
- **LRPL-03**: User can see parameter sensitivity preview before running full backtest

### Strategy Sophistication

- **SOPH-01**: User can follow a guided strategy builder wizard (explore → hypothesize → test → refine)
- **SOPH-02**: User can run walk-forward validation on backtests
- **SOPH-03**: User can run Monte Carlo robustness testing on backtest results

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Auto-execute from backtest results | Dangerous for a learning user; backtests have survivorship bias |
| Multi-exchange pair comparison | Bot only trades Bybit; cross-exchange data not actionable |
| AI-powered trade recommendations | User needs to build own understanding, not defer to AI |
| Social sentiment integration | Poorly correlated with funding rate dynamics |
| Custom indicator builder | User doesn't yet know what signals matter |
| Real-time push alerts | User is learning, not operating at scale; pull-based is better |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| EXPR-01 | — | Pending |
| EXPR-02 | — | Pending |
| EXPR-03 | — | Pending |
| EXPR-04 | — | Pending |
| EXPR-05 | — | Pending |
| EXPR-06 | — | Pending |
| EXPR-07 | — | Pending |
| EXPR-08 | — | Pending |
| EXPR-09 | — | Pending |
| TRPL-01 | — | Pending |
| TRPL-02 | — | Pending |
| TRPL-03 | — | Pending |
| TRPL-04 | — | Pending |
| TRPL-05 | — | Pending |
| STRT-01 | — | Pending |
| STRT-02 | — | Pending |
| STRT-03 | — | Pending |
| STRT-04 | — | Pending |
| DCSN-01 | — | Pending |
| DCSN-02 | — | Pending |
| DCSN-03 | — | Pending |
| DCSN-04 | — | Pending |
| DCSN-05 | — | Pending |

**Coverage:**
- v1.2 requirements: 22 total
- Mapped to phases: 0
- Unmapped: 22 ⚠️

---
*Requirements defined: 2026-02-13*
*Last updated: 2026-02-13 after initial definition*
