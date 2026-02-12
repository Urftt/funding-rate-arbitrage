# Domain Pitfalls: Adding Strategy Intelligence to Funding Rate Arbitrage Bot

**Domain:** Backtesting, trend analysis, and dynamic position sizing for crypto funding rate arbitrage
**Researched:** 2026-02-12
**Confidence:** MEDIUM (verified against Bybit API docs, ccxt issues, academic research, and practitioner sources)

> **Scope:** This document covers pitfalls specific to the v1.1 milestone -- adding backtesting, trend analysis, and dynamic position sizing to an already-working v1.0 system. v1.0 pitfalls (delta hedging, fee impact, rate limits, etc.) are documented in the v1.0 research archive and are not repeated here.

---

## Critical Pitfalls

Mistakes that produce false confidence, break the working v1 system, or cause the new intelligence layer to make worse decisions than the simple threshold approach it replaces.

### Pitfall 1: Look-Ahead Bias in Funding Rate Backtesting

**What goes wrong:** The backtester uses information that would not have been available at decision time. For funding rate arbitrage this is especially insidious because the "current" funding rate displayed by Bybit is actually the *predicted next* rate that will be settled, and historical data returns the *settled* rate. If the backtester decides to enter based on the settled rate (which the bot would not have known in advance), results appear far better than reality.

**Why it happens:**
- Bybit's `/v5/market/funding/history` returns rates *after* settlement. At decision time, the bot only has the *predicted* next rate, which can differ materially from the actual settled rate.
- The v1.0 FundingMonitor stores `rate` from the ticker's `fundingRate` field -- this is the *predicted next* rate. Historical data from the funding history endpoint is the *settled* rate. These are different numbers.
- Developers test with "what was the funding rate at time T?" using historical settled data, but the live system decides based on predicted rates. The gap between predicted and settled rates is the look-ahead bias.
- Using future price data to calculate unrealized P&L during backtest (e.g., knowing the exit price at entry time).

**Consequences:**
- Backtest shows the strategy picking winners it could not have picked in real-time.
- Parameter optimization gravitates toward thresholds that only work with perfect foresight.
- v1.1 deployed with "optimized" thresholds performs worse than v1.0's simple approach.
- False confidence in strategy improvements leads to larger position sizing, amplifying losses.

**Prevention:**
- Fetch and store *both* predicted and settled funding rates in historical data. The backtest decision engine must use only the predicted rate (the one that was visible before settlement).
- Implement a strict `as_of` timestamp for every data access in the backtester. No data point should be accessible before its real-world availability time.
- Create a `DataView` abstraction that enforces temporal ordering -- `get_funding_rate(symbol, as_of=T)` must return only data published before T.
- Validate by running the backtest on the last 2 weeks alongside the live paper trading v1.0. If backtest PnL materially differs from paper trading PnL for the same period, look-ahead bias is present.
- Add an assertion: `assert decision_time < data_timestamp` should FAIL (would indicate look-ahead).

**Detection (the "looks done but isn't" check):**
- Backtest win rate is significantly higher than v1.0 paper trading win rate for overlapping periods.
- Optimal entry threshold from backtest is lower than v1.0's 0.03% -- this suggests the backtest "sees" rates that the live system would miss.
- Backtest shows entries *just before* large funding rate spikes (impossible without future knowledge).
- Run A/B: backtest with predicted rates vs settled rates. If results differ by more than 10%, you have bias.

**Phase assignment:** Backtesting engine -- must be solved before any parameter optimization.

---

### Pitfall 2: Overfitting Thresholds to Historical Funding Rate Patterns

**What goes wrong:** Parameter optimization (entry threshold, exit threshold, holding period, sizing multiplier) finds values that perfectly fit historical patterns but fail on new data. Funding rate patterns are non-stationary -- they shift with market regime, exchange competition, and macro conditions.

**Why it happens:**
- Funding rates cluster in regimes: sustained high rates during bull markets, low/negative during bears, and volatile during transitions. Optimizing across a single regime produces regime-specific parameters.
- The parameter space is small (5-10 parameters) but the optimization surface is noisy. Grid search or random search over 6 months of data finds noise, not signal.
- Crypto markets have regime changes every 3-6 months. Parameters optimized on a 6-month window may be optimized for exactly one regime.
- Sharpe ratios above 3.0 and profit factors above 2.0 are red flags for overfitting -- but they look like success.

