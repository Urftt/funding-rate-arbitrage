# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-11)

**Core value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.
**Current focus:** Phase 1 - Core Trading Engine

## Current Position

Phase: 1 of 3 (Core Trading Engine)
Plan: 5 of 5
Status: Phase Complete
Last activity: 2026-02-11 — Completed 01-05-PLAN.md (P&L Tracking & Orchestrator Integration)

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 5
- Average duration: 5 min
- Total execution time: 0.38 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-core-trading-engine | 5/5 | 23 min | 5 min |

**Recent Trend:**
- Last 5 plans: 01-01 (4 min), 01-02 (4 min), 01-03 (5 min), 01-04 (5 min), 01-05 (5 min)
- Trend: Consistent ~4-5 min/plan

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [01-01] Used uv for Python 3.12 venv creation (system Python was 3.9.6)
- [01-01] All monetary fields use Decimal -- enforced via type annotations on all dataclasses
- [01-01] structlog with contextvars for async-safe logging (not threadlocal)
- [01-01] Separate BaseSettings subclasses with env_prefix per domain (BYBIT_, TRADING_, FEES_)
- [01-02] REST polling (30s) for funding rates instead of WebSocket -- rates change every 8h, simplifies Phase 1
- [01-02] TickerService as shared price cache decouples FundingMonitor from PaperExecutor consumers
- [01-02] InstrumentInfo not frozen -- allows mutable usage patterns downstream
- [01-03] FeeCalculator.is_profitable uses entry_price for exit fee estimate (conservative)
- [01-03] PositionSizer uses max(spot_step, perp_step) for cross-leg quantity alignment
- [01-03] Funding payment sign convention: positive = income, negative = expense (Bybit: positive rate = longs pay shorts)
- [01-04] Custom exceptions in dedicated src/bot/exceptions.py to avoid circular imports between executor and position modules
- [01-04] PaperExecutor uses 0.05% simulated slippage (5 bps) and 60s staleness threshold for realistic fills
- [01-04] PositionManager acquires asyncio.Lock for both open and close to prevent concurrent position modifications
- [01-05] PnLTracker.get_total_pnl takes unrealized_pnl as parameter (synchronous) rather than async-fetching prices
- [01-05] Orchestrator Phase 1 is monitor-only: logs opportunities but does NOT auto-open positions
- [01-05] Funding settlement uses time.time() elapsed check for paper trading simplicity

### Pending Todos

None yet.

### Blockers/Concerns

**Phase 2 readiness:**
- Bybit fee structures need verification (current maker/taker percentages, spot vs perp differences)
- Margin calculation methods require understanding (how maintenance margin changes during volatility)

## Session Continuity

Last session: 2026-02-11 - Plan 01-05 execution
Stopped at: Completed 01-05-PLAN.md (P&L Tracking & Orchestrator Integration) -- Phase 1 COMPLETE
Resume file: None
