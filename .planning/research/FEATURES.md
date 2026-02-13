# Feature Landscape: Strategy Discovery & Decision Support

**Domain:** Pair analysis, trade-level backtest results, strategy building workflow, decision dashboard for funding rate arbitrage
**Researched:** 2026-02-13
**Confidence:** MEDIUM-HIGH -- features informed by analysis of existing tools (CoinGlass, Loris Tools, FundingView, Sharpe AI, Freqtrade), the project's existing codebase, and domain knowledge of funding rate arbitrage workflows.

## Scope

This document covers features for v1.2 ONLY -- the Strategy Discovery & Decision Support milestone. It assumes all v1.0 and v1.1 features are already built and working:

**Existing v1.0:** Real-time funding rate scanning, delta-neutral execution, risk management, paper trading, web dashboard (8 panels), runtime config.
**Existing v1.1:** Historical data pipeline (SQLite, 50K+ records), composite signal engine (trend, persistence, basis, volume), backtesting with parameter sweep/equity curve/heatmap/comparison, dynamic position sizing.

**The problem this milestone solves:** The user can see rates and run backtests, but cannot tell which pairs are worth trading, cannot inspect individual backtest trades, and has no guided workflow for building intuition about what "good" looks like in funding rate arbitrage. The dashboard shows data without context.

---

## Table Stakes

Features users expect from a strategy discovery tool. Missing any of these means the milestone fails to solve the core problem: "I don't know which pairs to trade or why."

### Pair Explorer

| Feature | Why Expected | Complexity | Depends On | Notes |
|---------|--------------|------------|------------|-------|
| **Pair profitability ranking table** | Users need a single view showing which of the ~20 tracked pairs have been historically profitable. CoinGlass, FundingView, and Loris Tools all center on sortable pair tables as their primary UI. Without this, users must run 20 separate backtests to compare pairs. | Medium | `HistoricalDataStore.get_funding_rates()`, backtest engine | Query historical funding rates for all tracked pairs, compute per-pair metrics (avg rate, total funding collected, rate stability, fee-adjusted yield). Display as sortable table. Pre-computed, not requiring full backtest per pair -- use aggregate statistics from stored funding rate data. |
| **Per-pair funding rate time series chart** | Seeing the rate history for a specific pair is the most basic analysis step. Loris Tools and CoinGlass both feature per-pair interactive charts as their core offering. Users need to see if a pair's rate is currently high/low relative to its own history. | Low | `HistoricalDataStore.get_funding_rates()`, Chart.js (already used) | Render line chart of funding rate over time for selected pair. Add reference lines for mean and entry threshold. Existing Chart.js + HTMX pattern from equity curve applies directly. |
| **Rate distribution histogram** | Users with no funding rate experience need to understand "is 0.01% good or bad?" A distribution shows where the current rate falls relative to history. This is the single most important context feature for a new user. | Low | `HistoricalDataStore.get_funding_rates()`, Chart.js | Histogram of historical rates for a pair with the current rate marked. Shows percentile position. Can reuse Chart.js bar chart type. |
| **Pair comparison view** | Users need to compare 2-3 pairs side-by-side to make selection decisions. FundingView and CryptoFundingTracker both offer multi-pair comparison as a core feature. | Medium | Per-pair metrics computation, Chart.js | Overlay rate time series for multiple pairs on one chart. Side-by-side metrics table. Select pairs from the ranking table to add to comparison. |
| **Fee-adjusted yield calculator** | Raw funding rates are misleading without fee context. The existing `OpportunityRanker` already computes net yield and annualized yield after amortized fees, but this is only visible in the bot's internal ranking, not exposed to the user. Users must see net yield, not gross rate. | Low | `OpportunityRanker.rank_opportunities()` logic, `FeeSettings` | Display alongside raw rate: net yield per period, annualized yield after fees, breakeven holding periods. Already computed in v1.0 -- just surface it in the UI. |