**Consequences:**
- "Optimized" v1.1 parameters perform worse than v1.0's manually-chosen thresholds in the next market regime.
- Overconfidence in backtest results leads to increased position sizes, magnifying losses.
- Time wasted on parameter tuning that adds zero real-world value.

**Prevention:**
- Use walk-forward validation, not a single train/test split. Split historical data into rolling windows: optimize on 3-month windows, validate on the following 1-month window, advance 1 month, repeat.
- Limit the number of optimizable parameters. v1.0 has 2 (entry rate, exit rate). v1.1 should have at most 4-5 total.
- Require out-of-sample improvement over v1.0 baseline on *every* walk-forward fold, not just on average.
- Apply parameter stability check: if optimal parameters shift by more than 30% between adjacent windows, the optimization is fitting noise.
- Set hard boundaries: Sharpe > 3.0 in backtest should trigger an overfitting warning, not celebration.
- Monte Carlo shuffle test: randomize entry/exit timing and check if "optimized" parameters still outperform. If they don't survive randomization, they're overfit.

**Detection:**
- Backtest Sharpe > 3.0 or profit factor > 2.0 -- almost certainly overfit.
- Parameters that are radically different from v1.0's values (e.g., entry threshold of 0.001% vs v1.0's 0.03%).
- Performance degrades sharply when test period shifts by even 1 month.
- Parameters that "work" change with each re-optimization run.

**Phase assignment:** Backtesting engine validation -- must be tested before any parameters are deployed.

---

### Pitfall 3: Breaking the Working v1.0 System During Integration

**What goes wrong:** Adding the intelligence layer changes the decision path in the orchestrator's `_autonomous_cycle()`, and a bug in the new code causes the existing paper/live trading to malfunction. The v1.0 system works. The worst outcome of v1.1 is making it stop working.

**Why it happens:**
- The orchestrator directly calls `self._ranker.rank_opportunities()` and `self._close_unprofitable_positions()`. New intelligence code must intercept or augment these decision points without breaking the existing flow.
- v1.0's PositionSizer has a clean interface (`calculate_matching_quantity`). Dynamic sizing must extend, not replace, this interface.
- The OpportunityRanker scores by `net_yield_per_period`. Trend analysis adds new scoring dimensions that could accidentally suppress all opportunities or override risk limits.
- RuntimeConfig handles dashboard overrides. New strategy parameters need to integrate without breaking existing config flow.
- In-memory position tracking (`PositionManager._positions`) has no persistence. If the backtester accidentally shares state with live components, positions could be corrupted.

**Consequences:**
- Bot stops opening positions (over-cautious intelligence layer).
- Bot opens positions it shouldn't (intelligence layer overrides risk limits).
- Paper trading P&L tracking breaks (new code mutates shared PnLTracker state).
- Dashboard shows incorrect data (new analytics interfere with existing metrics).
- Emergency stop fails because new code path doesn't respect `_running` flag.

**Prevention:**
- **Strategy pattern:** Create a `StrategyEngine` interface with two implementations: `SimpleThresholdStrategy` (v1.0 behavior, extracted from current orchestrator) and `IntelligentStrategy` (v1.1 with trend analysis). The orchestrator calls `strategy.evaluate(opportunities)` instead of inline logic. v1.0 behavior must be preservable by switching strategy implementations.
- **Feature flag:** Add `strategy_mode: Literal["simple", "intelligent"] = "simple"` to config. v1.0 behavior is the default. v1.1 must be opt-in.
- **Isolation:** Backtesting engine must NEVER share instances with live components. No shared PositionManager, PnLTracker, or TickerService between backtest and live/paper.
- **Regression test suite:** Before v1.1, extract v1.0 integration tests as a regression suite. Every v1.1 change must pass the v1.0 regression tests.
- **Read-only intelligence:** The trend analysis and sizing layer should only *advise* (return scores/sizes); the existing orchestrator/risk manager should remain the sole decision maker. Never let the intelligence layer directly call `open_position()` or `close_position()`.

**Detection:**
- v1.0 regression tests fail after v1.1 changes.
- Paper trading with `strategy_mode=simple` behaves differently than v1.0.
- Dashboard metrics diverge from expected values with intelligence layer disabled.
- Position count exceeds `max_simultaneous_positions` (intelligence bypassed risk check).

**Phase assignment:** First phase of v1.1 -- extract strategy interface BEFORE adding intelligence.

---

### Pitfall 4: Survivorship Bias in Historical Funding Rate Data

