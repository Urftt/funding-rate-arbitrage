# Funding Rate Arbitrage Bot

## What This Is

A fully automated funding rate arbitrage bot for Bybit that exploits the spread between spot and perpetual futures markets. It scans all trading pairs for favorable funding rates, opens delta-neutral positions (long spot + short perp), collects funding payments, and exits when conditions deteriorate. Includes composite signal analysis, backtesting with parameter optimization, dynamic position sizing, and a real-time web dashboard for monitoring, control, and performance analytics. Built primarily as a learning project with real profit potential.

## Core Value

The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.

## Requirements

### Validated

- ✓ MKTD-01: Real-time funding rates for all Bybit perpetual pairs — v1.0
- ✓ MKTD-02: Ranks all pairs by funding rate opportunity (net yield after fees) — v1.0
- ✓ MKTD-03: Only enters positions when funding rate exceeds configurable minimum — v1.0
- ✓ EXEC-01: Opens delta-neutral positions (spot buy + perp short) simultaneously — v1.0
- ✓ EXEC-02: Automatically closes positions when funding rate drops below exit threshold — v1.0
- ✓ EXEC-03: Calculates position size with Decimal precision, respecting balance and leverage — v1.0
- ✓ EXEC-04: Accounts for entry and exit fees when evaluating profitability — v1.0
- ✓ RISK-01: Enforces maximum position size per trading pair — v1.0
- ✓ RISK-02: Enforces maximum number of simultaneously open positions — v1.0
- ✓ RISK-03: Emergency stop closes all open positions (SIGUSR1 signal) — v1.0
- ✓ RISK-04: Continuous delta neutrality validation (spot qty matches perp qty) — v1.0
- ✓ RISK-05: Monitors margin ratio with configurable alert thresholds — v1.0
- ✓ PAPR-01: Paper trading mode with simulated execution and virtual balances — v1.0
- ✓ PAPR-02: Paper trading uses identical logic path as real trading (swappable executor) — v1.0
- ✓ PAPR-03: Paper mode tracks P&L including simulated fees and funding payments — v1.0
- ✓ DASH-01: View open positions with pair, entry price, size, P&L, funding collected — v1.0
- ✓ DASH-02: Funding rate overview across all Bybit perpetual pairs — v1.0
- ✓ DASH-03: Trade history with timestamps, realized P&L, cumulative profit — v1.0
- ✓ DASH-04: Start/stop bot with status and error alerts — v1.0
- ✓ DASH-05: Balance breakdown (available vs allocated capital) — v1.0
- ✓ DASH-06: Configure strategy parameters via dashboard form — v1.0
- ✓ DASH-07: Performance analytics (Sharpe ratio, max drawdown, win rate) — v1.0
- ✓ DATA-01: Fetches and stores historical funding rates with pagination — v1.1
- ✓ DATA-02: Fetches and stores historical OHLCV price data — v1.1
- ✓ DATA-03: Historical data persists via SQLite storage — v1.1
- ✓ DATA-04: Handles API rate limits and resumes from last point — v1.1
- ✓ SGNL-01: Detects funding rate trend direction using EMA — v1.1
- ✓ SGNL-02: Scores rate persistence (consecutive elevated periods) — v1.1
- ✓ SGNL-03: Computes composite entry signal (rate + trend + persistence) — v1.1
- ✓ SGNL-04: Monitors spot-perp basis spread as signal — v1.1
- ✓ SGNL-05: Filters by volume trend (avoid declining volume pairs) — v1.1
- ✓ SGNL-06: Composite signal replaces threshold with feature flag revert — v1.1
- ✓ BKTS-01: Replays historical data chronologically without look-ahead bias — v1.1
- ✓ BKTS-02: Reuses production FeeCalculator and PnLTracker — v1.1
- ✓ BKTS-03: Parameter sweep over thresholds and signal weights — v1.1
- ✓ BKTS-04: Dashboard with equity curve and parameter heatmap — v1.1
- ✓ BKTS-05: Simulates v1.0 and v1.1 strategies side-by-side — v1.1
- ✓ SIZE-01: Position size scales with signal confidence — v1.1
- ✓ SIZE-02: Total portfolio exposure capped at configurable limit — v1.1
- ✓ SIZE-03: Delegates to existing PositionSizer for exchange constraints — v1.1

### Active

## Current Milestone: v1.2 Strategy Discovery

**Goal:** Enable learning-driven strategy development through historical pair analysis, profitability visualization, and iterative backtesting — so the user can build intuition about what works before committing capital.

**Target features:**
- Pair Explorer: Browse top ~20 pairs by market cap with funding rate history, distribution stats, and net yield calculations
- Trade Replay: Enhanced backtesting showing individual simulated trades with entry/exit reasons, holding periods, and fee-adjusted P&L
- Strategy Builder: Tweak parameters and test across selected pairs, comparing configurations to find consistent profitability
- Decision View: Summary dashboard that answers "should I turn this on?" with historical evidence

