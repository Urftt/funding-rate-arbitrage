# Milestones

## v1.0 MVP (Shipped: 2026-02-11)

**Phases completed:** 3 phases, 14 plans, ~28 tasks
**Lines of code:** 9,484 Python + 386 HTML
**Files changed:** 115 (19,906 insertions)
**Timeline:** 1 day (2026-02-10 → 2026-02-11)
**Git range:** feat(01-01) → feat(03-05)

**Delivered:** Fully automated funding rate arbitrage bot with paper trading, autonomous multi-pair execution, risk management, and real-time web dashboard.

**Key accomplishments:**
1. Complete paper trading engine with delta-neutral spot+perp execution and swappable executor pattern (PAPR-01/02/03)
2. Autonomous scan-rank-decide-execute cycle that opens/closes positions based on funding rate profitability (MKTD-02/03, EXEC-02)
3. Comprehensive risk management: per-pair limits, margin monitoring, signal-based emergency stop (RISK-01/02/03/04/05)
4. Performance analytics (Sharpe ratio, max drawdown, win rate) with full Decimal precision and TDD (DASH-07)
5. Real-time web dashboard with 7 panels, HTMX/WebSocket live updates, and bot controls (DASH-01 through DASH-07)
6. Single entry point running bot + dashboard in one asyncio event loop via programmatic uvicorn

**All 22 v1 requirements shipped.**

See `.planning/milestones/v1.0-ROADMAP.md` for full details.

---

## v1.1 Strategy Intelligence (Shipped: 2026-02-12)

**Phases completed:** 4 phases (4-7), 12 plans, ~24 tasks
**Lines of code:** 9,540 Python + 1,320 HTML (+ 6,246 test LOC)
**Files changed:** 81 (13,583 insertions)
**Timeline:** 1 day (2026-02-12)
**Git range:** feat(04-01) → docs(phase-07)

**Delivered:** Intelligent strategy engine with composite signals (trend, persistence, basis spread, volume), backtesting with parameter optimization, dynamic position sizing, and dashboard backtest visualization — all validated against v1.0 baseline.

**Key accomplishments:**
1. Persistent historical data pipeline: async SQLite store with 50,919 records (funding rates + OHLCV), backward pagination, fetch state resume, and dashboard data status widget (DATA-01/02/03/04)
2. Composite signal engine: EMA trend detection, persistence scoring, basis spread, volume filtering — weighted into single signal score with strategy_mode feature flag preserving v1.0 behavior (SGNL-01/02/03/04/05/06)
3. Full backtesting engine: event-driven historical replay using production FeeCalculator/PnLTracker/PositionManager, look-ahead prevention via time-bounded data wrapper (BKTS-01/02)
4. Parameter optimization: grid search sweep over thresholds and signal weights with v1.0 vs v1.1 comparison mode (BKTS-03/05)
5. Dashboard backtest page: Chart.js equity curve, parameter heatmap, background task execution with async polling, comparison table (BKTS-04)
6. Dynamic position sizing: signal-conviction scaling with portfolio exposure cap, delegating to existing PositionSizer for exchange constraints (SIZE-01/02/03)

**All 18 v1.1 requirements shipped. 286 tests passing.**

See `.planning/milestones/v1.1-ROADMAP.md` for full details.

---