**What goes wrong:** Backtesting only uses pairs that currently exist on Bybit. Pairs that were delisted, rug-pulled, or had their perpetual contracts removed are absent from historical data. This makes the strategy appear more profitable because it never encounters the losing scenarios of entering positions on pairs that subsequently failed.

**Why it happens:**
- Bybit's `/v5/market/funding/history` only returns data for currently listed symbols. Delisted symbols return empty results.
- The v1.0 `fetch_perpetual_symbols()` method filters for currently active `linear + swap` markets. Historical analysis using this list misses pairs that existed 6 months ago but are now gone.
- Crypto markets delist 5-15% of perpetual contracts per year. These are disproportionately the ones with extreme funding rates (which would have been highly ranked by the opportunity ranker).
- The most dangerous pairs for funding rate arbitrage (extreme rates on illiquid tokens) are the most likely to be delisted.

**Consequences:**
- Backtest overestimates returns by 5-20% because it never simulates entering (and being trapped in) pairs that were subsequently delisted.
- Optimal parameters are biased toward aggressive entry on high-rate pairs -- exactly the ones most likely to be delisted.
- Strategy appears to work on all pair counts, but in reality, some percentage would have resulted in locked positions or forced exits at bad prices.

**Prevention:**
- Build a historical pair registry: periodically snapshot all available perpetual symbols (weekly cron job) and store them. Include symbol, first_seen, last_seen, is_active.
- For backtesting, include pairs that existed at each historical point, even if they are now delisted. Mark delisted pair entries in backtest results.
- If historical data for delisted pairs is unavailable from Bybit API, apply a survivorship bias adjustment: assume X% of high-rate opportunities would have resulted in adverse exits (use 5-10% as a conservative estimate based on crypto delisting rates).
- Filter by CoinGlass or similar third-party data sources that archive historical funding rates for delisted pairs.
- At minimum, document which pairs are excluded and flag the bias in backtest reports.

**Detection:**
- Compare the pair count in backtest vs the pair count in v1.0 live data. If backtest has fewer pairs, survivorship bias is likely.
- Check if any top-performing backtest pairs are suspiciously "clean" -- no periods of extreme negative funding, no liquidity dips, no sudden exits.
- Cross-reference backtest pair list against Bybit delisting announcements.

**Phase assignment:** Historical data collection phase -- must be addressed when building the data pipeline.

---

### Pitfall 5: Funding Rate Trend Analysis Producing False Signals

**What goes wrong:** Trend analysis (moving averages, momentum indicators on funding rates) generates entry/exit signals that are worse than the v1.0 simple threshold. Funding rates are not prices -- they are periodic settlement values that behave differently from price time series. Standard technical analysis indicators produce excessive false signals.

**Why it happens:**
- Funding rates update every 8 hours (3 data points per day). Standard moving averages need 20+ data points for meaningful signals, meaning a 20-period MA spans 6.7 days. By the time the MA confirms a trend, the opportunity is often over.
- Funding rates are mean-reverting by design (the funding mechanism pushes futures toward spot price). Trend-following indicators are designed for trending series, not mean-reverting ones.
- Extreme funding rates (>0.1%/8h) are often short-lived spikes caused by liquidation cascades or event-driven positioning. Trend indicators smooth these out, causing the bot to miss profitable spikes while entering on lagging signals.
- Rate changes between 8h periods can be abrupt and discontinuous (e.g., 0.05% to -0.02% in one period). Indicators assuming smooth data produce meaningless crossovers.

**Consequences:**
- Trend analysis triggers entries *after* the profitable period has passed (lagging).
- Trend analysis filters *out* profitable spike opportunities that v1.0 would have captured.
- Net result: fewer trades, worse timing, lower returns than v1.0's simple threshold.
- Complexity added without benefit, making the system harder to debug and maintain.

**Prevention:**
- Do NOT apply standard price-based indicators (RSI, MACD, Bollinger Bands) directly to funding rates without modification. Funding rates are structurally different from price series.
- Focus on regime detection rather than trend following: is the market in a "high funding" regime (sustained rates > threshold) or "low funding" regime? Use regime classification (e.g., Hidden Markov Model or simple threshold-based state machine), not moving averages.
- If using moving averages, use short windows (3-5 periods = 1-1.7 days) and compare against v1.0 baseline on every test.
- Consider rate-of-change rather than absolute trends: "funding rate is accelerating upward" is more actionable than "funding rate is above its 20-period MA."
- Academic research supports funding rate predictability using DAR (double autoregressive) models, but notes predictability is "time-varying." Simple approaches may outperform complex ones.
- Always benchmark against v1.0: any trend signal must demonstrably outperform simple thresholding on out-of-sample data.

