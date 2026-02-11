# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-11)

**Core value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.
**Current focus:** Phase 2 — Multi-Pair Intelligence risk engine and orchestrator V2

## Current Position

Phase: 2 of 3 (Multi-Pair Intelligence)
Plan: 3 of 4
Status: Plan Complete
Last activity: 2026-02-11 — Completed 02-03-PLAN.md (Risk Manager & Emergency Controller)

Progress: [███████░░░] 75%

## Performance Metrics

**Velocity:**
- Total plans completed: 8
- Average duration: 4 min
- Total execution time: 0.55 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-core-trading-engine | 5/5 | 23 min | 5 min |
| 02-multi-pair-intelligence | 3/4 | 10 min | 3 min |

**Recent Trend:**
- Last 5 plans: 01-04 (5 min), 01-05 (5 min), 02-01 (3 min), 02-02 (3 min), 02-03 (4 min)
- Trend: Consistent ~3-5 min/plan

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
- [02-01] paper_virtual_equity added to RiskSettings rather than separate config class
- [02-01] get_markets is synchronous on ExchangeClient ABC (markets loaded at connect time)
- [02-01] simulate_paper_margin is module-level function, not on PaperExecutor class
- [02-02] Net yield formula uses Decimal arithmetic exclusively -- no float conversions
- [02-02] Spot symbol derived from markets dict base/quote fields, not string manipulation
- [02-02] Inactive spot markets treated same as missing -- pair excluded from rankings
- [02-03] RiskManager accepts optional paper_margin_fn callable instead of direct PaperExecutor dependency
- [02-03] EmergencyController records P&L via pnl_tracker.record_close during emergency close
- [02-03] Linear backoff (not exponential) for emergency close retries -- simplicity in emergency path

### Pending Todos

None yet.

### Blockers/Concerns

**Phase 2 readiness:**
- Bybit fee structures need verification (current maker/taker percentages, spot vs perp differences)
- Margin calculation methods require understanding (how maintenance margin changes during volatility)

## Session Continuity

Last session: 2026-02-11 - Plan 02-03 execution
Stopped at: Completed 02-03-PLAN.md (Risk Manager & Emergency Controller)
Resume file: None
