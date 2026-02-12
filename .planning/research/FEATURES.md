# Feature Landscape: Strategy Intelligence for Funding Rate Arbitrage

**Domain:** Strategy intelligence layer for crypto funding rate arbitrage (backtesting, trend analysis, dynamic sizing)
**Researched:** 2026-02-12
**Confidence:** MEDIUM -- verified against Bybit API docs, academic research, and industry practices; some specifics (e.g., exact ccxt pagination behavior) need implementation-time validation

## Scope

This document covers features for v1.1 ONLY -- the strategy intelligence milestone. It assumes the following v1.0 features are already built and working:

- Real-time funding rate scanning (FundingMonitor, 30s REST polling)
- Simple threshold-based entry/exit (OpportunityRanker with min_rate / exit_funding_rate)
- Delta-neutral execution (spot buy + perp short via swappable Executor ABC)
- Risk management (per-pair limits, max positions, emergency stop, margin monitoring)
- Paper trading with identical logic path
- Performance analytics (Sharpe, drawdown, win rate)
- Web dashboard with 7 panels and runtime config

---

## Table Stakes

Features that a strategy intelligence upgrade MUST have. Without these, "smarter strategy" is just marketing over the existing v1.0 threshold logic.

### Backtesting Capability

| Feature | Why Expected | Complexity | Depends On (v1.0) | Notes |
|---------|--------------|------------|-------------------|-------|
| **Historical funding rate data ingestion** | Cannot backtest without historical data; Bybit API provides it via `/v5/market/history-fund-rate` (200 records/page, paginated by endTime) | Medium | ExchangeClient (ccxt) | Must handle pagination: 200 records max per request, requires iterative fetching with sliding endTime. For 1 year of 8h data = ~1095 records = 6 API calls per symbol. Store as local Parquet/SQLite. |
| **Replay simulation engine** | Core of backtesting -- feed historical data through existing strategy logic in chronological order | High | Orchestrator._autonomous_cycle, OpportunityRanker | Event-driven replay: iterate through timestamped funding rate snapshots, invoke the same rank-decide-execute pipeline. Must prevent lookahead bias (no future data accessible at decision time). |
| **Fee-accurate P&L simulation** | Backtests without realistic fees produce dangerously optimistic results; research shows 17% of apparent opportunities lose money after transaction costs | Low | FeeCalculator, PnLTracker | Already built -- PnLTracker.record_open/close and FeeCalculator handle this. Backtest engine just needs to invoke them. |
| **Strategy parameter sweep** | Users need to test different min_rate, exit_rate, min_holding_periods to find what works | Medium | Config system (AppSettings, TradingSettings, RiskSettings) | Grid search over parameter combinations. Each combination runs a full replay. Output: parameter -> performance metrics table. |
| **Backtest results visualization** | Raw numbers are hard to interpret; need equity curve, trade markers, parameter heatmap | Low | Dashboard (existing Jinja2 + HTMX stack) | Render results on a new dashboard page. Equity curve is a cumulative P&L line chart. Parameter heatmap shows Sharpe/return across min_rate x exit_rate grid. |

### Funding Rate Trend Analysis

| Feature | Why Expected | Complexity | Depends On (v1.0) | Notes |
|---------|--------------|------------|-------------------|-------|
| **Funding rate history buffer** | Current FundingMonitor only keeps latest snapshot per symbol; trend analysis requires time-series history | Low | FundingMonitor._funding_rates | Add a rolling window buffer (e.g., deque of last N snapshots per symbol). Research shows autocorrelation is weak beyond 3 funding periods (~24h for 8h intervals), so 24-48 periods is sufficient. |
| **Rate trend direction detection** | "Is the rate rising, falling, or stable?" -- the most basic signal beyond absolute threshold. Enter when rising, avoid when falling. | Low | Funding rate history buffer (new) | Simple: compare current rate to moving average of last N periods. Or linear regression slope over window. No ML needed. |
| **Rate persistence scoring** | How long has this rate stayed elevated? Research shows mean-reversion is real (Ornstein-Uhlenbeck dynamics), so rates that just spiked are riskier than rates sustained for 3+ periods | Medium | Funding rate history buffer (new) | Count consecutive periods above entry threshold. Weight recent persistence higher. Academic research confirms DAR models outperform no-change baseline for next-period prediction. |
| **Composite entry signal** | Replace single threshold with multi-factor score: rate level + trend direction + persistence. This is the minimum viable "smarter entry" | Medium | Rate trend detection, persistence scoring, OpportunityRanker | Extend OpportunityScore to include signal_score. Composite: weighted sum of normalized rate, trend slope, persistence count. Replaces simple `rate > min_rate` check. |

