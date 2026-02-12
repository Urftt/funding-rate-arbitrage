# Project Research Summary

**Project:** Funding Rate Arbitrage v1.1 - Strategy Intelligence
**Domain:** Cryptocurrency trading bot enhancement (backtesting, trend analysis, dynamic position sizing)
**Researched:** 2026-02-12
**Confidence:** MEDIUM-HIGH

## Executive Summary

This project enhances an existing, working funding rate arbitrage bot (v1.0) by adding intelligent strategy capabilities. The v1.0 bot successfully executes delta-neutral funding rate arbitrage using simple threshold-based decisions (enter at 0.03%, exit at 0.01%, fixed $1000 positions). v1.1 adds three capabilities: (1) backtesting infrastructure to validate strategy improvements, (2) funding rate trend analysis to make smarter entry/exit decisions, and (3) dynamic position sizing based on conviction scores.

The recommended approach is to build incrementally in strict dependency order: first the historical data foundation (aiosqlite for storage, ccxt for fetching), then signal analysis (EMA-based trend detection, persistence scoring), then backtest engine (reusing existing components via the Executor ABC pattern), and finally dynamic position sizing. The critical architectural principle is to extend, not replace - the v1.0 system works, and every v1.1 addition must preserve the ability to fall back to v1.0 behavior.

The primary risks are (1) look-ahead bias in backtesting making the strategy appear better than it is, (2) overfitting parameters to historical regimes that won't persist, and (3) breaking the working v1.0 system during integration. Mitigation: strict temporal data access controls, walk-forward validation instead of single train/test splits, and optional injection of all new components with feature flags. The research shows funding rate arbitrage is fundamentally different from price-action trading - standard technical indicators and backtesting frameworks do not apply. Custom, domain-specific implementations are required.

## Key Findings

### Recommended Stack

Research confirms the v1.0 stack (Python 3.12, ccxt, FastAPI, Decimal-based math) is solid. Three new dependencies are recommended: **numpy 2.4.0+** for array-based trend calculations (10-100x faster than pure Python loops), **scipy 1.17.0+** for statistical analysis (linear regression with p-values, grid search optimization), and **aiosqlite 0.22.0+** for async SQLite persistence of historical data.

**Core technologies:**
- **numpy**: Fast numerical computation for EMA, moving averages, z-scores - required by scipy, industry standard for array math
- **scipy**: Linear regression for trend detection (`scipy.stats.linregress`), grid search for parameter optimization (`scipy.optimize.brute`) - rigorous statistical tests without ML framework bloat
- **aiosqlite**: Async SQLite wrapper for historical data persistence - zero-infrastructure, integrates with existing asyncio architecture, sufficient for ~200K rows/year of funding rate data

**Why not pandas/polars:** Unnecessary DataFrame abstraction - we need array operations and time-series storage, not tabular transformations. NumPy + aiosqlite are leaner and match the existing codebase patterns.

**Why not PostgreSQL:** Adds operational complexity (server process, connection pooling, migrations) that SQLite avoids. Data volume is modest, single-instance deployment, no concurrent write contention.

**Why not Optuna:** Heavy dependency tree (SQLAlchemy, Alembic, colorlog, tqdm) for a small parameter space (3-5 parameters). Grid search via `scipy.optimize.brute` handles this trivially.

### Expected Features

**Must have (table stakes) - without these, "smarter strategy" is just marketing:**
- **Historical funding rate ingestion**: Fetch from Bybit API (`/v5/market/history-fund-rate`, 200 records/page) with pagination handling
- **Replay simulation engine**: Feed historical data through existing strategy logic in chronological order, reusing Executor ABC pattern
- **Fee-accurate P&L simulation**: Use existing FeeCalculator and PnLTracker - backtest must model realistic transaction costs (research shows 17% of apparent opportunities lose money after fees)
- **Funding rate trend detection**: Compare current rate to moving average, detect rising/falling/stable trends
- **Rate persistence scoring**: How long has rate stayed elevated - sustained rates are more reliable than spikes
- **Composite entry signal**: Multi-factor score (rate level + trend direction + persistence) replacing single threshold
- **Conviction-scaled sizing**: Higher funding rate + better signal = larger position (research shows Sharpe improves from 1.4 to 2.3 vs static sizing)
- **Strategy parameter sweep**: Grid search over thresholds and sizing parameters with backtest validation