### Out of Scope

- Cross-exchange arbitrage — keeping it single-exchange (Bybit) for simplicity
- Mobile app — web dashboard is sufficient
- Telegram/Discord notifications — dashboard covers monitoring needs
- Multiple strategy types — funding rate arb only
- High-frequency trading — 8hr funding cycles tolerate minute-scale latency
- Leveraged spot positions — keep spot unleveraged, only perp side uses leverage
- Machine learning prediction — simple statistical signals capture 80% of value
- Genetic/Bayesian optimization — grid search sufficient for 3-5 parameter space
- Real-time strategy switching — adjust parameters within single strategy instead

## Context

- **Shipped:** v1.0 MVP (2026-02-11) + v1.1 Strategy Intelligence (2026-02-12) + v1.2 Strategy Discovery (in progress)
- **Codebase:** 9,540 lines of Python + 1,320 lines of HTML + 6,246 lines of tests across ~100 files
- **Tech stack:** Python 3.12, ccxt (Bybit), FastAPI, HTMX, Tailwind CSS, Chart.js, structlog, asyncio, Decimal arithmetic, SQLite (WAL mode)
- **Architecture:** Orchestrator pattern with dependency injection, swappable executor (paper/live), optional signal engine, dynamic sizer, signal-based emergency stop
- **Dashboard:** FastAPI + Jinja2 + HTMX with WebSocket real-time updates, 8 panels (positions, rates, history, status, balance, config, analytics, data status) + backtest page
- **Testing:** 286 tests covering all modules (TDD for fee calculator, position sizer, opportunity ranker, analytics, dynamic sizer)
- **Known areas for improvement:** Bybit fee structure verification needed, look-ahead bias risk (predicted vs settled funding rates), funding rate trend mean-reversion characteristics

## Constraints

- **Tech stack**: Python — ecosystem strength for trading (ccxt, pandas, async)
- **Exchange**: Bybit only — no multi-exchange complexity
- **Risk**: Moderate — reasonable position sizes, some tolerance for temporary funding dips, but exit on sustained unfavorable conditions
- **Scope**: Paper trading must work before any real money integration

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single exchange (Bybit) | Reduces complexity, faster to build and learn | ✓ Good — ccxt abstraction makes adding exchanges possible later |
| Paper trading first | Validate logic before risking capital | ✓ Good — caught several edge cases in simulation |
| Python | Best ecosystem for trading bots (ccxt, pandas, async support) | ✓ Good — async/await fits naturally |
| Web dashboard over CLI | Need visual overview of positions, rates, and P&L | ✓ Good — HTMX keeps it simple, no frontend build |
| Spot-perp delta neutral | Simpler than cross-exchange, proven strategy | ✓ Good — well-defined implementation |
| Decimal arithmetic everywhere | Prevent floating-point errors in financial calculations | ✓ Good — no precision issues |
| Swappable executor pattern | Same codebase for paper and live trading | ✓ Good — parameterized tests prove identical behavior |
| REST polling for funding rates | Rates change every 8h, WebSocket unnecessary | ✓ Good — simple and reliable |
| structlog with contextvars | Async-safe structured logging | ✓ Good — clean correlated logs |
| FastAPI + HTMX + Tailwind CDN | Minimal dashboard without frontend build complexity | ✓ Good — zero build step, real-time via WebSocket |
| RuntimeConfig overlay | Dashboard can modify settings without restart | ✓ Good — applied at cycle start |
| Signal-based emergency stop | SIGUSR1 triggers immediate position close | ✓ Good — works from CLI and dashboard |
| Optional dependency injection for v1.1 | `Component \| None = None` pattern preserves v1.0 behavior | ✓ Good — zero regressions, graceful degradation |
| strategy_mode feature flag | "simple" preserves v1.0, "composite" enables v1.1 signals | ✓ Good — safe rollout, easy comparison |
| SQLite with WAL mode | Persistent historical data without external database | ✓ Good — 50K+ records, instant resume |
| Backward pagination for Bybit API | endTime parameter required, startTime alone unreliable | ✓ Good — handles API quirks correctly |
| BacktestExecutor via Executor ABC | Same interface for live and simulated trading | ✓ Good — production components reused in backtests |
| BacktestDataStoreWrapper time-travel | Caps queries at simulated time to prevent look-ahead | ✓ Good — clean separation of concerns |
| Chart.js CDN for equity curves | Matches existing HTMX/CDN dashboard pattern | ✓ Good — no build step, rich visualization |
| Linear interpolation for dynamic sizing | Simplest mapping from signal score to allocation | ✓ Good — configurable, backtestable |

---
*Last updated: 2026-02-13 after v1.2 milestone start*
