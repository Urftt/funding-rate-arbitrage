# Domain Pitfalls: Strategy Discovery, Pair Analysis, and Enhanced Backtesting Visualization

**Domain:** Trading strategy discovery tools, per-pair profitability dashboards, and trade-level backtest visualization for crypto funding rate arbitrage
**Researched:** 2026-02-13
**Confidence:** MEDIUM-HIGH (verified against Bybit API docs, existing codebase analysis, backtesting methodology literature, and visualization research)

> **Scope:** This document covers pitfalls specific to the v1.2 milestone -- adding Pair Explorer, Trade Replay, Strategy Builder, and Decision View to the existing v1.0/v1.1 system. v1.1 pitfalls (look-ahead bias, overfitting, survivorship bias, false trend signals, etc.) are documented in the v1.1 research archive and are referenced but not repeated here. This document focuses on NEW pitfalls introduced by strategy discovery, profitability visualization, and user-facing analysis features.

> **Primary risk:** A beginner user makes bad trading decisions based on misleading analysis. Every pitfall below is evaluated through that lens.

---

## Critical Pitfalls

Mistakes that directly mislead the user into believing a strategy is profitable when it is not, or that cause them to deploy capital based on false confidence.

### Pitfall 1: Annualized Yield Illusion -- Displaying APY From Short-Period Rates

**What goes wrong:** The Pair Explorer and Decision View display annualized yield figures (e.g., "87% APY") derived from a single 8-hour funding rate snapshot or a short recent period. A beginner sees "87% APY" and concludes the pair is highly profitable, when in reality the rate is transient and fees consume most of the yield over realistic holding periods.

**Why it happens:**
- The existing `OpportunityRanker` computes `annualized_yield = net_yield_per_period * periods_per_year` where `periods_per_year = 8760 / interval_hours`. A 0.01% per-8h rate becomes 10.95% annualized, and a 0.08% rate becomes 87.6% annualized.
- This annualization assumes the rate stays constant for an entire year, which never happens. Funding rates are highly volatile with a mean-reverting structure.
- Beginners anchor on the largest number displayed. "87% APY" is psychologically far more compelling than "0.08% per 8 hours" even though they represent the same mathematical reality.
- The annualized figure ignores that most positions are held for 3-30 funding periods (1-10 days), not 365 days. Over a 3-period hold, a 0.08% rate yields 0.24% gross, minus ~0.31% round-trip fees = net LOSS.

**Consequences:**
- User enters positions on pairs with high annualized yield that are actually unprofitable after fees for realistic holding periods.
- User develops false confidence in the strategy, seeing "double-digit annual returns" everywhere.
- When positions lose money, user concludes the bot is broken rather than understanding the display was misleading.

**Prevention:**
- **Never display annualized yield as the primary metric.** Show "net yield per period" (after amortized fees) as the main number.
- **Always show break-even context:** "Needs X consecutive periods at this rate to cover round-trip fees." The current `FeeCalculator.min_funding_rate_for_breakeven()` already computes this -- surface it prominently.
- **Display holding-period returns**, not annualized: "At this rate for 3 periods: -0.07% | 10 periods: +0.49% | 30 periods: +2.09%"
- **Color-code by net profitability** after fees, not by raw rate magnitude. A 0.03% rate that persists for 30 days is more profitable than a 0.1% rate that reverses after 2 periods.
- **Add a volatility indicator** next to yield: "This rate has changed by more than 50% in the last 7 days" prevents false stability assumptions.

**Detection:**
- User consistently enters positions that lose money on pairs shown as "high yield" in the dashboard.
- Pairs ranked #1 by annualized yield rarely appear in the top 5 by actual backtest profitability.
- Win rate on high-annualized-yield pairs is lower than average.

**Phase assignment:** Pair Explorer and Decision View -- must be addressed in the first visualization phase. This is THE most dangerous pitfall for a beginner.

---

### Pitfall 2: Survivorship-Biased Pair Selection via Current Market Cap Ranking

**What goes wrong:** The Pair Explorer shows "top 20 pairs by market cap" using current exchange data. The user backtests these pairs historically and sees strong performance, not realizing that selecting today's winners and testing them historically guarantees good-looking results. Pairs that crashed, were delisted, or lost market cap are invisible.

**Why it happens:**
- The existing `pair_selector.py` uses `select_top_pairs(funding_rates, count=20)` sorted by current `volume_24h`. Any historical analysis of these 20 pairs inherits survivorship bias because they are, by definition, the pairs that survived and grew.
- Backtesting research shows this can inflate returns by 50-100%. One study demonstrated a strategy showing 4x less profit, 15% more drawdown, and profit factor nearly halved when properly accounting for survivorship bias (Concretum Group, 2025).
- Crypto is especially vulnerable: 5-15% of perpetual contracts are delisted annually, and the delisted ones disproportionately had extreme funding rates (high signal, high risk).