**Should have (differentiators):**
- **Walk-forward validation**: Rolling window optimization (3-month train, 1-month test) to prevent overfitting to historical regimes
- **Spot-perp basis spread monitoring**: Basis z-score > 2 is a confirmed entry signal per academic literature
- **Volume-weighted filtering**: High rates on declining volume pairs are traps - insufficient exit liquidity
- **Drawdown-responsive sizing**: Reduce position sizes when portfolio is in drawdown (standard risk management)
- **Backtest visualization**: Equity curve, trade markers, parameter heatmap on dashboard

**Defer (v2+):**
- **Machine learning prediction**: Academic research shows DAR models provide modest predictability but ML complexity is not justified vs simple statistical signals
- **Cross-exchange arbitrage**: Different APIs, fee structures, capital transfer delays - massive complexity
- **Market regime classification**: High complexity, needs more live data to calibrate properly
- **Correlation-aware exposure**: Requires substantial historical price data infrastructure

### Architecture Approach

The v1.0 architecture has three strong patterns: (1) orchestrator-based scan-rank-decide-execute cycle, (2) dependency injection via `_build_components()`, and (3) swappable Executor ABC. v1.1 extends this cleanly by adding a fourth Executor implementation: `BacktestExecutor` fills orders from historical data instead of exchange API. This means the ENTIRE trading pipeline (PositionManager, PnLTracker, FeeCalculator, analytics) runs unchanged in backtests - no separate simulation logic, no drift between backtest and live behavior.

**Major components:**
1. **HistoricalDataStore** (`src/bot/data/store.py`) - aiosqlite-based persistence for funding rates, klines, market snapshots. Schema stores Decimal values as TEXT for precision. WAL mode for concurrent reads.
2. **SignalAnalyzer** (`src/bot/strategy/signal_analyzer.py`) - Pure computation module that reads historical data and produces SignalResult (trend direction, confidence score, entry/exit recommendations). No side effects, trivially testable.
3. **DynamicPositionSizer** (`src/bot/strategy/dynamic_sizer.py`) - Wraps existing PositionSizer, computes conviction-based target size, delegates to base sizer for exchange constraint handling (qty_step, min_notional). Preserves all v1.0 validation logic.
4. **BacktestEngine** (`src/bot/backtest/engine.py`) - Time-stepped replay: for each 8h funding period, set BacktestExecutor clock, feed historical data to mock monitors, run one orchestrator cycle, collect results from PnLTracker.
5. **BacktestExecutor** (`src/bot/backtest/executor.py`) - Implements Executor ABC, fills orders at historical prices with simulated slippage. The key that makes backtests reuse production code.

**Integration pattern:** All new components are **optional** (`| None = None` in orchestrator). This enables gradual rollout, feature flags (`strategy_mode: simple | intelligent`), and preserves v1.0 regression tests. The orchestrator adds steps 3-4 (ANALYZE signals, SIZE positions) between existing RANK and DECIDE steps.

### Critical Pitfalls

1. **Look-ahead bias in backtesting** - Bybit's historical endpoint returns SETTLED rates, but live trading uses PREDICTED rates (different numbers). Backtesting with settled rates = false confidence. **Mitigation:** Store both predicted and settled rates, enforce `as_of` timestamp for all data access, validate backtest vs recent paper trading results.

2. **Overfitting to historical regimes** - Funding rate patterns are non-stationary, shift every 3-6 months with market regime. Grid search on 6 months finds noise. **Mitigation:** Walk-forward validation with rolling 3-month train / 1-month test windows, parameter stability checks (reject if optimal params shift >30% between folds), hard bounds on Sharpe >3.0 as overfitting warning.

