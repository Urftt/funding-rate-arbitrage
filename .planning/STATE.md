# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-11)

**Core value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.
**Current focus:** Phase 3 in progress — Dashboard & Analytics

## Current Position

Phase: 3 of 3 (Dashboard & Analytics)
Plan: 2 of 5
Status: Executing
Last activity: 2026-02-11 — Completed 03-02-PLAN.md (Data Layer Extensions)

Progress: [████------] 40%

## Performance Metrics

**Velocity:**
- Total plans completed: 11
- Average duration: 4 min
- Total execution time: 0.73 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-core-trading-engine | 5/5 | 23 min | 5 min |
| 02-multi-pair-intelligence | 4/4 | 16 min | 4 min |
| 03-dashboard-analytics | 2/5 | 5 min | 3 min |

**Recent Trend:**
- Last 5 plans: 02-02 (3 min), 02-03 (4 min), 02-04 (6 min), 03-01 (2 min), 03-02 (3 min)
- Trend: Consistent ~2-6 min/plan

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
- [02-04] Emergency controller injected post-construction via set_emergency_controller to resolve circular dependency
- [02-04] asyncio.Lock for cycle lock (strict mutual exclusion, no overlapping autonomous cycles)
- [02-04] Graceful stop closes all positions before setting _running=False
- [03-01] Added jinja2>=3.1 as explicit dependency -- starlette requires it for Jinja2Templates but does not auto-install
- [03-01] App factory pattern with optional lifespan for main.py injection in Plan 05
- [03-01] Global DashboardHub instance stored on app.state for route handler access
- [03-01] format_decimal Jinja2 filter for clean Decimal rendering
- [03-02] RuntimeConfig is a dataclass (not BaseSettings) -- mutable runtime state for dashboard overrides
- [03-02] restart() uses asyncio.create_task so dashboard route handler returns immediately
- [03-02] stop() always closes positions (safe default); restart() re-enters the loop

### Pending Todos

None yet.

### Blockers/Concerns

**Phase 2 readiness:**
- Bybit fee structures need verification (current maker/taker percentages, spot vs perp differences)
- Margin calculation methods require understanding (how maintenance margin changes during volatility)

## Session Continuity

Last session: 2026-02-11 - Plan 03-02 execution
Stopped at: Completed 03-02-PLAN.md (Data Layer Extensions)
Resume file: None
