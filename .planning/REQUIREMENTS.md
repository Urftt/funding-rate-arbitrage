# Requirements: Funding Rate Arbitrage Bot

**Defined:** 2026-02-11
**Core Value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Market Data

- [ ] **MKTD-01**: User can see real-time funding rates for all Bybit perpetual pairs
- [ ] **MKTD-02**: Bot ranks all pairs by funding rate opportunity (net yield after fees)
- [ ] **MKTD-03**: Bot only enters positions when funding rate exceeds configurable minimum threshold

### Position Execution

- [ ] **EXEC-01**: Bot opens delta-neutral positions by placing spot buy + perp short simultaneously
- [ ] **EXEC-02**: Bot automatically closes positions when funding rate drops below exit threshold
- [ ] **EXEC-03**: Bot calculates position size using Decimal precision, respecting available balance and leverage limits
- [ ] **EXEC-04**: Bot accounts for entry and exit fees when evaluating if a trade is profitable

### Risk Management

- [ ] **RISK-01**: Bot enforces maximum position size per trading pair
- [ ] **RISK-02**: Bot enforces maximum number of simultaneously open positions
- [ ] **RISK-03**: User can trigger emergency stop that closes all open positions
- [ ] **RISK-04**: Bot continuously validates delta neutrality (spot qty matches perp qty within tolerance)
- [ ] **RISK-05**: Bot monitors margin ratio and alerts when it drops below configurable thresholds

### Paper Trading

- [ ] **PAPR-01**: Bot can run in paper trading mode with simulated execution and virtual balances
- [ ] **PAPR-02**: Paper trading uses identical logic path as real trading (single codebase, swappable executor)
- [ ] **PAPR-03**: Paper mode tracks P&L including simulated fees and funding payments

### Dashboard

- [ ] **DASH-01**: User can view all open positions with pair, entry price, size, unrealized P&L, and funding collected
- [ ] **DASH-02**: User can see funding rate overview across all Bybit perpetual pairs
- [ ] **DASH-03**: User can view trade history with timestamps, realized P&L, and cumulative profit over time
- [ ] **DASH-04**: User can start/stop the bot and see its current status and any error alerts
- [ ] **DASH-05**: User can see balance breakdown (available vs allocated capital)
- [ ] **DASH-06**: User can configure strategy parameters (funding thresholds, risk limits, pair filters) via dashboard
- [ ] **DASH-07**: User can view performance analytics (Sharpe ratio, max drawdown, win rate by pair)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Market Analysis

- **MKTD-04**: Funding rate heatmap visualization showing rates across all pairs over time
- **MKTD-05**: Liquidity analysis checking order book depth before entering positions
- **MKTD-06**: Slippage protection rejecting trades when expected slippage exceeds threshold

### Advanced Position Management

- **EXEC-05**: Dynamic rebalancing to shift capital from underperforming to higher-yielding pairs
- **EXEC-06**: Backtesting engine to test strategy on historical funding rate data

### Notifications

- **NOTF-01**: Telegram/webhook alerts for position opens, closes, errors, and funding collections

### Prediction

- **PRED-01**: Funding rate prediction model to estimate rate persistence and avoid pairs about to flip

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| High-frequency trading | Not funding arbitrage's strength — 8hr funding cycles tolerate minute-scale latency |
| Leveraged spot positions | Massively increases risk — keep spot unleveraged, only perp side uses leverage |
| Cross-exchange arbitrage | Single exchange (Bybit) keeps complexity manageable for learning |
| Social/copy trading | Legal/regulatory complexity, not core to learning goal |
| Auto capital injection | Prevents runaway capital allocation — require manual deposits |
| Mobile app | Web dashboard sufficient for monitoring |
| Multi-exchange support | Very high complexity — different APIs, cross-exchange coordination |
| Custom exotic order types | Simple limit/market orders sufficient, exchange handles the rest |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| MKTD-01 | TBD | Pending |
| MKTD-02 | TBD | Pending |
| MKTD-03 | TBD | Pending |
| EXEC-01 | TBD | Pending |
| EXEC-02 | TBD | Pending |
| EXEC-03 | TBD | Pending |
| EXEC-04 | TBD | Pending |
| RISK-01 | TBD | Pending |
| RISK-02 | TBD | Pending |
| RISK-03 | TBD | Pending |
| RISK-04 | TBD | Pending |
| RISK-05 | TBD | Pending |
| PAPR-01 | TBD | Pending |
| PAPR-02 | TBD | Pending |
| PAPR-03 | TBD | Pending |
| DASH-01 | TBD | Pending |
| DASH-02 | TBD | Pending |
| DASH-03 | TBD | Pending |
| DASH-04 | TBD | Pending |
| DASH-05 | TBD | Pending |
| DASH-06 | TBD | Pending |
| DASH-07 | TBD | Pending |

**Coverage:**
- v1 requirements: 22 total
- Mapped to phases: 0
- Unmapped: 22 (pending roadmap creation)

---
*Requirements defined: 2026-02-11*
*Last updated: 2026-02-11 after initial definition*