**Consequences:**
- User backtests "BTC, ETH, SOL" and sees profits, assumes strategy works, not realizing that 3 pairs that went to zero in 2025 would have been in the top 20 when selected historically.
- Strategy Builder results are systematically biased upward. Every configuration looks better than it should.
- User deploys with false confidence, encounters a pair that crashes, and suffers unexpected losses.

**Prevention:**
- **Show survivorship bias warning** when backtesting current top pairs: "These are today's top pairs. In January 2025, the top 20 list included X pairs that are no longer actively traded."
- **Implement point-in-time pair selection** for backtesting: when the user backtests June 2025, use the pairs that were in the top 20 AS OF June 2025, not today.
- **Store historical pair snapshots** in the existing `tracked_pairs` table. Add a `snapshot_date` column. Weekly cron job already exists for pair re-evaluation (`pair_reeval_interval_hours = 168`). Snapshot the list at each re-evaluation.
- **Display "pair tenure"** in the explorer: "This pair has been continuously tracked for X months." Short tenure = more uncertainty.
- **If point-in-time data is unavailable**, show a disclaimer: "Backtest results may be inflated by survivorship bias. Pairs were selected using current market cap, not historical."

**Detection:**
- Backtest profitability is significantly higher than live paper trading results for the same period.
- All tested pairs show positive returns (unrealistic -- some should show losses).
- The pair list hasn't changed in months despite market cap shifts.

**Phase assignment:** Pair Explorer setup and Strategy Builder -- must be addressed when implementing historical pair browsing. Can be partially mitigated with disclaimers in Phase 1, fully solved in a later phase with historical snapshots.

---

### Pitfall 3: Aggregate Metrics Hiding Per-Trade Reality in Backtest Results

**What goes wrong:** The current backtest output shows aggregate `BacktestMetrics` (total trades, net PnL, Sharpe ratio, win rate) and an equity curve. Adding Trade Replay without surfacing the RIGHT per-trade details can make bad strategies look acceptable. A strategy with 60% win rate and positive net PnL can still have a catastrophic risk profile if the losing trades are 5x larger than winners.

**Why it happens:**
- Aggregate win rate is the most psychologically salient metric for beginners. "60% win rate" sounds great. But if average winner = $2 and average loser = $10, expected value per trade is negative.
- The equity curve smooths noise through its line chart presentation. A strategy that has a smooth upward equity curve with a sudden cliff at the end looks almost identical to a consistently good strategy when the cliff is off-screen or at the tail.
- The current `BacktestMetrics` has `net_pnl`, `total_fees`, `total_funding`, `sharpe_ratio`, `max_drawdown`, `win_rate`. Missing: average win vs. average loss, profit factor, maximum consecutive losses, time in drawdown, holding period distribution.
- When adding trade-level detail, showing a long table of individual trades creates information overload. Users scan for confirming evidence (green rows) and skip the important patterns (clusters of losses, long drawdown periods).

**Consequences:**
- User sees "Sharpe 2.1, 65% win rate, $340 net profit" and concludes the strategy works.
- They miss that the strategy had a 3-week drawdown period, 12 consecutive losses in March, and the entire profit came from 2 lucky trades on a single pair.
- User deploys, hits the inevitable losing streak, and abandons the strategy at exactly the wrong time.

**Prevention:**
- **Always show profit factor** (gross wins / gross losses). Profit factor < 1.0 = losing strategy regardless of win rate. This is the single most honest metric.
- **Show average winner vs. average loser** side by side. If avg_loser > 2x avg_winner, flag it.
- **Show maximum consecutive losses** and **maximum drawdown duration** (not just depth). A 3-week drawdown is psychologically devastating even if the dollar amount is small.
- **Highlight trade clustering:** "80% of profits came from 3 trades" is a critical insight. Compute and display profit concentration (top N trades as % of total profit).
- **In the equity curve, mark individual trades** as dots/markers at entry and exit. Color by outcome. This prevents the smooth-line illusion from hiding clustered losses.
- **Show holding period distribution** as a histogram. A strategy that holds for 1 period (8h) most of the time is fundamentally different from one that holds for 30 periods.
- **Add "strategy health" indicators:**
  - Expectancy per trade = (win_rate * avg_win) - (loss_rate * avg_loss)
  - If expectancy is positive but less than estimated slippage+fees, flag it
  - If more than 50% of profit comes from a single trade, flag it

**Detection:**
- User runs multiple backtests and always picks the one with the highest win rate, ignoring profit factor.
- Backtest shows positive net PnL but profit factor < 1.2 (fragile).
- Equity curve looks good but max consecutive losses > 8 (psychologically unsustainable).

**Phase assignment:** Trade Replay phase -- must be addressed when adding per-trade detail. The trade table is not enough; contextual metrics are required.

---

### Pitfall 4: Dynamic Funding Intervals Breaking Yield Calculations and Comparisons