### Dynamic Position Sizing

| Feature | Why Expected | Complexity | Depends On (v1.0) | Notes |
|---------|--------------|------------|-------------------|-------|
| **Conviction-scaled sizing** | Higher funding rate = higher confidence = larger position. Research shows this alone improves Sharpe from 1.4 to 2.3 vs. static sizing. | Medium | PositionSizer, composite entry signal (new) | Scale position size linearly or via Kelly fraction between min_size and max_position_size_per_pair based on signal_score. Fractional Kelly (quarter to half) recommended for crypto volatility. |
| **Risk-constrained sizing** | Conviction scaling without risk guardrails is dangerous. Must cap total exposure and per-pair exposure. | Low | RiskManager.check_can_open | Already partially built -- max_position_size_per_pair and max_simultaneous_positions exist. Add: total_portfolio_exposure_limit (sum of all position sizes as % of equity). |
| **Drawdown-responsive sizing** | Reduce position sizes when portfolio is in drawdown. Standard risk management practice. | Medium | Analytics (max_drawdown), PnLTracker.get_portfolio_summary | If current drawdown > X% of peak equity, scale all new positions by (1 - drawdown_ratio). Prevents doubling down during losing streaks. |

---

## Differentiators

Features that move this from "competent backtested strategy" to "sophisticated arbitrage system." Not required for v1.1 to be valuable, but each meaningfully improves risk-adjusted returns.

### Enhanced Market Context Signals

| Feature | Value Proposition | Complexity | Depends On | Notes |
|---------|-------------------|------------|------------|-------|
| **Spot-perp basis spread monitoring** | The basis (perp price - spot price) is a direct measure of market sentiment. Widening basis precedes funding rate increases. Z-score of basis > 2 is a confirmed entry signal in academic literature. | Medium | TickerService (already caches spot + perp prices) | Calculate basis = (perp_price - spot_price) / spot_price. Maintain rolling z-score. Use as additional signal in composite score. Cheap to compute -- prices are already cached. |
| **Open interest change tracking** | Surging OI + rising rates = genuine demand, not a spike. Falling OI + high rates = crowded exit about to happen. | Medium | New: requires Bybit `/v5/market/open-interest` API calls via ccxt `fetchOpenInterest` | Poll OI on same interval as funding rates. Track OI delta (% change over N periods). Positive OI delta = confirming signal, negative = warning. Note: ccxt pagination limited to 200 records for historical OI. |
| **Volume-weighted rate filtering** | High rate on low volume pairs is a trap -- insufficient liquidity for clean entry/exit. v1.0 has min_volume_24h but no volume trend. | Low | FundingMonitor (already captures volume_24h) | Track volume trend: is 24h volume increasing or decreasing vs. 7d average? Declining volume on a high-rate pair = avoid. |
| **Market regime classification** | Bull/bear/sideways regime dramatically affects funding rate strategy returns (research: 52% annualized in bull vs 8.7% in bear). Adjust risk parameters per regime. | High | New: BTC price trend as proxy, or multi-asset breadth | Simple regime: BTC 20-period SMA slope + funding rate breadth (% of pairs with positive rates). 3 states: risk-on, neutral, risk-off. Scale max_simultaneous_positions and position sizes accordingly. |

### Backtesting Sophistication

| Feature | Value Proposition | Complexity | Depends On | Notes |
|---------|-------------------|------------|------------|-------|
| **Walk-forward validation** | Prevents overfitting by optimizing on in-sample window, testing on out-of-sample, then rolling forward. Grid search alone risks curve-fitting to historical noise. | High | Parameter sweep (table stakes), replay engine | Split data into rolling windows (e.g., 3 months in-sample, 1 month out-of-sample). Optimize on in-sample, record out-of-sample performance. Average out-of-sample results = realistic expected performance. |
| **Historical OHLCV data for spread/slippage modeling** | Backtests assuming market orders at last price are unrealistic. Need price candles to model slippage and basis spread at entry/exit time. | Medium | New: fetch Bybit kline data via `/v5/market/kline` | Store alongside funding rate data. Use high/low of candle to estimate worst-case slippage. Adds realism to backtest P&L calculations. |
| **Monte Carlo robustness testing** | After parameter optimization, shuffle trade sequence to test if results depend on lucky ordering or are genuinely robust | Medium | Backtest results (table stakes) | Resample trade returns with replacement, run 1000+ simulations, compute confidence intervals on Sharpe/drawdown. Flags fragile strategies. |