3. **Breaking the working v1.0 system** - Adding intelligence layer changes orchestrator decision path. A bug could make existing paper/live trading malfunction. **Mitigation:** Extract strategy interface before adding intelligence, feature flags with `simple` as default, regression test suite from v1.0 that must pass unchanged, read-only intelligence (components advise, orchestrator decides).

4. **Survivorship bias in historical data** - Bybit API only returns data for currently listed pairs. Delisted pairs (5-15% annually, often the high-rate illiquid ones) are invisible. **Mitigation:** Build historical pair registry (snapshot pairs weekly), document excluded pairs, apply 5-10% adjustment for delisting risk in backtest returns.

5. **Trend indicators producing false signals** - Funding rates are mean-reverting (8h settlements, by-design convergence), not trending. Standard TA indicators (MACD, RSI) designed for price series produce excessive false signals. **Mitigation:** Use short-window EMAs (3-5 periods = 1-1.7 days) for regime detection, focus on rate-of-change vs absolute trends, always benchmark against v1.0 simple threshold baseline.

## Implications for Roadmap

Based on research, strict dependency ordering is critical. Each phase must be validated before proceeding to avoid cascading failures.

### Phase 1: Historical Data Foundation
**Rationale:** Everything else depends on historical data. Without persistence, neither signal analysis nor backtesting have inputs. Build the data layer first, validate data quality before consuming it.

**Delivers:**
- HistoricalDataStore (aiosqlite schema, async read/write methods)
- HistoricalDataFetcher (Bybit API pagination handler, backfill logic)
- ExchangeClient extensions (`fetch_funding_rate_history`, `fetch_klines`)
- Data quality validation (gap detection, duplicate checks, interval consistency)

**Addresses:** Historical data ingestion (table stakes), 90-day backfill capability

**Avoids:** Pitfall #7 (API rate limits via throttling), Pitfall #10 (data gaps via validation pipeline), Pitfall #4 (survivorship bias via pair registry)

**Stack:** aiosqlite 0.22.0+, ccxt extensions

**Research flag:** SKIP - Bybit API is well-documented, aiosqlite is mature, integration pattern is straightforward.

### Phase 2: Signal Analysis
**Rationale:** Pure computation on stored data. Can be validated independently without backtest engine. Provides immediate value to live trading even before backtesting is complete.

**Delivers:**
- SignalAnalyzer module with trend detection (EMA crossover)
- Rate persistence scoring (consecutive periods above threshold)
- Composite signal calculation (trend + persistence + stability)
- SignalResult model with confidence scores

**Addresses:** Trend detection, persistence scoring, composite entry signal (table stakes)

**Uses:** numpy for array operations, scipy.stats for regression

**Avoids:** Pitfall #5 (false signals via mean-reversion-aware indicators, short windows)

**Stack:** numpy 2.4.0+, scipy 1.17.0+

**Research flag:** MODERATE - Standard pattern (EMA crossover) but funding rate domain specifics need empirical validation against v1.0 baseline.

### Phase 3: Orchestrator Integration
**Rationale:** Wire signal analysis into live trading before backtesting. Validates that the integration doesn't break v1.0, enables A/B testing signal quality in paper mode, provides real-world signal data for backtest calibration.

**Delivers:**
- Orchestrator modifications (add ANALYZE step, enrich OpportunityScore)
- FundingMonitor auto-persistence (write live data to store)
- Configuration extensions (SignalSettings, feature flags)
- Main.py wiring with optional injection

**Addresses:** Integration of trend signals into decision flow

**Avoids:** Pitfall #3 (breaking v1.0 via strategy interface extraction, feature flags, regression tests)

**Architecture:** Extend, don't replace - all new components are optional

**Research flag:** SKIP - Integration pattern follows established v1.0 dependency injection, well-understood.