### Trade-Level Backtest Results

| Feature | Why Expected | Complexity | Depends On | Notes |
|---------|--------------|------------|------------|-------|
| **Individual trade log table** | The current backtest returns only aggregate metrics (total trades, net P&L, Sharpe). Users cannot see WHEN trades happened, HOW LONG they lasted, or WHICH ones were winners/losers. Freqtrade, TradesViz, and every serious backtesting tool show per-trade details. This is the most critical gap in the current backtest output. | Medium | `BacktestEngine`, `PnLTracker.get_closed_positions()` | The engine already processes individual trades through `PnLTracker`, which records `PositionPnL` with entry/exit fees, funding payments, timestamps. The data EXISTS but is discarded after aggregate metrics are computed. Need to capture the list of `PositionPnL` objects and serialize them in `BacktestResult`. |
| **Trade-on-chart visualization** | Users need to see entry/exit points overlaid on the funding rate time series to understand "why did the strategy enter here?" TradesViz and TradingView both show trade markers on price charts. For funding rate arb, the relevant chart is the funding rate (not price). | Medium | Individual trade log (above), per-pair funding rate chart | Render entry (green triangle up) and exit (red triangle down) markers on the funding rate time series chart at the timestamps from the trade log. Chart.js annotation plugin handles this. |
| **Per-trade P&L breakdown** | For each trade: entry time, exit time, duration, number of funding periods captured, total funding collected, total fees paid, net P&L. Users learning funding rate arb need to see the mechanics of each trade to build intuition about how funding payments accumulate vs fees. | Low | `PositionPnL` dataclass (already has all fields) | `PositionPnL` already stores `funding_payments` (list of `FundingPayment` with amount, rate, mark_price, timestamp), `entry_fee`, `exit_fee`, `opened_at`, `closed_at`. Just need to serialize this to JSON and render in a table with expandable rows. |
| **Win/loss trade categorization** | Color-code trades by profitability. Show distribution of wins vs losses. Let users filter to only losing trades to understand what went wrong. | Low | Per-trade P&L breakdown (above) | Compute net P&L per trade (total funding - total fees). Tag as win/loss. Add summary row: X wins, Y losses, avg win size, avg loss size, largest win, largest loss. |

### Decision Context Dashboard

| Feature | Why Expected | Complexity | Depends On | Notes |
|---------|--------------|------------|------------|-------|
| **"Is this rate good?" contextual indicator** | For each pair showing a funding rate, display whether that rate is above/below its historical average, what percentile it is in, and whether it is trending up or down. This is the single most impactful feature for a new user who sees "0.0103%" and has no idea if that is good. | Medium | `HistoricalDataStore`, existing funding rates panel | Enhance the existing funding rates panel (DASH-02) with columns: historical avg rate, percentile rank, trend direction (from v1.1 signal engine). Color-code: green = above 75th percentile and rising, yellow = average, red = below average or falling. |
| **Signal score breakdown display** | The composite signal engine already computes rate_level, trend_score, persistence, basis_score. These are computed but never shown to the user. Display them so the user understands WHY a pair scored high/low. | Low | `CompositeSignal` dataclass, `SignalEngine.score_opportunities()` | The `CompositeSignal` already has all sub-scores. Render as a small radar/spider chart or horizontal bar breakdown next to each pair in the opportunity table. Existing HTMX polling can deliver updates. |
| **Recommended action label** | For each tracked pair, show a clear label: "Strong opportunity", "Moderate", "Not recommended", "Insufficient data". This is opinionated decision support -- not just showing data but interpreting it. | Low | Composite signal score, historical context | Map signal score + historical percentile to a label. Simple thresholds: score >= 0.6 AND rate > 75th percentile = "Strong". This is the feature that transforms data display into decision support. |

---

## Differentiators

Features that set this apart from just another data dashboard. Not expected by users, but significantly increase the tool's value for learning and strategy development.

### Strategy Building Workflow

