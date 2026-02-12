# Requirements: Funding Rate Arbitrage Bot

**Defined:** 2026-02-12
**Core Value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.

## v1.1 Requirements

Requirements for v1.1 Strategy Intelligence milestone. Each maps to roadmap phases.

### Historical Data

- [ ] **DATA-01**: Bot fetches and stores historical funding rates from Bybit API with pagination handling
- [ ] **DATA-02**: Bot fetches and stores historical OHLCV price data from Bybit API
- [ ] **DATA-03**: Historical data persists across restarts via SQLite storage
- [ ] **DATA-04**: Data fetcher handles API rate limits and resumes from last fetched point

### Signal Analysis

- [ ] **SGNL-01**: Bot detects funding rate trend direction (rising, falling, stable) using short-window EMA
- [ ] **SGNL-02**: Bot scores rate persistence (how long rate has stayed elevated above threshold)
- [ ] **SGNL-03**: Bot computes composite entry signal combining rate level, trend, and persistence
- [ ] **SGNL-04**: Bot monitors spot-perp basis spread as additional entry/exit signal
- [ ] **SGNL-05**: Bot filters opportunities by volume trend (avoid high-rate pairs with declining volume)
- [ ] **SGNL-06**: Composite signal replaces simple threshold in entry/exit decisions (with feature flag to revert to v1.0 behavior)

### Backtesting

- [ ] **BKTS-01**: Bot replays historical data through strategy pipeline in chronological order without look-ahead bias
- [ ] **BKTS-02**: Backtest uses existing FeeCalculator and PnLTracker for fee-accurate P&L simulation
- [ ] **BKTS-03**: User can run parameter sweep over entry/exit thresholds and signal weights
- [ ] **BKTS-04**: Dashboard displays backtest results with equity curve and parameter heatmap
- [ ] **BKTS-05**: Backtest can simulate both v1.0 (simple threshold) and v1.1 (composite signal) strategies for comparison

### Dynamic Sizing

- [ ] **SIZE-01**: Position size scales with signal confidence (higher conviction = larger position)
- [ ] **SIZE-02**: Total portfolio exposure is capped at configurable limit
- [ ] **SIZE-03**: Dynamic sizer delegates to existing PositionSizer for exchange constraint validation

## Future Requirements

Deferred to v1.2+. Tracked but not in current roadmap.

### Advanced Validation

- **BKTS-06**: Walk-forward validation with rolling in-sample/out-of-sample windows
- **BKTS-07**: Monte Carlo robustness testing (resample trade sequence, confidence intervals)

### Advanced Sizing

- **SIZE-04**: Drawdown-responsive sizing (reduce positions during portfolio drawdown)
- **SIZE-05**: Correlation-aware exposure management (cap effective exposure across correlated pairs)

### Market Context

- **SGNL-07**: Open interest change tracking as confirming/warning signal
- **SGNL-08**: Market regime classification (bull/bear/sideways) with parameter adjustment

## Out of Scope

| Feature | Reason |
|---------|--------|
| Machine learning prediction | Simple statistical signals capture 80% of value; ML adds massive complexity for marginal gain |
| Cross-exchange arbitrage | Different APIs, fee structures, capital transfer delays -- massive complexity |
| Genetic/Bayesian optimization | Grid search sufficient for 3-5 parameter space |
| Real-time strategy switching | Too complex/risky for v1.1; adjust parameters within single strategy instead |
| Custom backtesting framework | Purpose-built replay loop sufficient for funding rate data (3 data points per 8h period) |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 4 | Pending |
| DATA-02 | Phase 4 | Pending |
| DATA-03 | Phase 4 | Pending |
| DATA-04 | Phase 4 | Pending |
| SGNL-01 | Phase 5 | Pending |
| SGNL-02 | Phase 5 | Pending |
| SGNL-03 | Phase 5 | Pending |
| SGNL-04 | Phase 5 | Pending |
| SGNL-05 | Phase 5 | Pending |
| SGNL-06 | Phase 5 | Pending |
| BKTS-01 | Phase 6 | Pending |
| BKTS-02 | Phase 6 | Pending |
| BKTS-03 | Phase 6 | Pending |
| BKTS-04 | Phase 6 | Pending |
| BKTS-05 | Phase 6 | Pending |
| SIZE-01 | Phase 7 | Pending |
| SIZE-02 | Phase 7 | Pending |
| SIZE-03 | Phase 7 | Pending |

**Coverage:**
- v1.1 requirements: 18 total
- Mapped to phases: 18
- Unmapped: 0

---
*Requirements defined: 2026-02-12*
*Last updated: 2026-02-12 after roadmap creation*