### Phase 4: Backtest Engine
**Rationale:** Requires historical data (Phase 1) and signal logic (Phase 2). Validates strategy improvements before deploying dynamic sizing. Parameter optimization is meaningless without backtest results.

**Delivers:**
- BacktestExecutor implementing Executor ABC
- BacktestEngine with time-stepped replay
- v1.0 baseline strategy simulation (SimpleThresholdStrategy)
- BacktestResult models and analytics
- Parameter grid search framework

**Addresses:** Replay simulation, fee-accurate P&L, parameter sweep (table stakes)

**Uses:** All existing components (PositionManager, PnLTracker, FeeCalculator) via Executor pattern

**Avoids:** Pitfall #1 (look-ahead bias via strict temporal access), Pitfall #2 (overfitting via walk-forward validation), Pitfall #14 (wrong baseline via v1.0 simulation first)

**Architecture:** BacktestExecutor reuses production components - no separate simulation logic

**Research flag:** MODERATE - Custom backtest engine (not framework-based), need to validate temporal ordering, test against known outcomes.

### Phase 5: Dynamic Position Sizing
**Rationale:** Build last because sizing changes affect real money and must be backtested (Phase 4) before live deployment. Sizing parameters need optimization from backtest results.

**Delivers:**
- DynamicPositionSizer wrapping existing PositionSizer
- Conviction-based scaling (signal confidence -> position size)
- Risk constraints (portfolio exposure limit, drawdown-responsive sizing)
- DynamicSizingSettings configuration

**Addresses:** Conviction-scaled sizing, risk-constrained sizing (table stakes)

**Uses:** Signal confidence from Phase 2, backtest validation from Phase 4

**Avoids:** Pitfall #8 (backtest-based sizing via conservative bounds), Pitfall #9 (correlation risk via portfolio-level exposure limits)

**Architecture:** Wraps, doesn't replace - delegates to base PositionSizer for exchange constraints

**Research flag:** SKIP - Position sizing math is well-understood, integration pattern is clear.

### Phase 6: Dashboard Extensions
**Rationale:** Display layer for features built in previous phases. Not on critical path for strategy intelligence. Can be built after core functionality is validated.

**Delivers:**
- Backtest results visualization (equity curve, parameter heatmap)
- Signal indicators on opportunity table (confidence scores)
- Backtest trigger UI

**Addresses:** Backtest visualization (table stakes)

**Research flag:** SKIP - FastAPI + HTMX pattern established in v1.0.

### Phase Ordering Rationale

- **Data before analysis:** Can't compute trends without historical data (Phase 1 before 2)
- **Analysis before optimization:** Can't optimize parameters without backtest validation (Phase 2-4 before 5)
- **Validate before deploy:** Signal integration (Phase 3) proves non-breaking before adding more complexity
- **Backtest before dynamic sizing:** Sizing changes are high-risk, must be backtested first (Phase 4 before 5)
- **Display last:** Dashboard extensions don't block functionality (Phase 6 deferred)

The linear dependency chain prevents premature optimization and ensures each layer is validated before the next is built. Funding rate arbitrage domain specifics (8h settlement cycles, mean-reverting rates, dual-leg positions) make standard frameworks unsuitable - custom implementations are required at every layer.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 2 (Signal Analysis):** Funding rate trend behavior needs empirical validation. Standard indicators may not work. Plan to spend time on A/B testing signal variations against v1.0 baseline.
- **Phase 4 (Backtest Engine):** Temporal ordering and look-ahead bias prevention are subtle. Plan validation against known periods where v1.0 paper trading results exist.