| Feature | Value Proposition | Complexity | Depends On | Notes |
|---------|-------------------|------------|------------|-------|
| **Guided strategy builder wizard** | Walk the user through: (1) pick pairs based on pair explorer data, (2) choose strategy mode (simple vs composite), (3) set parameters with sensible defaults and explanations, (4) run backtest, (5) review results with trade log, (6) compare with alternative parameters. This turns 6 disconnected features into a coherent workflow. | Medium | Pair explorer, backtest engine, trade log, parameter sweep | Multi-step HTML form with HTMX partial updates. Each step informs the next. Step 1 pre-selects the pair with best historical metrics. Step 3 shows parameter defaults from the pair's historical data (e.g., "average rate for ETHUSDT is 0.008%, so entry threshold of 0.01% means you enter above the 62nd percentile"). |
| **Parameter sensitivity preview** | Before running a full sweep, show quick estimates of how parameter changes affect results. "If you raise the entry threshold from 0.01% to 0.02%, you would have captured X fewer trades but with Y% higher avg yield." | High | Historical funding rate data, quick estimation logic | Lightweight estimation using rate distribution (no full backtest). Count how many funding periods exceed each threshold. Multiply by avg rate above threshold minus fees. Gives directional guidance without the computation cost of a full sweep. |
| **Strategy template library** | Pre-built strategy configurations: "Conservative BTC" (high threshold, low allocation), "Aggressive Altcoin" (lower threshold, higher allocation, composite mode), "Balanced Portfolio" (multi-pair, moderate settings). New users do not know what good parameters look like. | Low | Backtest config system | JSON/dict templates that pre-fill the backtest form. Include description explaining the rationale. Can ship 3-5 templates based on analysis of the user's historical data. |
| **Backtest comparison across pairs** | Run the same strategy parameters across multiple pairs simultaneously and compare results. Currently, backtests are single-pair only. The user wants to know: "With these settings, which pairs would have been profitable?" | Medium | Backtest engine, pair explorer | Iterate the existing single-pair backtest across selected pairs. Aggregate results into a comparison table: pair, net P&L, Sharpe, win rate, total trades. Already have all the infrastructure -- just need the loop and aggregation UI. |

### Learning & Intuition Features

| Feature | Value Proposition | Complexity | Depends On | Notes |
|---------|-------------------|------------|------------|-------|
| **Rate regime annotations** | Mark periods on the funding rate chart: "Bull market -- rates consistently positive", "Market crash -- rates went deeply negative for 3 days", "Consolidation -- rates near zero." Help users connect rate patterns to market events they may remember. | Medium | Historical rate data, manual or heuristic labeling | Auto-detect regimes using rate statistics over rolling windows: avg rate > 0.02% = "High funding environment", avg rate < 0 = "Bearish pressure", rate std dev > 2x normal = "Volatile period". Overlay as shaded regions on rate chart. |
| **Trade replay mode** | Step through a backtest trade-by-trade, showing the state of the market at each entry/exit decision. "At this moment, the rate was X, the trend was Y, the persistence was Z, and the strategy decided to enter because..." Inspired by FX Replay and TradingView bar replay. | High | Trade log, historical data, signal engine | For each trade in the backtest log, reconstruct the signal state at entry/exit time. Display as a card: rate chart zoomed to the trade period, signal breakdown, funding payments received during hold. This is the most powerful learning tool but requires significant UI work. |
| **Funding rate glossary/tooltips** | Inline explanations: "Funding rate: the periodic payment between long and short positions. Positive = longs pay shorts. Our strategy collects this payment by shorting perps while holding spot." | Low | None (static content) | Tooltip icons next to every metric. Helps users who are learning funding rate arbitrage for the first time. Minimal code, high impact for onboarding. |
| **Historical performance summary card** | "Over the last 90 days, your tracked pairs had an average annualized yield of X% after fees. The best pair was Y with Z% yield. The worst was W which would have lost money due to fee drag." One-paragraph summary that answers "is this strategy even working?" | Low | Historical rate data, fee calculations | Compute from stored data on page load. No backtest needed -- use rate averages and fee math. Display prominently at the top of the pair explorer page. |

