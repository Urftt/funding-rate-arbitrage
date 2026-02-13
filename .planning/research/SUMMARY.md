# Research Summary: v1.2 Strategy Discovery & Pair Explorer

**Domain:** Pair profitability analysis, statistical distribution visualization, market cap filtering, trade-level backtest output, decision support
**Researched:** 2026-02-13
**Overall confidence:** HIGH

## Executive Summary

This milestone adds a read-only analysis and visualization layer to the existing funding rate arbitrage bot. The v1.1 system has a working backtesting engine, composite signal engine, and 50K+ historical funding rate records in SQLite. What it lacks is the ability to explore pairs comparatively, inspect individual backtest trades, visualize statistical distributions, and filter by market capitalization. The user can run backtests but cannot answer "which pairs should I even be looking at?"

The key finding is that **zero new Python dependencies are needed**. The existing numpy (for statistical computation and histogram binning), aiosqlite (for aggregate SQL queries), and Chart.js (for chart rendering) handle all new visualization requirements. The only addition is a single CDN script tag for `@sgratzl/chartjs-chart-boxplot@4.4.5` to enable box plot and violin plot charts in Chart.js, plus occasional HTTP calls to CoinGecko's free API for market cap data.

The architecture adds a `PairAnalyzer` service (read-only SQL aggregation + numpy statistics), a `MarketCapCache` (CoinGecko data fetched once per 24 hours via stdlib urllib), and a `BacktestTrade` model extension (surface per-trade data that PnLTracker already captures internally). All new features are dashboard-facing -- they do not modify the trading engine, signal engine, or execution path.

The primary risks are (1) misleading pair rankings from insufficient data (pairs with 3 days of history appearing alongside pairs with 3 months), (2) dashboard performance degradation from unoptimized aggregate queries on 50K+ records, and (3) CoinGecko symbol mapping failures causing market cap tiers to be wrong or missing. All are solvable with standard practices: minimum data thresholds, SQL GROUP BY aggregation with caching, and manual symbol override mappings.

## Key Findings

**Stack:** Zero new Python dependencies. One CDN script addition (`@sgratzl/chartjs-chart-boxplot@4.4.5`). One external API (CoinGecko free tier, 1 call per 24 hours).

**Architecture:** Read-only analysis layer on existing data store. New `PairAnalyzer` module for per-pair statistics. Extended `BacktestResult` with trade-level detail. New `/pair-explorer` dashboard page following existing HTMX partial pattern.

**Critical pitfall:** Misleading pair rankings when data completeness varies widely across pairs. Must enforce minimum data thresholds and display record counts prominently.

## Implications for Roadmap

Based on research, suggested phase structure:

### 1. Pair Analysis Foundation -- build the data pipeline and page structure first

**Rationale:** All other features (distribution charts, market cap filtering, trade detail) depend on per-pair statistical aggregation and the pair explorer page. Building the ranking table and basic charts first creates the foundation everything else plugs into.

**Addresses:**
- Per-pair profitability ranking (FEATURES.md: table stakes)
- Historical rate summary per pair (FEATURES.md: table stakes)
- Date range filtering (FEATURES.md: table stakes)
- Per-pair funding rate time series chart (FEATURES.md: table stakes)