### Advanced Sizing Strategies

| Feature | Value Proposition | Complexity | Depends On | Notes |
|---------|-------------------|------------|------------|-------|
| **Correlation-aware exposure management** | BTC-correlated altcoin positions are not truly diversified. 5 positions in correlated pairs = effectively 1 large position. | High | Historical price data, position tracking | Compute rolling correlation matrix of position returns. Cap total "effective exposure" (sum of position sizes weighted by average pairwise correlation). Prevents false diversification. |
| **Time-to-funding-aware sizing** | A position opened 1 hour before funding snapshot captures more value per dollar of fee than one opened 7 hours before. | Low | FundingRateData.next_funding_time (already available) | Scale position size or entry urgency by time remaining to next funding. Closer to snapshot = more aggressive entry (amortized fee is lower). |
| **Auto-compounding** | Reinvest funding profits into larger positions. Compound growth instead of flat returns. | Low | PnLTracker.get_portfolio_summary, PositionSizer | Use current equity (initial + accumulated P&L) instead of initial capital for sizing calculations. Simple change but meaningful over time. |

---

## Anti-Features

Features to explicitly NOT build in v1.1. Each has been considered and rejected for specific reasons.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Machine learning funding rate prediction** | Academic research shows DAR models provide modest next-period predictability, but building/training/maintaining ML models is a massive complexity increase for marginal gain. Simple statistical signals (trend slope, persistence) capture 80% of the value. | Use moving averages, linear regression slope, and consecutive-period counting. Revisit ML only if statistical signals prove insufficient after live testing. |
| **Real-time WebSocket data for backtesting** | Backtesting uses historical data, not live streams. Building WebSocket replay infrastructure is over-engineering. | Simple chronological iteration through stored DataFrames/dicts. Event-driven does not mean WebSocket-driven for backtests. |
| **Genetic algorithm / Bayesian parameter optimization** | Grid search with walk-forward validation is sufficient for the small parameter space (min_rate, exit_rate, holding_periods, sizing_factor). Advanced optimizers add complexity without proportional benefit for <10 parameters. | Grid search with walk-forward. If parameter space grows beyond 10 dimensions in future, then consider Bayesian optimization. |
| **Cross-exchange funding rate arbitrage** | Different APIs, different fee structures, capital transfer delays, and counterparty risk across exchanges. Massive complexity increase. | Stay single-exchange (Bybit). Cross-exchange is a v3.0 feature at earliest. |
| **Portfolio optimization (Markowitz/Black-Litterman)** | Overkill for funding rate arb where positions are nearly identical in structure. MPT assumes diverse asset classes. | Simple correlation-aware exposure limits are sufficient. |
| **Custom backtesting framework** | Building from scratch when the strategy is simple enough that a purpose-built replay loop suffices. Frameworks like Backtrader/Zipline add dependencies and abstraction overhead for a strategy that processes 3 data points per period. | Build a minimal replay engine tailored to funding rate data. The strategy evaluates rate + trend + persistence per 8h period -- this does not need a generic framework. |
| **Real-time strategy switching** | Automatically switching between different strategy modes based on market conditions. Too complex for v1.1, too risky without extensive testing. | Use market regime to adjust parameters (position sizes, thresholds) within a single strategy, not to switch strategies entirely. |

---

## Feature Dependencies