---

## Anti-Features

Features to explicitly NOT build in v1.2. Each has been considered and rejected.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Real-time pair recommendation alerts** | The user is learning, not operating at scale. Push notifications create urgency without understanding. The user should pull insights when ready, not be pushed into action. | Show "Strong opportunity" labels on the dashboard. The user checks when they want to. |
| **Auto-execute from backtest results** | "This backtest was profitable, click here to run it live" is dangerous for a user who does not yet understand the strategy. Backtests have survivorship bias, look-ahead risk, and regime sensitivity. | Show results with context: "This backtest earned $X over Y days in a bull market. Past performance does not predict future results." Let the user manually configure the bot. |
| **Multi-exchange pair comparison** | The bot only trades on Bybit. Showing funding rates from Binance, OKX, etc. is interesting but not actionable. It also requires additional API integrations and data pipelines. | Stay focused on Bybit-only data. Clearly label all data as Bybit. Cross-exchange comparison is a v2.0+ feature. |
| **AI-powered trade recommendations** | LLM-based analysis ("Claude thinks ETHUSDT is a good opportunity because...") adds opacity and unpredictability. The user needs to build their OWN understanding, not defer to an AI. | Show clear metrics and let the user form conclusions. The signal score system already provides structured analysis. |
| **Social sentiment integration** | Integrating Twitter/Reddit sentiment adds noise, requires external APIs with rate limits, and is poorly correlated with funding rate dynamics. Funding rates are driven by leverage positioning, not social sentiment. | Focus on market-microstructure signals that are already available: rate level, trend, persistence, basis spread, volume. |
| **Complex multi-leg strategies** | Calendar spreads, cross-pair hedging, or options overlays. Massively increases complexity. The user is still learning basic delta-neutral arb. | Stick with single-pair long-spot/short-perp. Add complexity only after the user has live trading experience. |
| **Custom indicator builder** | "Build your own signal from rate + OI + volume + basis with custom weights." Powerful but premature. The user does not yet know what signals matter. | Provide the composite signal with fixed sub-signals and let the user adjust weights via the existing backtest parameter sweep. |

---

## Feature Dependencies

```
Pair Explorer Layer:
  HistoricalDataStore.get_funding_rates() --> Per-pair aggregate statistics computation
  Per-pair aggregate statistics --> Pair profitability ranking table
  Per-pair aggregate statistics --> Fee-adjusted yield calculator
  Per-pair aggregate statistics --> "Is this rate good?" contextual indicator
  HistoricalDataStore.get_funding_rates() --> Per-pair funding rate time series chart
  Per-pair funding rate time series chart --> Rate distribution histogram
  Pair profitability ranking table --> Pair comparison view

Trade-Level Results Layer:
  BacktestEngine.run() --> Capture individual PositionPnL in BacktestResult  [CRITICAL CHANGE]
  Captured PositionPnL list --> Individual trade log table
  Individual trade log table --> Win/loss trade categorization
  Individual trade log table + Per-pair rate chart --> Trade-on-chart visualization
  Individual trade log table --> Per-trade P&L breakdown (expandable rows)

Decision Context Layer:
  Per-pair aggregate statistics + Existing funding rates panel --> Contextual rate indicator
  SignalEngine.score_opportunities() --> Signal score breakdown display
  Contextual rate indicator + Signal score --> Recommended action label

Strategy Building Layer (differentiators):
  Pair explorer + Backtest engine + Trade log --> Guided strategy builder wizard
  Historical rate distribution --> Parameter sensitivity preview
  Backtest config templates --> Strategy template library
  Backtest engine + Pair explorer --> Multi-pair backtest comparison

Learning Layer (differentiators):
  Historical rate data + heuristic detection --> Rate regime annotations
  Trade log + signal reconstruction --> Trade replay mode
  Static content --> Funding rate glossary/tooltips
  Per-pair aggregate statistics --> Historical performance summary card
```