**What goes wrong:** Bybit launched dynamic settlement frequency on October 30, 2025. Some pairs now switch between 8h, 4h, 2h, and 1h intervals based on market volatility. The Pair Explorer and Strategy Builder compute per-period and annualized yields assuming a fixed interval, producing incorrect comparisons between pairs with different intervals and incorrect historical analysis when a pair's interval changed mid-dataset.

**Why it happens:**
- The existing `HistoricalFundingRate` model has `interval_hours: int = 8` as a default. If the fetched data doesn't include interval info (the Bybit funding history API response does NOT include `fundingIntervalHours`), all records default to 8h.
- The `insert_funding_rates` method extracts interval from `r.get("info", {}).get("fundingIntervalHours", 8)`. If the ccxt `info` dict doesn't include this field for historical records, the default of 8 is silently applied.
- BTCUSDT and ETHUSDT are EXCLUDED from dynamic frequency. But most altcoin pairs are subject to it. A user comparing "BTCUSDT at 0.01%/8h" with "SOLUSDT at 0.01%/1h" needs to understand these represent very different annualized yields (10.95% vs 87.6%).
- Historical data before October 2025 is all 8h. After October 2025, the same pair may have mixed intervals. Computing "average funding rate" or "median rate" across mixed intervals produces nonsensical results.

**Consequences:**
- Pair Explorer ranks a pair as "high yield" because it had many 1h funding settlements (high raw count) without adjusting for the shorter interval.
- Historical statistics (mean, percentile, distribution) are invalid when computed across mixed intervals without weighting.
- Net yield calculations using amortized fees assume a fixed holding-period count. A pair that settles every 1h during volatility generates more fee events than one settling every 8h, changing the fee-to-funding ratio.
- User sees "SOLUSDT has 3x more funding events than BTCUSDT" and misinterprets volume of settlements as profitability.

**Prevention:**
- **Normalize all rates to a common time unit** (e.g., per-day or per-8h-equivalent) before comparison. `normalized_rate = rate * (8 / actual_interval_hours)` converts any interval to 8h-equivalent.
- **Store actual interval per funding record,** not a default. If the API doesn't provide it, infer from timestamp gaps: if consecutive records are 1h apart, the interval was 1h.
- **Display interval alongside rate** in every table and chart: "0.01% / 8h" not just "0.01%". Never show a bare rate without its period.
- **When computing historical statistics**, group by interval or normalize first. "Average rate" should be "average 8h-equivalent rate."
- **Add interval change markers** to time-series charts. When a pair's interval changes from 8h to 1h (indicating volatility), mark it visually. This is information the user needs.
- **In Strategy Builder comparisons**, use the same time normalization. "Strategy A earned $50 from 6 funding events" vs. "Strategy B earned $50 from 48 funding events" tells a very different story about consistency.

**Detection:**
- Pair rankings change dramatically when switching between raw rates and normalized rates.
- Historical statistics show impossible values (e.g., >100% annualized from a pair that was rarely above 0.01%/8h, because 1h intervals were counted as 8h).
- Backtest for post-October-2025 data shows different results than expected.

**Phase assignment:** Pair Explorer AND data layer -- must be addressed when building any yield display. Requires data layer changes to properly store and retrieve interval information.

---

### Pitfall 5: Confirmation Bias Amplification Through Cherry-Picked Backtest Visualization

**What goes wrong:** The Strategy Builder allows the user to run backtests with different parameters across different pairs and date ranges. The user unconsciously (or consciously) cherry-picks the combination that looks best: favorable pair, favorable date range, favorable parameters. The dashboard facilitates this by making it easy to run many tests and hard to see the full distribution of results.

**Why it happens:**
- The current backtest form (in `backtest_form.html`) lets the user choose symbol, date range, and parameters independently. Nothing prevents running BTC from Jan-June 2025 (bull market), seeing great results, then running ETH from Jul-Dec 2025 (bear market), seeing bad results, and only remembering the BTC result.
- Each backtest is standalone. There is no persistent record of "I ran 15 backtests and 3 looked good." The user only sees the last result.
- The equity curve display makes it very easy to "look good" by narrowing the date range to exclude drawdown periods. A strategy that lost money Jan-March but made money April-June looks great if you only test April-June.
- Research on cognitive biases in data visualization shows that confirmation bias is the most amplified bias when users can interactively filter and explore data. Users seek confirming evidence and ignore disconfirming evidence.

**Consequences:**
- User deploys a strategy that "worked" on one pair for one 3-month period, not realizing it failed on 4 other pairs and 3 other time periods.
- Strategy Builder becomes a tool for self-deception rather than honest discovery.
- User develops unfounded confidence that erodes when live results diverge from their cherry-picked backtest.