**Phases with standard patterns (minimal research):**
- **Phase 1 (Data Foundation):** aiosqlite integration is well-documented, Bybit API is official and verified
- **Phase 3 (Orchestrator Integration):** Follows established v1.0 dependency injection pattern
- **Phase 5 (Dynamic Sizing):** Position sizing math is standard, wrapper pattern is clear
- **Phase 6 (Dashboard):** FastAPI + HTMX pattern already used in v1.0

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommended libraries verified via official docs, version compatibility confirmed for Python 3.12, existing v1.0 stack is proven |
| Features | MEDIUM | Table stakes features (backtesting, trend analysis, sizing) are industry-standard, but funding rate domain specifics need empirical validation. Academic research confirms trends exist but predictability is "time-varying" |
| Architecture | HIGH | Executor ABC pattern extension is natural, aiosqlite integration is straightforward, component boundaries are clear. Based on analysis of actual v1.0 codebase. |
| Pitfalls | MEDIUM | Look-ahead bias and overfitting are well-documented in backtesting literature. Funding rate specifics (predicted vs settled rates, mean-reversion) come from Bybit API docs + academic papers but need implementation-time validation |

**Overall confidence:** MEDIUM-HIGH

The recommended approach is sound and builds on a proven v1.0 foundation. The primary uncertainty is around funding rate trend analysis effectiveness - academic research confirms predictability exists but is "modest" and "time-varying." The mitigation is to always benchmark against v1.0's simple threshold baseline and only deploy improvements that demonstrably outperform on out-of-sample data.

### Gaps to Address

**During Phase 2 (Signal Analysis):**
- Optimal EMA window sizes for 8h funding rate data need empirical determination - research suggests 3-9 periods but this must be validated against v1.0 baseline across multiple regimes
- Composite signal weighting (how much weight on trend vs persistence vs stability) requires parameter sweep and backtest validation

**During Phase 4 (Backtest Engine):**
- Predicted vs settled funding rate relationship needs measurement - research confirms they differ but exact magnitude per pair/regime is unknown. May need to fetch both from API during backfill.
- Realistic slippage modeling for different pair liquidity levels needs calibration - 5bps baseline may be too optimistic for low-volume pairs during high-funding periods

**During deployment:**
- Market regime changes every 3-6 months per research - plan quarterly review of strategy parameters against live results, be prepared to revert to v1.0 if v1.1 underperforms for 50+ trades

**Documentation needed:**
- Explicit rollback procedure (feature flag to `strategy_mode=simple`)
- A/B testing framework (run v1.0 and v1.1 side-by-side in paper mode for 2 weeks before live)

## Sources

### Primary (HIGH confidence)
- Bybit Official API Documentation: funding rate history endpoint (`/v5/market/history-fund-rate`), kline endpoint (`/v5/market/kline`), rate limits (600 req/5s per IP)
- NumPy 2.4.2 release notes (Feb 2026, Python 3.12 support verified)
- SciPy 1.17.0 release notes (Jan 2026, NumPy 1.26.4+ dependency verified)
- aiosqlite 0.22.1 PyPI page (Dec 2025, async SQLite wrapper)
- Existing v1.0 codebase analysis: orchestrator.py, executor.py, position/sizing.py, main.py, config.py

### Secondary (MEDIUM confidence)
- Academic: "Predictability of Funding Rates" (SSRN) - DAR models, autocorrelation weak beyond 3 lags, mean-reversion dynamics
- Academic: "Two-Tiered Structure of Funding Rate Markets" (MDPI) - 17% of opportunities lose money after fees
- Industry: Amberdata guide to funding rate arbitrage - multi-factor signals, OI confirmation
- Industry: MadeInArk funding rate analysis - regime-aware returns (52% bull vs 8.7% bear)
- Backtesting: QuantStart event-driven backtesting pattern, QuantInsti walk-forward optimization

### Tertiary (LOW confidence, needs validation)
- ccxt GitHub issues (#15990, #17854) - Bybit pagination bugs documented but workarounds may have changed since reports
- Kelly Criterion position sizing - fractional Kelly (quarter to half) recommended for crypto volatility, but funding rate arbitrage may not fit Kelly assumptions

---
*Research completed: 2026-02-12*
*Ready for roadmap: YES*