**Critical path for table stakes:**
```
1. Per-pair aggregate statistics computation (foundation for everything)
2. Capture trade-level data in BacktestResult (critical change to existing code)
3. Pair profitability ranking table + rate chart (pair explorer core)
4. Trade log table + trade-on-chart (backtest detail core)
5. Contextual rate indicators (decision support core)
```

---

## MVP Recommendation for v1.2

### Priority 1: Pair Explorer (foundation for all decision-making)

Build first because the user cannot make ANY strategy decisions without understanding which pairs are worth considering.

1. Per-pair aggregate statistics computation (avg rate, std dev, percentile rankings, fee-adjusted yield)
2. Pair profitability ranking table (sortable by yield, stability, volume)
3. Per-pair funding rate time series chart (with mean/threshold reference lines)
4. Rate distribution histogram (with current rate marker)
5. Fee-adjusted yield display (annualized net yield, breakeven periods)
6. Historical performance summary card ("here's how your pairs have performed")

**Rationale:** The pair explorer transforms raw historical data (50K+ records already stored) into actionable insights. It answers the user's most basic question: "Which of these 20 pairs should I care about?" No new data collection needed -- all inputs exist in SQLite.

### Priority 2: Trade-Level Backtest Results (makes backtesting actually useful for learning)

Build second because the user needs to understand WHY a strategy worked or failed, not just whether it did.

1. Capture individual `PositionPnL` list in `BacktestResult` (code change in engine)
2. Trade log table with per-trade P&L breakdown
3. Win/loss categorization and summary statistics
4. Trade-on-chart visualization (entry/exit markers on rate chart)

**Rationale:** The current backtest shows "you made $47 in 30 days with 12 trades." The user needs to see "trade #3 entered at 0.015% rate, held for 4 funding periods, collected $8.20 in funding, paid $3.10 in fees, net +$5.10." This is how intuition gets built.

### Priority 3: Decision Context (transforms the dashboard from data display to decision support)

Build third because it requires both pair statistics (Priority 1) and familiarity with the interface.

1. Contextual rate indicators on the existing funding rates panel (percentile, trend)
2. Signal score breakdown display (radar/bar chart of sub-signals)
3. Recommended action labels ("Strong opportunity", "Not recommended")
4. Funding rate glossary tooltips

**Rationale:** These features enhance existing dashboard panels with context. The user who has explored pairs (Priority 1) and understood backtest trades (Priority 2) is now ready for real-time decision support.

### Defer to v1.3+

- **Guided strategy builder wizard** -- valuable but not blocking. Users can manually navigate pair explorer -> backtest -> review results.
- **Trade replay mode** -- highest-value learning tool but highest complexity. Build after core features prove useful.
- **Parameter sensitivity preview** -- nice optimization but not needed when the user is still learning basics.
- **Rate regime annotations** -- interesting but requires calibration. Auto-detection thresholds need tuning against more data.
- **Multi-pair backtest comparison** -- straightforward extension once trade-level results work for single pairs.
- **Strategy template library** -- simple to add later, low urgency since the backtest form already works.

---

## Complexity Analysis