**Prevention:**
- **Maintain a backtest session log:** Every backtest run is recorded with its parameters and results. Show a summary: "You've run 12 backtests. 4 were profitable, 8 were not. Best: X. Worst: Y."
- **Show cross-pair results by default.** When the user tests a strategy, automatically show results across all available pairs, not just the selected one. "This configuration on BTC: +$340. On all 20 pairs: +$120 avg, -$450 worst, 12/20 profitable."
- **Require minimum date range** for strategy evaluation. Prevent testing on less than 3 months of data. Show a warning for less than 6 months.
- **Show both the best and worst backtest** for a configuration. "Best case: +$500 on ETH. Worst case: -$200 on DOGE. Are you comfortable with the worst case?"
- **Add a "robustness check" feature** that automatically runs the strategy across all pairs and a rolling window, presenting aggregate results. This is the antidote to cherry-picking.
- **Display the parameter stability heatmap** from v1.1's sweep feature prominently. If the strategy only works with very specific parameters, the heatmap will show a narrow bright spot surrounded by red -- visually obvious fragility.

**Detection:**
- User runs many backtests on different pairs but only references the best-performing one.
- Deployed strategy parameters don't match the "typical" backtest result.
- Live performance is significantly worse than the backtest the user cited.

**Phase assignment:** Strategy Builder -- must be part of the strategy comparison workflow, not an afterthought.

---

## Moderate Pitfalls

Significant issues that degrade analysis quality or produce misleading results, but are recoverable with better design.

### Pitfall 6: Funding Rate Distribution Statistics Without Fee Context

**What goes wrong:** The Pair Explorer displays funding rate distributions (histogram, percentiles, mean, median) for each pair. A beginner sees "median rate is 0.015%/8h, 75th percentile is 0.03%" and concludes this is profitable, without understanding that the break-even rate after fees is approximately 0.02%/8h for a 3-period hold.

**Why it happens:**
- Statistical summaries of raw funding rates ignore the cost structure. A distribution centered at 0.015% looks "mostly positive" but is actually "mostly below break-even."
- The existing `FeeCalculator` can compute the break-even rate, but it's not integrated into statistical displays.
- Percentile displays without reference lines create false baselines. "75th percentile = 0.03%" means nothing without knowing that "break-even = 0.02%."
- Beginners don't intuitively understand that "positive funding rate" does not mean "profitable trade" because fees must be overcome first.

**Prevention:**
- **Overlay break-even rate** on every funding rate distribution chart. Draw a vertical line at the computed break-even rate. Color the area below it red ("unprofitable zone") and above it green.
- **Show "time above break-even"** as a percentage: "This pair was above break-even 42% of the time over the last 6 months." This is the real profitability signal.
- **Replace raw percentile tables** with net-yield percentile tables: show the distribution of `rate - amortized_fee_per_period`, not just `rate`.
- **Add a "fee drag" indicator** prominently: "Round-trip fees consume the first X periods of funding for this pair." Make the cost tangible.

**Detection:**
- User is excited about a pair with "mostly positive" funding rates that actually shows negative backtest returns.
- Distribution charts show green/positive but paired backtest shows losses.

**Phase assignment:** Pair Explorer statistical analysis -- must be addressed when building distribution displays.

---

### Pitfall 7: Equity Curve Visual Deception Through Scale and Smoothing

**What goes wrong:** The existing equity curve chart uses `tension: 0.3` (cubic interpolation) which smooths the line between data points. It also auto-scales the Y-axis to fill the chart, making a $10 profit on a $10,000 account look like a dramatic upswing. These visual choices make mediocre strategies look much better than they are.

**Why it happens:**
- Chart.js default `tension: 0.3` creates visually appealing curves that smooth over volatility. A strategy that fluctuates between $9,990 and $10,010 appears as a smooth upward slope.
- Auto-scaling the Y-axis to the data range means a $10,000 to $10,050 chart fills the same vertical space as a $10,000 to $15,000 chart. The visual amplitude is identical despite 100x difference in actual returns.
- The current chart doesn't show a reference line at the initial capital level ($10,000), so the user can't visually gauge "am I above or below where I started?"
- With trade-level detail added, the equity curve will have more data points, making the smoothing effect even more pronounced.

**Prevention:**
- **Use `tension: 0` (straight lines between points)** for honest representation. Every dip and spike should be visible.
- **Pin Y-axis minimum to 0 or to a percentage below initial capital.** Show the full context: "$10,050 on $10,000" should not fill the chart. Alternatively, display returns as percentage: "0.5% return" is much more honest than a chart that appears to show dramatic growth.
- **Add a horizontal reference line** at initial capital ($10,000). Everything below is loss territory. Color the area below it red.
- **Show return percentage as the primary Y-axis**, not dollar amounts. "$10,050" looks like growth; "0.5% return" shows reality.
- **Add drawdown shading** below the equity curve high-water mark. This makes drawdown periods visually obvious rather than hidden by scale.
- **When comparing strategies**, use the same Y-axis scale. The comparison chart in `renderComparisonEquityCurve` already uses shared axes, which is correct.

**Detection:**
- User describes backtest results as "the chart looks great" but actual returns are < 1%.
- Strategy comparisons where one appears dramatically better but the actual difference is < $50.

**Phase assignment:** Trade Replay and Decision View -- must be addressed when enhancing equity curve visualization.

---