**Avoids:**
- Misleading rankings from incomplete data (PITFALLS.md: #1) -- by implementing minimum data thresholds
- Dashboard performance degradation (PITFALLS.md: #2) -- by using aggregate SQL from the start

**Stack used:** aiosqlite (existing), numpy (existing), Chart.js (existing), HTMX (existing)

### 2. Enhanced Backtest Output -- surface trade-level data that already exists

**Rationale:** The PnLTracker already captures per-trade data (entry/exit timestamps, funding payments, fees). This phase simply surfaces it in the BacktestResult model and renders it in the dashboard. Low risk because no new computation is needed, just serialization and display.

**Addresses:**
- Trade-level detail in backtest results (FEATURES.md: table stakes)
- Trade P&L distribution visualization (FEATURES.md: table stakes)
- Trade duration analysis (FEATURES.md: table stakes)
- Decision explanation view (FEATURES.md: differentiator)

**Avoids:**
- API response bloat (PITFALLS.md: #4) -- by paginating trade data separately

**Stack used:** Existing dataclasses, numpy.histogram() for distributions, Chart.js bar/scatter charts

### 3. Distribution Visualization & Market Cap -- add statistical depth

**Rationale:** Box plots and histograms require the pair explorer page (Phase 1) to exist. Market cap filtering requires external API integration (CoinGecko) which adds a failure point. Building these after core analysis reduces risk.

**Addresses:**
- Funding rate distribution per pair (FEATURES.md: table stakes)
- Cross-pair distribution comparison (FEATURES.md: table stakes)
- Market cap tier filtering (FEATURES.md: differentiator)

**Avoids:**
- CoinGecko symbol mapping failures (PITFALLS.md: #3) -- by treating market cap as optional enhancement
- Box plot CDN failures (PITFALLS.md: #6) -- by adding graceful fallback

**Stack used:** @sgratzl/chartjs-chart-boxplot (CDN, new), numpy.histogram() (existing), CoinGecko API (new, free tier)

### 4. Decision Context Enhancement -- add contextual intelligence to existing panels

**Rationale:** Requires pair statistics (Phase 1) and user familiarity with the interface. Enhances existing dashboard panels rather than creating new ones. Lower priority because it depends on historical data quality proven in earlier phases.

**Addresses:**
- "Is this rate good?" contextual indicator (FEATURES.md: table stakes)
- Signal score breakdown display (FEATURES.md: table stakes)
- Recommended action labels (FEATURES.md: table stakes)
- Funding rate glossary tooltips (FEATURES.md: differentiator)

**Phase ordering rationale:**
- Phase 1 before all others: the pair explorer page and aggregation pipeline are prerequisites for everything
- Phase 2 independent of Phase 1 UI: trade-level output is a backtest engine change, can be built in parallel with Phase 1 if needed
- Phase 3 after Phase 1: box plots and market cap enhance the pair explorer that must exist first
- Phase 4 after Phase 1: contextual indicators require per-pair statistics to be computed

**Research flags for phases:**
- Phase 1: Standard patterns (SQL aggregation, Chart.js rendering), unlikely to need research
- Phase 2: Standard patterns (model extension, data serialization), unlikely to need research
- Phase 3: Box plot CDN integration needs integration testing; CoinGecko symbol mapping needs manual verification for top pairs
- Phase 4: Signal score display is straightforward; recommended action label thresholds may need tuning

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new Python deps. Chart.js boxplot plugin verified on jsDelivr. CoinGecko free tier verified. |
| Features | HIGH | All features are read-only analysis on existing data. No new data collection, no trading logic changes. |
| Architecture | HIGH | Read-only analysis layer with clear boundaries. PairAnalyzer is pure computation. No trading engine modifications. |
| Pitfalls | HIGH | Primary risks (data completeness, query performance, symbol mapping) are well-understood with standard mitigations. |

## Gaps to Address

- **CoinGecko symbol mapping:** Need to build and verify manual override mapping for top 50 Bybit perpetual pairs. Cannot be fully automated -- requires manual verification.
- **SQL query performance:** Need to benchmark aggregate queries on the actual 50K+ record dataset. May need additional indexes if GROUP BY queries are slow.
- **Box plot plugin CDN reliability:** Need fallback strategy if jsDelivr is unavailable. Consider self-hosting the 50KB UMD build if CDN proves unreliable.
- **Trade data volume:** Need to measure actual JSON response sizes for backtests with 100+ trades. May need pagination threshold tuning.
- **Histogram bin strategy:** Default `bins="auto"` may not work well for bimodal funding rate distributions. Need to test with real data and potentially use `bins="fd"` or fixed bin counts.

## Sources

### Stack (HIGH confidence)
- [@sgratzl/chartjs-chart-boxplot v4.4.5](https://www.jsdelivr.com/package/npm/@sgratzl/chartjs-chart-boxplot) -- CDN verified, Chart.js 4 compatible, published Oct 2025
- [CoinGecko API /coins/markets](https://docs.coingecko.com/reference/coins-markets) -- free tier 30 calls/min, 10K/month, market_cap field
- [numpy.histogram](https://numpy.org/doc/stable/reference/generated/numpy.histogram.html) -- bin computation with auto/sturges/fd strategies
- [Chart.js Bar Chart](https://www.chartjs.org/docs/latest/charts/bar.html) -- histogram via zero-gap bar chart

### Features (MEDIUM-HIGH confidence)
- [CoinGlass Funding Rate Tools](https://www.coinglass.com/FrArbitrage) -- competitive analysis for pair ranking UI
- [Freqtrade Backtesting](https://www.freqtrade.io/en/stable/backtesting/) -- trade-level output patterns
- [TradesViz](https://www.tradesviz.com/) -- trade-on-chart visualization patterns

### Architecture (HIGH confidence)
- Existing codebase: `src/bot/backtest/engine.py`, `src/bot/data/store.py`, `src/bot/dashboard/routes/api.py`
- Existing dashboard patterns: HTMX partials, Chart.js CDN, Jinja2 templates

---
*Research completed: 2026-02-13*
*Ready for roadmap: YES*