**Detection:**
- Trade count drops significantly compared to v1.0 (trend filter is too conservative).
- Average entry timing is later than v1.0 (lagging signal).
- Win rate improves but total profit drops (catching fewer but "surer" trades that don't compensate for missed opportunities).
- Trend signals are highly correlated with each other across pairs (all pairs enter/exit together, reducing diversification).

**Phase assignment:** Trend analysis development -- must be validated against v1.0 baseline before integration.

---

## Moderate Pitfalls

Significant issues that degrade backtest accuracy or strategy performance but are recoverable.

### Pitfall 6: Unrealistic Fill Assumptions in Backtesting

**What goes wrong:** The backtester assumes instant fills at exact prices (like v1.0's PaperExecutor with 5bps slippage). In reality, during high-funding-rate periods (when the bot would be most active), spreads widen, slippage increases, and partial fills occur. Backtest overstates achievable returns.

**Why it happens:**
- v1.0 PaperExecutor uses a fixed `_SLIPPAGE = Decimal("0.0005")` (5bps). During volatile periods when funding rates spike, actual slippage can be 10-50bps.
- Backtest assumes both legs (spot + perp) fill simultaneously at the same effective price. In reality, the spot-perp basis can shift between leg executions.
- For less liquid pairs (which often have the highest funding rates), order book depth may not support the backtest's assumed position size without market impact.
- Funding rate settlement times (00:00, 08:00, 16:00 UTC) are high-activity periods with elevated spreads.

**Prevention:**
- Model slippage as a function of volume and volatility, not a fixed constant. Use `slippage = base_slippage * (1 + volatility_multiplier)` where volatility_multiplier increases during high-funding periods.
- For each backtest trade, check whether the assumed position size is realistic given historical volume. If position size > 1% of the pair's 24h volume, flag as potentially unrealistic.
- Add a "conservative" backtest mode that doubles slippage and fees -- if the strategy is still profitable under conservative assumptions, it's more likely to work live.
- Fetch historical OHLCV data (available via Bybit API, 1000 candles per request) to estimate spreads during the backtest period.

**Detection:**
- Backtest profit per trade is significantly higher than v1.0 paper trading profit per trade.
- Backtest shows profitable trades on pairs where v1.0 paper trading had negative slippage impact.
- Average slippage in backtest < 5bps during periods when live spreads exceeded 10bps.

**Phase assignment:** Backtesting engine -- realistic execution simulation.

---

### Pitfall 7: Bybit API Rate Limits During Historical Data Collection

**What goes wrong:** Fetching historical funding rates for 200+ perpetual pairs exhausts API rate limits, causing data collection to fail partway through or take excessively long. The bot gets IP-banned (403) during data collection, which also blocks live trading operations if sharing the same IP.

**Why it happens:**
- Bybit allows 600 requests per 5-second window per IP (120/s). The funding rate history endpoint returns max 200 records per request. For 200 pairs over 6 months (540 8-hour periods each), that's 200 * 3 = 600 requests minimum (200 records per request, ~2.7 requests per pair for 6 months).
- If also fetching OHLCV data (1000 candles per request), the request count multiplies.
- ccxt's `enableRateLimit: True` provides basic throttling but may not account for burst patterns during bulk historical data fetches.
- Running data collection while the live bot is also running shares the same API key rate limit pool (Bybit rate limits are per-UID for authenticated endpoints, per-IP for public endpoints).

**Consequences:**
- Data collection fails midway, producing incomplete historical datasets (some pairs have full history, others are partial).
- If sharing IP with live bot: live trading API calls fail, potentially unable to close positions during emergencies.
- 403 ban lasts at least 10 minutes, during which all API access is blocked.

**Prevention:**
- Historical data collection MUST run on a separate schedule from live trading, ideally as a standalone script.
- Implement explicit rate limiting: max 50 requests per 5 seconds for historical data (well under the 600/5s limit to leave headroom for live operations).
- Use public endpoints for funding rate history (no auth required, IP-limited only). Run from a separate IP if possible.
- Implement incremental collection: store last-fetched timestamp per pair, only fetch new data on subsequent runs.
- Add progress tracking and resumability: if collection is interrupted, restart from where it left off.
- Cache aggressively: funding rates are immutable once settled. Never re-fetch data you already have.
- Batch by symbol: fetch all history for one pair before moving to the next, so partial collection still gives complete data for some pairs.

**Detection:**
- API error logs show 429 or 403 responses during data collection.
- Historical dataset has gaps (some pairs have data, others don't).
- Live trading operations slow down or fail during data collection runs.
- Data collection takes more than 30 minutes for a 6-month dataset.

**Phase assignment:** Historical data pipeline -- must be solved before backtesting can begin.

---

### Pitfall 8: Dynamic Position Sizing Based on Backtested Returns

**What goes wrong:** The dynamic sizing model uses backtest-derived metrics (expected return, Sharpe ratio) to scale position sizes. Because backtest returns are inflated by the biases above (look-ahead, survivorship, unrealistic fills), position sizes are too large. The system over-allocates to strategies/pairs that appeared profitable in backtest but aren't live.

**Why it happens:**
- Conviction-based sizing ("higher rate = larger position") seems logical, but the relationship between funding rate magnitude and trade profitability is noisy.
- Historical funding rates show that extreme rates (>0.1%/8h) are often followed by rapid reversals. Sizing up on extreme rates increases exposure right when the rate is most likely to mean-revert.
- If sizing model uses backtest volatility estimates, it underestimates real volatility (backtest doesn't capture execution risk, gap risk, or sudden rate changes).
- Kelly criterion or similar optimal sizing formulas require accurate win rate and payoff estimates -- backtest-derived estimates are biased upward.

**Consequences:**
- Over-sized positions during rate reversals cause larger losses than v1.0's fixed sizing.
- Concentrated exposure to a few "high conviction" pairs reduces the diversification benefit of multi-pair trading.
- Margin utilization increases, reducing buffer for emergency situations.
- The "intelligent" sizing performs worse than v1.0's simple fixed $1000 per position.

**Prevention:**
- Start with conservative scaling: v1.1 dynamic sizing should range from 0.5x to 1.5x of v1.0's fixed size, not 0.1x to 5x.
- Cap maximum position size at v1.0's `max_position_size_per_pair` ($1000). Dynamic sizing can only *reduce* from the max, never exceed it. Let the existing RiskManager enforce the ceiling.
- Use rate of change (is the funding rate increasing or decreasing?) rather than absolute level for sizing decisions.
- Apply sizing half-life: increase size gradually over multiple funding periods of sustained high rates, rather than jumping to max on the first high rate observation.
- Decouple sizing from backtest returns entirely for initial deployment. Use simple heuristics (rate percentile across all pairs) instead of model-derived conviction scores.
- Test dynamic sizing with historical data where positions are forced to use the same fixed slippage and fee assumptions as v1.0, to ensure the sizing improvement is real.

**Detection:**
- Average position size is significantly larger than v1.0's fixed size.
- Position size variance is high (some positions 5x others).
- Largest losses come from the largest positions.
- Portfolio PnL is more volatile than v1.0 despite supposedly better strategy.

**Phase assignment:** Dynamic sizing development -- must be bounded by existing risk limits.

---

### Pitfall 9: Correlation Underestimation Across Funding Rate Pairs

**What goes wrong:** The bot opens multiple large positions across "different" pairs, but during market stress, funding rates across all pairs move together (correlation -> 1.0). What looked like diversified exposure becomes concentrated directional risk.

**Why it happens:**
- Crypto funding rates are driven by aggregate market sentiment. During bull markets, most pairs have high positive rates. During corrections, most rates collapse simultaneously.
- The current v1.0 RiskManager checks `max_simultaneous_positions` (5) and `max_position_size_per_pair` ($1000). It does NOT check correlation between open positions.
- If dynamic sizing increases sizes on "high conviction" pairs, and all of them are correlated (BTC/USDT, ETH/USDT, SOL/USDT all have similar funding rate patterns), the effective portfolio risk is much larger than the sum of individual position risks suggests.
- Altcoin funding rates are heavily influenced by BTC. Having 5 positions in different altcoins provides less diversification than it appears.

**Consequences:**
- Simultaneous drawdown across all positions during market correction.
- Margin utilization spikes as all pairs move adversely at once.
- Exit becomes difficult as liquidity dries up simultaneously across all pairs.
- Portfolio max drawdown is much larger than backtest predicted (backtest tested pairs individually).

**Prevention:**
- Add a portfolio-level exposure check to RiskManager: total portfolio notional must not exceed X% of available capital, regardless of per-pair limits.
- Group pairs by underlying correlation (BTC-correlated, ETH-ecosystem, stablecoin pairs). Limit exposure per group.
- During dynamic sizing, reduce individual position sizes when multiple positions are open: `effective_size = base_size * (1 / sqrt(num_open_positions))` as a simple diversification discount.
- Monitor rolling correlation between open position funding rates. If correlation exceeds 0.8, reduce total exposure.
- v1.0's fixed size of $1000 across 5 positions = $5000 max. v1.1 should not exceed this without explicit portfolio-level validation.

**Detection:**
- All open positions have similar funding rate levels (all high or all low).
- Portfolio PnL shows large synchronized moves (all positions profit/loss together).
- Historical correlation analysis shows >0.7 average correlation between open pairs' funding rates.
- Max drawdown in live trading is >2x the backtest-predicted max drawdown.

**Phase assignment:** Dynamic sizing and risk management -- extend RiskManager before enabling dynamic sizing.

---

### Pitfall 10: Historical Data Gaps and Inconsistencies

**What goes wrong:** Bybit historical funding rate data has gaps, inconsistent intervals, and timestamp precision issues that produce incorrect backtest results. The backtester treats data as complete and evenly spaced when it isn't.

**Why it happens:**
- Bybit changed funding intervals for some pairs over time (some moved from 8h to 4h to 1h). Historical data mixes intervals without clear markers.
- Exchange maintenance windows sometimes skip funding settlements. These missing data points appear as gaps.
- The API returns 200 records per request with timestamp-based pagination. Off-by-one errors in pagination logic cause duplicated or missing records (documented in ccxt issue #15990).
- Some pairs have funding rate history starting from their listing date, not from the backtest start date. Backtest must handle varying data availability per pair.
- Timezone handling: Bybit timestamps are in milliseconds, but funding settlements occur at fixed UTC times. Misalignment between data timestamps and settlement times causes incorrect period assignments.

**Consequences:**
- Backtest calculates incorrect number of funding periods (missing gaps = fewer payments than expected).
- Mixed interval data causes incorrect annualization (8h data treated as 4h or vice versa).
- Pagination bugs produce duplicated funding payments (inflating backtest returns) or missing payments (deflating returns).
- Backtest results vary depending on data collection timing, making results non-reproducible.

**Prevention:**
- After fetching data, validate: sort by timestamp, check for duplicates (same timestamp+symbol), verify consistent interval spacing within each pair.
- Store `interval_hours` per data point (from `fundingIntervalHour` field, already in v1.0's FundingRateData model). Use per-record interval, not a global assumption.
- Flag gaps: if time between consecutive records exceeds `1.5 * expected_interval`, mark as a gap. Don't interpolate -- the backtest should skip gap periods for that pair.
- ccxt pagination workaround: provide both `since` and `until` parameters explicitly (not just `since` + `limit`, per ccxt issue #15990 fix). Verify record count matches expected count for the time range.
- Add a data integrity report to the data pipeline: for each pair, output record count, expected count, gap count, duplicate count. Fail loudly if discrepancies exceed 5%.
- Store raw API responses alongside parsed data for auditability.

**Detection:**
- Data record count doesn't match expected count (time_range / interval_hours).
- Duplicate timestamps in the dataset.
- Annualized yield calculations produce implausible values (>500% or <-100%).
- Backtest results change when data is re-fetched (non-deterministic).

**Phase assignment:** Historical data pipeline -- data quality checks before backtesting.

---

## Minor Pitfalls

Issues that cause confusion or inefficiency but are unlikely to produce material losses.

### Pitfall 11: Backtester Performance -- Slow Iteration Cycles

**What goes wrong:** The backtesting engine is too slow for interactive parameter exploration. Running a 6-month backtest across 200 pairs takes hours, making walk-forward validation impractical and reducing research velocity.

**Why it happens:**
- Using Decimal arithmetic (v1.0 standard) for all backtest calculations. Decimal is 10-100x slower than float for arithmetic operations.
- Simulating the full orchestrator cycle (scan-rank-decide-execute) for each 8h period across 200 pairs.
- Loading historical data from API on every run instead of caching locally.
- Not vectorizing calculations (pure Python loops instead of pandas/numpy for analysis).

**Prevention:**
- Use float for backtest calculations (acceptable for simulation) and Decimal only for live trading. This is a deliberate exception to v1.0's "Decimal everywhere" rule -- backtesting is analysis, not execution.
- Pre-load all historical data into memory at backtest start. A 6-month dataset for 200 pairs at 8h intervals is ~200 * 540 = 108,000 records -- trivially fits in memory.
- Cache historical data locally (SQLite or Parquet files). Only fetch from API for new data since last collection.
- Profile before optimizing: the bottleneck is likely data loading or fee calculation, not the decision logic.

**Phase assignment:** Backtesting engine architecture.

---

### Pitfall 12: Conflating Strategy Improvement with Market Regime Change

**What goes wrong:** v1.1 is deployed during a favorable market regime, and the team attributes the improvement to the intelligence layer rather than to market conditions. Or conversely, v1.1 is deployed during an unfavorable regime, and the intelligence layer is abandoned despite being genuinely better.

**Prevention:**
- Always run v1.0 baseline alongside v1.1 (even if only in paper mode). Compare performance on the same time period.
- Use risk-adjusted metrics (Sharpe ratio, Sortino ratio) rather than absolute returns for comparison.
- Require a minimum sample size (50+ trades) before drawing conclusions about v1.1 vs v1.0.
- Document market conditions during evaluation periods (BTC price trend, overall market sentiment, average funding rates).

**Phase assignment:** Post-deployment evaluation -- define evaluation criteria before deployment.

---

### Pitfall 13: Strategy State Management Between Restarts

**What goes wrong:** The trend analysis module maintains state (moving averages, regime classification, historical windows) in memory. When the bot restarts, this state is lost, causing incorrect signals until the state is rebuilt. v1.0 doesn't have this problem because it's stateless (each cycle makes decisions based only on current data).

**Prevention:**
- Design trend analysis as a pure function of historical data: `calculate_signal(historical_rates[-N:])` rather than maintaining running state.
- If running state is necessary for performance, implement state serialization (save to disk on each cycle, load on restart).
- On restart, the intelligence layer should either (a) load saved state, or (b) fall back to v1.0 simple threshold behavior until enough data accumulates.
- Add a "warmup period" concept: strategy reports LOW confidence for the first N periods after restart.

**Phase assignment:** Trend analysis development -- state management design.

---

### Pitfall 14: Backtesting the Wrong Baseline

**What goes wrong:** The backtest compares v1.1 against a theoretical "perfect" strategy or against "buy and hold BTC" rather than against the actual v1.0 behavior. v1.1 may look good against buy-and-hold but be worse than v1.0.

**Prevention:**
- The first thing the backtest framework should produce is a v1.0 baseline simulation: apply v1.0's exact logic (simple threshold entry at 0.03%, exit at 0.01%, fixed $1000 sizing, max 5 positions) to the historical data.
- All v1.1 comparisons must be against this v1.0 baseline, not against "no trading" or "buy and hold."
- Implement `SimpleThresholdStrategy` as the first backtesting strategy. Verify it produces results consistent with v1.0 paper trading before building `IntelligentStrategy`.

**Phase assignment:** Backtesting engine -- implement v1.0 baseline strategy first.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Severity | Mitigation |
|---|---|---|---|
| Historical data pipeline | API rate limits (#7) | Critical | Separate script, rate throttling, incremental collection |
| Historical data pipeline | Data gaps/inconsistencies (#10) | Moderate | Validation pipeline, gap detection, interval tracking |
| Historical data pipeline | Survivorship bias (#4) | Critical | Pair registry, delisting tracking |
| Backtesting engine | Look-ahead bias (#1) | Critical | `as_of` temporal enforcement, predicted vs settled rate separation |
| Backtesting engine | Unrealistic fills (#6) | Moderate | Variable slippage model, volume-based validation |
| Backtesting engine | Wrong baseline (#14) | Minor | Implement v1.0 baseline first |
| Backtesting engine | Slow iteration (#11) | Minor | Float for backtest, local data cache |
| Parameter optimization | Overfitting (#2) | Critical | Walk-forward validation, parameter stability checks |
| Trend analysis | False signals (#5) | Critical | Mean-reversion-aware indicators, v1.0 benchmark |
| Trend analysis | State management (#13) | Minor | Pure functions or serializable state |
| Dynamic sizing | Backtest-based sizing (#8) | Moderate | Conservative bounds, cap at v1.0 max |
| Dynamic sizing | Correlation risk (#9) | Moderate | Portfolio-level exposure limits, correlation monitoring |
| Integration | Breaking v1.0 (#3) | Critical | Strategy pattern, feature flags, regression tests |
| Evaluation | Regime conflation (#12) | Minor | Parallel v1.0 baseline, risk-adjusted metrics |

---

## The Meta-Pitfall: Complexity Without Improvement

The single most likely failure mode of v1.1 is adding complexity that makes the system harder to understand, debug, and maintain without actually improving performance over v1.0's simple threshold approach.

**The v1.0 system works.** It has a clear, auditable decision process: scan rates, rank by net yield, enter above threshold, exit below threshold. Every added component (trend analysis, dynamic sizing, optimized thresholds) must demonstrably improve on this baseline.

**Decision framework for every v1.1 feature:**
1. Does it beat v1.0 on out-of-sample data?
2. Does it beat v1.0 across multiple market regimes?
3. Is the improvement large enough to justify the added complexity?
4. Can it be disabled instantly to fall back to v1.0 behavior?

If any answer is "no" or "not sure," don't ship it.

---

## Sources

### Bybit Official Documentation
- [Bybit Funding Rate History API](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) -- endpoint constraints, 200 records/request limit, timestamp parameters -- HIGH confidence
- [Bybit Rate Limits](https://bybit-exchange.github.io/docs/v5/rate-limit) -- 600 requests/5s per IP, per-UID limits by endpoint category -- HIGH confidence

### ccxt Library Issues
- [ccxt #15990: Bybit fetchFundingRateHistory since/limit bug](https://github.com/ccxt/ccxt/issues/15990) -- pagination requires explicit endTime -- HIGH confidence
- [ccxt #17854: Bug in fetchOpenInterestHistory/fetchFundingRateHistory for Bybit](https://github.com/ccxt/ccxt/issues/17854) -- 200 record limit per call -- HIGH confidence

### Backtesting Methodology
- [Starqube: 7 Deadly Sins of Backtesting](https://starqube.com/backtesting-investment-strategies/) -- overfitting, look-ahead bias, survivorship bias -- MEDIUM confidence
- [LuxAlgo: Backtesting Traps](https://www.luxalgo.com/blog/backtesting-traps-common-errors-to-avoid/) -- common errors, detection methods -- MEDIUM confidence
- [Interactive Brokers: Walk-Forward Analysis](https://www.interactivebrokers.com/campus/ibkr-quant-news/the-future-of-backtesting-a-deep-dive-into-walk-forward-analysis/) -- WFO methodology -- MEDIUM confidence
- [Adventures of Greg: Survivorship Bias in Backtesting](http://adventuresofgreg.com/blog/2026/01/14/survivorship-bias-backtesting-avoiding-traps/) -- practical crypto examples -- MEDIUM confidence
- [Portfolio Optimization: Dangers of Backtesting](https://bookdown.org/palomar/portfoliooptimizationbook/8.3-dangers-backtesting.html) -- academic treatment of biases -- MEDIUM confidence

### Funding Rate Research
- [QuantJourney: Funding Rates in Crypto](https://quantjourney.substack.com/p/funding-rates-in-crypto-the-hidden) -- signal interpretation, false positives, regime changes -- MEDIUM confidence
- [Amberdata: Ultimate Guide to Funding Rate Arbitrage](https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata) -- execution challenges, volatility impact -- MEDIUM confidence
- [SSRN: Predictability of Funding Rates](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5576424) -- DAR models, time-varying predictability -- MEDIUM confidence
- [ScienceDirect: Risk and Return Profiles of Funding Rate Arbitrage](https://www.sciencedirect.com/science/article/pii/S2096720925000818) -- CEX correlation, returns analysis -- MEDIUM confidence
- [CoinAPI: Historical Data for Perpetual Futures](https://www.coinapi.io/blog/historical-data-for-perpetual-futures) -- data gaps, missing data, format challenges -- MEDIUM confidence

### Crypto Trading Bot Practices
- [Gate.com: Crypto Trading Bot Pitfalls](https://www.gate.com/news/detail/13225882) -- overoptimization, complexity risks -- LOW confidence
- [Altrady: Dynamic Position Sizing Tips](https://www.altrady.com/blog/crypto-paper-trading/risk-management-seven-tips) -- correlation creep, volatility-adjusted sizing -- LOW confidence
- [3Commas: Backtesting AI Crypto Trading](https://3commas.io/blog/comprehensive-2025-guide-to-backtesting-ai-trading) -- general best practices -- LOW confidence

### Codebase Analysis
- v1.0 source code reviewed: orchestrator.py, config.py, position/sizing.py, market_data/opportunity_ranker.py, risk/manager.py, models.py, exchange/bybit_client.py, market_data/funding_monitor.py, pnl/tracker.py, analytics/metrics.py, execution/paper_executor.py, position/manager.py -- HIGH confidence for integration pitfall analysis