### Pitfall 8: Per-Pair Profitability Analysis Without Time Segmentation

**What goes wrong:** The Pair Explorer shows "this pair earned $X total over the last 6 months" as a single aggregate number. The user doesn't see that all the profit came from one 2-week period and the other 5.5 months were flat or negative. Aggregate per-pair profitability masks the temporal distribution of returns.

**Why it happens:**
- The simplest profitability display is "total net yield" or "average rate." Both hide temporal clustering.
- Funding rate profitability is highly regime-dependent. A pair might have extreme positive rates during one market event and be neutral the rest of the time.
- Without monthly or weekly breakdowns, the user cannot distinguish "consistently profitable" from "one-time windfall."
- The current analytics module (`metrics.py`) computes lifetime metrics. There's no built-in time-segmented analysis.

**Prevention:**
- **Show monthly profitability breakdown** for each pair. A simple bar chart: Jan=$10, Feb=$-5, Mar=$20, etc. This instantly reveals temporal clustering.
- **Compute "consistency score"**: what percentage of months was the pair net-profitable? "6/6 months profitable" is much more convincing than "+$50 total" which could be "+$100 in January, -$50 over the next 5 months."
- **Highlight the "best month contribution"**: "60% of this pair's total profit came from March 2025." If one month dominates, flag it.
- **Show rolling 30-day profitability** as a time series, not just the aggregate. This reveals trends and regime changes.

**Detection:**
- User selects a pair based on high aggregate profitability that turns out to have been profitable in one burst.
- Backtest shows strong results but monthly breakdown reveals inconsistency.

**Phase assignment:** Pair Explorer and Decision View -- must be addressed when building per-pair profitability displays.

---

### Pitfall 9: Strategy Builder Allowing Parameter Combinations That Can't Work

**What goes wrong:** The Strategy Builder form allows arbitrary parameter combinations, including ones that are logically impossible or guaranteed to lose money. For example: entry threshold lower than exit threshold (never holds a position), signal weights that don't sum to 1.0, or minimum funding rates below the break-even point.

**Why it happens:**
- The current backtest form (`backtest_form.html`) has independent number inputs for each parameter with no cross-field validation. The `_build_config_from_body` function in `api.py` accepts whatever the user provides.
- `BacktestConfig` is a pure dataclass with no validation logic. Invalid combinations produce confusing backtest results (0 trades, NaN metrics) rather than clear error messages.
- A beginner doesn't know which parameter combinations are valid. They might set `exit_threshold = 0.5` and `entry_threshold = 0.3`, which means the strategy enters only when the score is above 0.3 but exits when it drops below 0.5 -- so it exits immediately after entry.

**Prevention:**
- **Add form-level validation** that checks constraints before submitting:
  - `entry_threshold > exit_threshold` (otherwise immediate exit)
  - `min_funding_rate >= 0` (negative entry threshold makes no sense for this strategy)
  - Signal weights should sum to approximately 1.0 (warn if < 0.8 or > 1.2)
  - `exit_funding_rate < min_funding_rate` (otherwise never enters)
- **Show computed break-even rate** as the parameter is entered. "With these fees, you need at least 0.02%/period to break even. Your entry threshold allows rates down to 0.01%/period."
- **Add "sensible defaults" presets**: "Conservative," "Balanced," "Aggressive" preset configurations that are known to be valid. Let beginners start from presets rather than blank forms.
- **When a backtest produces 0 trades**, explain WHY: "No trades occurred because the entry threshold (0.3) was never reached during this period" rather than showing a flat equity curve with no explanation.

**Detection:**
- User runs backtests that produce 0 trades and doesn't understand why.
- User sets contradictory parameters (entry < exit threshold) and sees confusing results.

**Phase assignment:** Strategy Builder form -- validation must be part of the form implementation.

---

### Pitfall 10: Decision View Presenting Correlation as Causation

**What goes wrong:** The Decision View shows historical evidence like "when funding rate was above 0.03%, the strategy was profitable 70% of the time." The beginner interprets this as "if I enter when the rate is above 0.03%, I will be profitable 70% of the time." This is correlation (historical pattern) presented as causation (predictive rule).

**Why it happens:**
- Historical success rates are backward-looking. "70% win rate when rate > 0.03%" means that in the past, this happened. It does not account for regime changes, survivorship bias, or look-ahead effects in the historical data.
- The Decision View is specifically designed to answer "should I turn this on?" If it presents historical statistics without uncertainty, it becomes a false oracle.
- Beginners are especially susceptible to interpreting historical patterns as future guarantees. Professional traders understand that "past performance is not indicative of future results" but beginners take historical statistics at face value.

