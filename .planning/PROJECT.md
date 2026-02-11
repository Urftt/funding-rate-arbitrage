# Funding Rate Arbitrage Bot

## What This Is

A fully automated funding rate arbitrage bot for Bybit that exploits the spread between spot and perpetual futures markets. It scans all trading pairs for favorable funding rates, opens delta-neutral positions (long spot + short perp), collects funding payments, and exits when conditions deteriorate. Includes a real-time web dashboard for monitoring, control, and performance analytics. Built primarily as a learning project with real profit potential.

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

### Active

(No active requirements — planning next milestone)

### Out of Scope

- Cross-exchange arbitrage — keeping it single-exchange (Bybit) for simplicity
- Mobile app — web dashboard is sufficient
- Telegram/Discord notifications — dashboard covers monitoring needs for v1
- Leverage optimization — moderate fixed approach first, tuning later
- Multiple strategy types — funding rate arb only
- High-frequency trading — 8hr funding cycles tolerate minute-scale latency
- Leveraged spot positions — keep spot unleveraged, only perp side uses leverage

## Context

- **Shipped:** v1.0 MVP with 9,484 lines of Python + 386 lines of HTML across 60 files
- **Tech stack:** Python 3.12, ccxt (Bybit), FastAPI, HTMX, Tailwind CSS, structlog, asyncio, Decimal arithmetic
- **Architecture:** Orchestrator pattern with dependency injection, swappable executor (paper/live), signal-based emergency stop
- **Dashboard:** FastAPI + Jinja2 + HTMX with WebSocket real-time updates, 7 panels covering all DASH requirements
- **Testing:** 206+ tests covering all modules (TDD for fee calculator, position sizer, opportunity ranker, analytics)
- **Known areas for improvement:** Bybit fee structure verification needed, margin calculation during volatility, persistent trade history (currently in-memory)

## Constraints

- **Tech stack**: Python — ecosystem strength for trading (ccxt, pandas, async)
- **Exchange**: Bybit only — no multi-exchange complexity
- **Risk**: Moderate — reasonable position sizes, some tolerance for temporary funding dips, but exit on sustained unfavorable conditions
- **v1 scope**: Paper trading must work before any real money integration

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
| REST polling for funding rates | Rates change every 8h, WebSocket unnecessary for Phase 1 | ✓ Good — simple and reliable |
| structlog with contextvars | Async-safe structured logging | ✓ Good — clean correlated logs |
| FastAPI + HTMX + Tailwind CDN | Minimal dashboard without frontend build complexity | ✓ Good — zero build step, real-time via WebSocket |
| RuntimeConfig overlay | Dashboard can modify settings without restart | ✓ Good — applied at cycle start |
| Signal-based emergency stop | SIGUSR1 triggers immediate position close | ✓ Good — works from CLI and dashboard |

---
*Last updated: 2026-02-11 after v1.0 milestone*