| Feature | Complexity | Effort Estimate | Risk | Existing Code Leverage |
|---------|------------|-----------------|------|----------------------|
| Per-pair aggregate statistics | Medium | 1-2 days | SQL query performance on 50K+ records | `HistoricalDataStore` queries exist, need aggregation |
| Pair ranking table | Low | 0.5-1 day | Sorting/filtering UX | Existing HTMX table patterns from funding rates panel |
| Rate time series chart | Low | 0.5 day | None | Chart.js + equity curve pattern directly reusable |
| Rate distribution histogram | Low | 0.5 day | Bin sizing | Chart.js bar chart |
| Fee-adjusted yield display | Low | 0.5 day | None | `OpportunityRanker` math already exists |
| Capture trades in BacktestResult | Low | 0.5 day | Serialization size | `PnLTracker.get_closed_positions()` already works |
| Trade log table | Low-Medium | 1 day | Table rendering with many columns | HTMX partial pattern |
| Per-trade P&L breakdown | Low | 0.5 day | None | `PositionPnL` already has all data |
| Win/loss categorization | Low | 0.5 day | None | `_net_return()` already in analytics/metrics.py |
| Trade-on-chart markers | Medium | 1 day | Chart.js annotation plugin integration | Equity curve chart pattern adaptable |
| Contextual rate indicators | Medium | 1-1.5 days | Percentile computation per pair | Need new aggregate query + UI enhancement |
| Signal score breakdown | Low | 0.5 day | None | `CompositeSignal` dataclass has all fields |
| Recommended action labels | Low | 0.5 day | Threshold calibration | Simple mapping from score + percentile |
| Pair comparison view | Medium | 1-1.5 days | Multi-series chart rendering | Chart.js supports multi-dataset |
| Tooltips/glossary | Low | 0.5 day | Content writing | Static HTML |
| Historical summary card | Low | 0.5 day | None | Aggregate query + template |

**Total estimated effort for table stakes:** 8-12 days across 3 priorities
**Total with differentiators:** 16-24 days

---

## Integration Points with Existing Code

These are the specific components that v1.2 features will extend or modify:

| Existing Component | How v1.2 Modifies It | Change Type |
|-------------------|---------------------|-------------|
| `BacktestResult` (backtest/models.py) | Add `trades: list[dict]` field containing serialized `PositionPnL` data for each trade | **Model extension** |
| `BacktestEngine.run()` (backtest/engine.py) | After `_compute_metrics()`, serialize `PnLTracker.get_closed_positions()` into the result | **Minor code change** |
| `HistoricalDataStore` (data/store.py) | Add aggregate query methods: `get_pair_statistics()`, `get_rate_distribution()`, `get_rate_percentile()` | **New methods** |
| Dashboard routes (dashboard/routes/pages.py) | Add routes: `/pairs` (pair explorer page), enhance `/backtest` to show trade log | **New routes** |
| Dashboard API routes (dashboard/routes/api.py) | Add endpoints: `/api/pairs/stats`, `/api/pairs/{symbol}/rates`, `/api/pairs/{symbol}/distribution` | **New endpoints** |
| Funding rates panel (templates/partials/funding_rates.html) | Add columns for historical context (percentile, trend, recommendation) | **Template enhancement** |
| Base template (templates/base.html) | Add navigation link to pair explorer page | **Minor template change** |
| `CompositeSignal` (signals/models.py) | No change needed -- already has all sub-scores for display | **Read-only use** |
| `OpportunityRanker` (market_data/opportunity_ranker.py) | No change needed -- reuse net yield calculation logic | **Read-only use** |

**Key insight:** Most v1.2 features are READ operations on data that already exists. The only significant CODE change is capturing trade-level data in `BacktestResult`. Everything else is new UI/routes that query existing stores.

---

## User Learning Journey

The feature set is designed to support a specific learning progression:

```
Stage 1: "What am I looking at?" (Pair Explorer)
  User opens pair explorer, sees ranking table
  Clicks on top-ranked pair, sees rate history chart
  Sees distribution histogram: "Oh, 0.01% is above average for this pair"
  Reads tooltip: "Funding rate is the periodic payment between longs and shorts"

Stage 2: "How would this have performed?" (Trade-Level Backtest)
  User runs backtest on the top-ranked pair
  Sees trade log: 15 trades over 30 days, 11 wins, 4 losses
  Expands winning trade: held 4 periods, collected $8.20 funding, paid $3.10 fees
  Expands losing trade: held 1 period, rate dropped, collected $1.50, paid $3.10 fees
  Sees trades on chart: "entries happen when rate spikes, exits when it drops"
  Insight: "Short trades lose because fees exceed single-period funding"

Stage 3: "What should I do now?" (Decision Context)
  User returns to main dashboard, sees enhanced funding rate panel
  ETHUSDT shows: rate=0.012%, percentile=78th, trend=rising, label="Strong opportunity"
  XRPUSDT shows: rate=0.005%, percentile=35th, trend=falling, label="Below average"
  Signal breakdown shows: rate_level=0.8, trend=0.9, persistence=0.7, basis=0.5
  User understands why ETHUSDT scores higher and is ready to configure the bot

Stage 4: "Can I try different approaches?" (Strategy Builder -- v1.3)
  User follows guided wizard to compare strategies
  Steps through trade replay to understand each decision
  Applies templates to quickly test different risk profiles
```

---

## Sources

### Competitive Analysis (MEDIUM confidence)
- [CoinGlass Funding Rate Arbitrage](https://www.coinglass.com/FrArbitrage) -- cross-exchange arbitrage table with APR, net funding rate, spread rate, OI columns
- [CoinGlass Funding Rate Heatmap](https://www.coinglass.com/FundingRateHeatMap) -- visual heatmap of rates across pairs/exchanges
- [Loris Tools Historical Funding](https://loris.tools/funding/historical) -- per-symbol analysis, BPS/APY toggle, multi-exchange overlay, 8h-30d timeframes
- [FundingView Strategy Finder](https://fundingview.app/strategy) -- historical APR calculations across timeframes (1d to 1y), exchange filtering, strategy discovery
- [Sharpe AI Funding Rate Dashboard](https://sharpe.ai/funding-rate) -- 200+ pair heatmap, real-time dashboard, pattern tracking
- [CryptoFundingTracker](https://cryptofundingtracker.com/) -- cross-platform rate comparison, discrepancy identification

### Backtesting UX (MEDIUM confidence)
- [Freqtrade Backtesting](https://www.freqtrade.io/en/stable/backtesting/) -- per-trade breakdown tables (entry tag, avg profit, win/draw/loss counts), web visualization, export to file
- [TradesViz](https://www.tradesviz.com/) -- 600+ stats, per-trade chart visualization with entry/exit/stops/MAE, customizable dashboard widgets
- [FX Replay](https://www.fxreplay.com/) -- trade replay stepping, P&L trend tracking, past trades on chart review

### Funding Rate Analysis (MEDIUM-HIGH confidence)
- [Zipmex: How to Analyze Funding Rates](https://zipmex.com/blog/how-to-analyze-funding-rates-in-crypto/) -- neutral rate ~0.01% per 8h, extreme readings (>0.05%, <-0.05%) as opportunity signals, multi-exchange comparison, OI correlation
- [Amberdata: Ultimate Guide to Funding Rate Arbitrage](https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata) -- OI as liquidity indicator, basis spread monitoring, delta-neutral maintenance
- [MadeInArk: Funding Rate Arbitrage Deep Dive](https://madeinark.org/funding-rate-arbitrage-and-perpetual-futures-the-hidden-yield-strategy-in-cryptocurrency-derivatives-markets/) -- 19.26% avg annual returns in 2025, <2% max drawdown, large vs small cap tradeoffs

### Strategy Discovery (MEDIUM confidence)
- [Gate.io: Perpetual Contract Funding Rate Arbitrage Strategy](https://www.gate.com/learn/articles/perpetual-contract-funding-rate-arbitrage/2166) -- high/stable rates, minimal price differences, high OI for liquidity, large vs small cap tradeoffs
- [1Token: Crypto Fund 101 Funding Fee Arbitrage](https://blog.1token.tech/crypto-fund-101-funding-fee-arbitrage-strategy/) -- conservative leverage on small caps, higher concentration acceptable on large caps