**Prevention:**
- **Always show confidence intervals**, not point estimates. "Win rate: 70% (95% CI: 55%-82%)" is much more honest than "70%."
- **Show the worst historical period**, not just the average. "Average win rate: 70%. Worst month: 30%."
- **Compare against random baseline**: "Is this 70% win rate actually better than random entry? Random entry in this period: 62% win rate." If the strategy barely beats random, the "discovery" is likely noise.
- **Add explicit disclaimer** on every predictive display: "Historical results. Actual performance depends on future market conditions which may differ."
- **Show how the win rate changed over time**: "Win rate by quarter: Q1=80%, Q2=60%, Q3=75%, Q4=55%." Declining trend should trigger caution.
- **Never present a single "should I turn this on?" score.** Present evidence for and against, and let the user decide. The dashboard should inform, not recommend.

**Detection:**
- User deploys a strategy "because the Decision View said 70% win rate" without understanding the confidence interval.
- Live performance is significantly below the historical average shown in Decision View.

**Phase assignment:** Decision View -- must be addressed in the summary dashboard design.

---

## Minor Pitfalls

Issues that cause confusion or inefficiency but are unlikely to produce material financial harm.

### Pitfall 11: Information Overload in Trade Replay Killing Actionable Insight

**What goes wrong:** Trade Replay adds per-trade detail (entry reason, exit reason, holding period, fee breakdown, funding payments). Showing all of this for every trade creates a data wall that the user can't parse. They either ignore it entirely or fixate on individual trades rather than seeing patterns.

**Prevention:**
- **Show summary first, detail on demand.** Default view: trade list with outcome (green/red), net PnL, holding period. Click to expand: full detail with entry/exit reasons, fee breakdown, funding schedule.
- **Aggregate into patterns:** "Trades entered on RISING trend: 8 trades, 6 profitable. Trades entered on STABLE trend: 12 trades, 5 profitable." This reveals actionable patterns that individual trade inspection misses.
- **Limit initial display to 20-30 trades** with pagination. Showing 500 trades at once is never useful.
- **Highlight "interesting" trades:** the biggest winner, biggest loser, longest hold, shortest hold. These outliers tell the story.

**Phase assignment:** Trade Replay -- part of the trade detail UI design.

---

### Pitfall 12: Stale Data Creating False Signals in the Pair Explorer

**What goes wrong:** The Pair Explorer shows funding rate statistics computed from the full historical dataset (up to 365 days). If the data hasn't been synced recently, the "current" display is stale. A user sees a pair ranked highly based on data that's hours or days old, enters a position, and finds the rate has already changed.

**Prevention:**
- **Show "last synced" timestamp** prominently on every data display. "Data as of: Feb 13, 2026 09:15 UTC."
- **Separate "current rate" from "historical statistics."** Current rate should come from the live `FundingMonitor`, historical stats from the data store. Don't mix them.
- **Gray out or badge stale data.** If last sync was > 8h ago, show a warning: "Data may be stale. Last sync: 12h ago."
- The existing `HistoricalDataStore.get_data_status()` returns `last_sync_ms`. Use it.

**Phase assignment:** Pair Explorer -- must be addressed in the display layer.

---

### Pitfall 13: Comparing Strategy Configurations Without Controlling for Time Period

**What goes wrong:** The Strategy Builder lets the user compare Configuration A (tested on BTC, Jan-Mar 2025) with Configuration B (tested on ETH, Apr-Jun 2025). The comparison is invalid because it varies three things simultaneously (parameters, pair, and time period), but the user draws conclusions about the parameters.

**Prevention:**
- **When comparing configurations, require the same pair and time period** for a valid comparison. The existing `/backtest/compare` endpoint already enforces this for v1.0 vs v1.1 comparison. Extend this pattern.
- **Show a "comparison validity" indicator**: "Same pair + same period = Valid comparison. Different pair or period = Informational only."
- **Default comparison mode** should fix pair and time period, varying only strategy parameters. This is the only scientifically valid comparison.
- **If the user wants cross-pair comparison**, show it as a matrix: rows = pairs, columns = configurations, cells = net PnL. This makes it visually clear that multiple variables are changing.

**Phase assignment:** Strategy Builder comparison feature.

---

### Pitfall 14: Existing Backtest Engine Limitations Amplified by Trade-Level Display

**What goes wrong:** The current backtest engine has known limitations (from v1.1 PITFALLS): fixed 5bps slippage, single-pair-at-a-time simulation, no multi-pair portfolio simulation. When Trade Replay surfaces per-trade detail, these limitations become more visible and more misleading. A trade showing "$2.50 profit" at the individual level masks that the slippage model is crude and the actual profit might be anywhere from $0.50 to $4.00.

**Prevention:**
- **Show slippage assumption on every trade.** "Entry slippage: 5bps ($0.50). This is an estimate; actual slippage varies."
- **Add a "confidence range" to per-trade PnL**: "$2.50 +/- $1.00 (sensitivity to slippage)." Compute this by running the trade at 0bps and 15bps slippage.
- **Flag trades where fees dominate:** If entry+exit fees > 50% of gross funding income, highlight it. These trades are highly sensitive to execution quality.
- **Don't compute statistics to more precision than the model supports.** Showing "$2.4731 net PnL" implies false precision. Round to cents or use ranges.