```
Historical Data Layer:
  Bybit API pagination handler --> Historical funding rate ingestion
  Historical funding rate ingestion --> Replay simulation engine
  Historical funding rate ingestion --> Funding rate history buffer (can also use live data)

Trend Analysis Layer:
  Funding rate history buffer --> Rate trend direction detection
  Funding rate history buffer --> Rate persistence scoring
  Rate trend detection + Persistence scoring --> Composite entry signal

Backtesting Layer:
  Replay simulation engine + Fee-accurate P&L --> Backtest execution
  Backtest execution --> Strategy parameter sweep
  Parameter sweep --> Walk-forward validation
  Backtest execution --> Backtest results visualization
  Backtest execution --> Monte Carlo robustness testing

Dynamic Sizing Layer:
  Composite entry signal --> Conviction-scaled sizing
  Conviction-scaled sizing --> Risk-constrained sizing (guardrails)
  PnLTracker drawdown data --> Drawdown-responsive sizing

Market Context Layer (differentiators):
  TickerService prices --> Spot-perp basis spread monitoring
  Bybit OI API --> Open interest change tracking
  FundingMonitor volume --> Volume-weighted rate filtering
  BTC price data + rate breadth --> Market regime classification
  Composite signal + Market context signals --> Enhanced entry signal

Integration:
  Enhanced entry signal --> Orchestrator._autonomous_cycle (replaces simple threshold)
  Conviction-scaled sizing --> Orchestrator.open_position (replaces static sizing)
  Backtest results --> Dashboard visualization (new page)
```

---

## MVP Recommendation for v1.1

### Phase 1: Historical Data + Trend Analysis (foundation for everything else)

Build first because backtesting AND smarter entry both require historical rate data.

1. Historical funding rate data ingestion (paginated Bybit API fetcher + local storage)
2. Funding rate history buffer (rolling window in FundingMonitor)
3. Rate trend direction detection (moving average slope)
4. Rate persistence scoring (consecutive periods above threshold)
5. Composite entry signal (replaces simple threshold in OpportunityRanker)

**Rationale:** Trend analysis is the lowest-risk, highest-impact improvement over v1.0. It makes the bot immediately smarter for live trading while also building the data infrastructure needed for backtesting.

### Phase 2: Backtesting Engine

Build second because parameter validation requires Phase 1's data and signals.

1. Replay simulation engine (feed historical data through strategy pipeline)
2. Fee-accurate P&L simulation (reuse existing PnLTracker/FeeCalculator)
3. Strategy parameter sweep (grid search over min_rate, exit_rate, holding_periods)
4. Backtest results visualization (equity curve + parameter heatmap on dashboard)

**Rationale:** Backtesting validates the trend signals from Phase 1 and provides evidence for parameter choices. Without it, trend analysis parameters are just guesses.

### Phase 3: Dynamic Position Sizing

Build last because sizing logic should be validated via backtesting first.

1. Conviction-scaled sizing (signal_score -> position size)
2. Risk-constrained sizing (total portfolio exposure limit)
3. Drawdown-responsive sizing (reduce during losing streaks)

**Rationale:** Sizing changes affect real money. They MUST be backtested (Phase 2) before live deployment. Phase ordering prevents deploying untested sizing logic.

### Defer to v1.2+

- Walk-forward validation (Phase 2 delivers value without it; add when parameter space grows)
- Market regime classification (high complexity, needs more live data to calibrate)
- Correlation-aware exposure (requires substantial historical price data infrastructure)
- Open interest tracking (additional API complexity, moderate signal value)
- Monte Carlo testing (nice-to-have after core backtesting works)

---

## Complexity Analysis

| Feature | Complexity | Effort Estimate | Risk |
|---------|------------|-----------------|------|
| Historical data ingestion | Medium | 2-3 days | API pagination edge cases, rate limits |
| Rate history buffer | Low | 0.5 days | Minimal -- deque per symbol |
| Trend direction detection | Low | 0.5 days | Choosing window size |
| Persistence scoring | Low-Medium | 1 day | Defining "elevated" threshold relative to mean |
| Composite entry signal | Medium | 1-2 days | Weight tuning (use backtest to validate) |
| Replay simulation engine | High | 3-5 days | Preventing lookahead bias, time simulation fidelity |
| Parameter sweep | Medium | 1-2 days | Computation time management, results storage |
| Backtest visualization | Low-Medium | 1-2 days | Chart rendering in existing dashboard stack |
| Conviction-scaled sizing | Medium | 1-2 days | Kelly fraction calibration |
| Risk-constrained sizing | Low | 0.5 days | Simple extension of existing RiskManager |
| Drawdown-responsive sizing | Medium | 1 day | Real-time drawdown calculation, scaling curve |

**Total estimated effort:** 12-20 days across 3 phases

---

## Integration Points with v1.0

These are the specific v1.0 components that v1.1 features will extend or modify:

| v1.0 Component | How v1.1 Modifies It |
|----------------|---------------------|
| `OpportunityRanker.rank_opportunities()` | Add `signal_score` to OpportunityScore, use composite signal instead of raw rate comparison |
| `FundingMonitor._funding_rates` | Add `_funding_rate_history: dict[str, deque[FundingRateData]]` for rolling window |
| `PositionSizer.calculate_matching_quantity()` | Accept `signal_score` parameter, scale between min and max size based on conviction |
| `RiskManager.check_can_open()` | Add total portfolio exposure check alongside existing per-pair and max-position checks |
| `Orchestrator._autonomous_cycle()` | Pass signal_score through to sizing; apply drawdown scaling |
| `PnLTracker` | Expose real-time drawdown metric for sizing decisions |
| `AppSettings` / config system | New settings for trend windows, signal weights, sizing curves, backtest parameters |
| Dashboard | New backtest page, enhanced opportunity display showing signal scores |

---

## Sources

### Bybit API (HIGH confidence)
- [Bybit Historical Funding Rate API](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) -- 200 records/page, category + symbol required, paginate with endTime
- [Bybit Open Interest API](https://bybit-exchange.github.io/docs/v5/market/open-interest) -- intervalTime parameter, 200 records/page
- [Bybit Kline API](https://bybit-exchange.github.io/docs/v5/market/kline) -- standard OHLCV with category/symbol/interval

### Academic Research (MEDIUM-HIGH confidence)
- [Predictability of Funding Rates (SSRN)](https://papers.ssrn.com/sol3/Delivery.cfm/fe1e91db-33b4-40b5-9564-38425a2495fc-MECA.pdf?abstractid=5576424) -- DAR models outperform no-change baseline; autocorrelation weak beyond 3 lags; mean-reversion (Ornstein-Uhlenbeck) dynamics confirmed
- [Two-Tiered Structure of Funding Rate Markets (MDPI)](https://www.mdpi.com/2227-7390/14/2/346) -- 17% of apparent opportunities lose money after transaction costs
- [Exploring Risk and Return Profiles of Funding Rate Arbitrage (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S2096720925000818) -- CEX vs DEX return profiles

### Industry Practice (MEDIUM confidence)
- [Amberdata: Ultimate Guide to Funding Rate Arbitrage](https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata) -- multi-factor entry signals, OI confirmation, spread analysis
- [QuantJourney: Funding Rates as Hidden Signals](https://quantjourney.substack.com/p/funding-rates-in-crypto-the-hidden) -- statistical properties, mean reversion edge, multi-factor integration
- [MadeInArk: Funding Rate Arbitrage Deep Dive](https://madeinark.org/funding-rate-arbitrage-and-perpetual-futures-the-hidden-yield-strategy-in-cryptocurrency-derivatives-markets/) -- regime-aware returns (52% bull vs 8.7% bear), dynamic sizing Sharpe improvement (1.4 to 2.3)

### Position Sizing (MEDIUM confidence)
- [Kelly Criterion for Crypto Traders (Medium)](https://medium.com/@tmapendembe_28659/kelly-criterion-for-crypto-traders-a-modern-approach-to-volatile-markets-a0cda654caa9) -- fractional Kelly (quarter to half) recommended for crypto
- [Dynamic Position Sizing in Volatile Markets (ITI)](https://internationaltradinginstitute.com/blog/dynamic-position-sizing-and-risk-management-in-volatile-markets/) -- volatility-adjusted sizing framework

### Backtesting Architecture (MEDIUM confidence)
- [Event-Driven Backtesting with Python (QuantStart)](https://www.quantstart.com/articles/Event-Driven-Backtesting-with-Python-Part-I/) -- event queue architecture, lookahead bias prevention
- [Walk-Forward Optimization (QuantInsti)](https://blog.quantinsti.com/walk-forward-optimization-introduction/) -- rolling in-sample/out-of-sample windows
- [Vector vs Event-Based Backtesting (IBKR)](https://www.interactivebrokers.com/campus/ibkr-quant-news/a-practical-breakdown-of-vector-based-vs-event-based-backtesting/) -- hybrid model recommendation

### ccxt Integration (LOW-MEDIUM confidence -- known pagination bugs)
- [ccxt fetchFundingRateHistory Bybit issues](https://github.com/ccxt/ccxt/issues/17854) -- 200 record pagination limitation
- [ccxt fetchOpenInterestHistory issues](https://github.com/ccxt/ccxt/issues/15990) -- since/limit parameter bugs reported