**Phase assignment:** Trade Replay -- must accompany per-trade detail display.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Severity | Mitigation |
|---|---|---|---|
| Pair Explorer: yield display | Annualized yield illusion (#1) | **Critical** | Show per-period net yield, break-even context, holding-period returns |
| Pair Explorer: pair selection | Survivorship bias (#2) | **Critical** | Point-in-time pairs, tenure display, disclaimers |
| Pair Explorer: distributions | Statistics without fees (#6) | Moderate | Break-even overlay, net-yield percentiles |
| Pair Explorer: data freshness | Stale data (#12) | Minor | Last-synced timestamp, live vs historical separation |
| Trade Replay: trade list | Information overload (#11) | Minor | Summary first, detail on demand, pattern aggregation |
| Trade Replay: per-trade PnL | Aggregate metrics hiding reality (#3) | **Critical** | Profit factor, avg winner/loser, consecutive losses, concentration |
| Trade Replay: equity curve | Visual deception (#7) | Moderate | No smoothing, percentage axis, drawdown shading, reference line |
| Trade Replay: precision | Amplified engine limits (#14) | Minor | Slippage disclosure, confidence ranges, rounding |
| Strategy Builder: form | Invalid parameters (#9) | Moderate | Cross-field validation, presets, break-even display |
| Strategy Builder: comparison | Cherry-picking (#5) | **Critical** | Session log, cross-pair defaults, robustness checks |
| Strategy Builder: comparison | Uncontrolled variables (#13) | Minor | Same-pair-same-period enforcement, validity indicator |
| Decision View: recommendations | Correlation as causation (#10) | Moderate | Confidence intervals, worst period, random baseline comparison |
| Decision View: summary | Annualized yield (#1) | **Critical** | Per-period framing, fee context, holding-period returns |
| Data layer: intervals | Dynamic intervals (#4) | **Critical** | Rate normalization, per-record intervals, interval display |
| All visualizations | Confirmation bias amplification (#5) | **Critical** | Session logs, cross-pair defaults, worst-case display |

---

## The Meta-Pitfall: Building a Tool That Confirms What the User Wants to Hear

The single most dangerous outcome of v1.2 is building a strategy discovery tool that makes every strategy look good. A beginner WANTS to believe the strategy works. The dashboard should fight this tendency, not enable it.

**Design principle:** Every visualization should include at least one element that could discourage the user from trading. If every screen makes the strategy look appealing, the tool is broken.

Specific applications:
- **Pair Explorer**: For every pair, show "time below break-even" prominently. If it's 60%, the user should feel cautious.
- **Trade Replay**: Show the worst trade first, not the best. Lead with the downside.
- **Strategy Builder**: Show cross-pair results by default, not single-pair. Most configs lose on most pairs.
- **Decision View**: Never give a single "yes/no" answer. Present evidence and uncertainty. Let the user decide.

**The v1.0/v1.1 system works as a trading engine.** The v1.2 system's job is to help the user understand WHETHER and WHEN to use it. That means showing the full picture -- including the parts that suggest caution.

---

## Bybit-Specific Concerns Carried Forward

These known concerns from v1.1 become more acute in v1.2 because they directly affect the accuracy of analysis shown to the user.

### Concern A: Bybit Fee Structure Verification

**Status:** VERIFIED. Current Bybit Non-VIP rates match the code: spot taker 0.1%, perp taker 0.055%. This was confirmed against Bybit's official fee page as of February 2026.

**v1.2 Impact:** Fee calculations in Pair Explorer and Strategy Builder are correct for Non-VIP users. However, if the user has VIP status (lower fees), the displayed break-even rates and profitability calculations will be conservative. Consider adding a fee tier selector in the Strategy Builder.

### Concern B: Look-Ahead Bias (Predicted vs Settled Rates)

**Status:** PARTIALLY ADDRESSED. The v1.1 `BacktestDataStoreWrapper` enforces temporal ordering. However, the historical data store contains SETTLED rates while the live bot uses PREDICTED rates. This discrepancy remains.

**v1.2 Impact:** Trade Replay will show trades entered based on settled rates that were not actually available at decision time. Per-trade detail makes this more visible: "Entered because rate was 0.05%" -- but was it 0.05% at entry time, or is that the settled rate that was only known afterward? Surface this distinction in Trade Replay: "Rate at settlement: 0.05%. Note: decision was based on predicted rate, which may have differed."

### Concern C: Funding Rate Trend Mean-Reversion

**Status:** ACKNOWLEDGED in v1.1 signal engine design. EMA span kept short (6 periods).

**v1.2 Impact:** The Pair Explorer's trend indicators (if displayed) should carry a note: "Funding rate trends are mean-reverting. A rising trend is likely to reverse." This directly counters the beginner's tendency to extrapolate trends.

---

## Sources

### Bybit Official Documentation
- [Bybit Funding Rate History API](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) -- endpoint constraints, response fields (does NOT include interval_hours), pagination -- HIGH confidence
- [Bybit Dynamic Settlement Frequency Announcement](https://www.prnewswire.com/news-releases/bybit-launches-dynamic-settlement-frequency-system-for-perpetual-contracts-302598179.html) -- October 2025 launch, affected pairs, frequency rules -- HIGH confidence
- [Bybit Trading Fee Structure](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure/) -- Non-VIP rates confirmed: spot 0.1%/0.1%, perp 0.02%/0.055% -- HIGH confidence
- [Bybit Funding Rate Introduction](https://www.bybit.com/en/help-center/article/Introduction-to-Funding-Rate) -- funding rate mechanics, settlement times -- HIGH confidence

### Backtesting Methodology and Visualization
- [Backtesting Common Mistakes (QuantInsti)](https://blog.quantinsti.com/common-mistakes-backtesting/) -- overfitting, unrealistic assumptions, data issues -- MEDIUM confidence
- [Equity Curve Backtesting (FasterCapital)](https://fastercapital.com/content/Equity-Curve-Backtesting--Evaluating-Strategies-for-Profitability.html) -- equity curve interpretation pitfalls -- MEDIUM confidence
- [Interpreting Backtest Results (FX Replay)](https://www.fxreplay.com/learn/how-to-interpret-backtest-results-a-traders-guide-to-smarter-strategy-decisions) -- trade-level metrics, profit factor, drawdown -- MEDIUM confidence
- [Backtesting Strategies That Actually Work (Billions Club)](https://www.fortraders.com/blog/backtesting-strategies-that-actually-work) -- over-optimization, curve fitting -- MEDIUM confidence

### Survivorship Bias
- [Building Survivorship-Bias-Free Crypto Dataset (Concretum Group)](https://concretumgroup.com/building-a-survivorship-bias-free-crypto-dataset-with-coinmarketcap-api/) -- 4x profit difference, dataset methodology -- MEDIUM confidence
- [Survivorship Bias in Trading (Quantified Strategies)](https://www.quantifiedstrategies.com/survivorship-bias-in-backtesting/) -- impact estimates, prevention methods -- MEDIUM confidence
- [Survivorship Bias in Backtesting (LuxAlgo)](https://www.luxalgo.com/blog/survivorship-bias-in-backtesting-explained/) -- crypto-specific survivorship effects -- MEDIUM confidence
- [Survivorship Bias (Bookmap)](https://bookmap.com/blog/survivorship-bias-in-market-data-what-traders-need-to-know) -- market data quality impacts -- MEDIUM confidence

### Funding Rate Arbitrage Research
- [Risk and Return Profiles of Funding Rate Arbitrage (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S2096720925000818) -- 17% of observations show significant spreads, 40% generate positive returns -- MEDIUM confidence
- [Funding Rates: Hidden Cost and Strategy Trigger (QuantJourney)](https://quantjourney.substack.com/p/funding-rates-in-crypto-the-hidden) -- rate reversals, regime changes, false signals -- MEDIUM confidence
- [Funding Rate Arbitrage Illusion vs Reality](https://vocus.cc/article/69247fa6fd89780001a58f88) -- annualization problems, borrowing costs -- MEDIUM confidence
- [Crypto Funds 101: Funding Fee Arbitrage (1Token)](https://blog.1token.tech/crypto-fund-101-funding-fee-arbitrage-strategy/) -- ADL risk, transaction cost impact, position adjustment costs -- MEDIUM confidence
- [Gate.com: Perpetual Contract Funding Rate Arbitrage 2025](https://www.gate.com/learn/articles/perpetual-contract-funding-rate-arbitrage/2166) -- average annual return 19.26% in 2025 -- LOW confidence

### Cognitive Bias and Visualization Research
- [Cognitive Biases in Visualizations (Ellis)](https://aedeegee.github.io/bookchapter18.pdf) -- framing, anchoring, confirmation bias in data viz -- MEDIUM confidence
- [Data Visualization and Cognitive Biases in Audits (ResearchGate)](https://www.researchgate.net/publication/335157173_Data_visualization_and_cognitive_biases_in_audits) -- five major bias types in data visualization -- MEDIUM confidence
- [Trading Metrics Guide (Edgewonk)](https://edgewonk.com/blog/the-ultimate-guide-to-the-10-most-important-trading-metrics) -- profit factor, expectancy, win rate interpretation -- MEDIUM confidence

### Codebase Analysis
- v1.0/v1.1 source code reviewed: `backtest/models.py`, `backtest/engine.py`, `data/store.py`, `data/fetcher.py`, `data/models.py`, `data/pair_selector.py`, `pnl/fee_calculator.py`, `signals/engine.py`, `analytics/metrics.py`, `market_data/opportunity_ranker.py`, `config.py`, `dashboard/routes/api.py`, `dashboard/routes/pages.py`, `dashboard/templates/partials/equity_curve.html`, `dashboard/templates/partials/backtest_form.html` -- HIGH confidence for integration pitfall analysis
