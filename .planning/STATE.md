# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-12)

**Core value:** The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.
**Current focus:** v1.1 Strategy Intelligence -- Phase 5 complete, ready for Phase 6

## Current Position

Milestone: v1.1 Strategy Intelligence
Phase: 5 of 7 (Signal Analysis Integration) -- COMPLETE
Plan: 3 of 3 in current phase
Status: Phase Complete
Last activity: 2026-02-12 -- Completed 05-03-PLAN.md (SignalEngine + orchestrator integration)

Progress: [████████████████░░░░] 79% (v1.0 complete, v1.1 phase 5: 3/3 plans)

## Performance Metrics

**Velocity (v1.0):**
- Total plans completed: 14
- Total execution time: ~1 day
- Average: ~1.7 hours/plan

**By Phase (v1.0):**

| Phase | Plans | Status |
|-------|-------|--------|
| 1. Core Trading Engine | 5 | Complete |
| 2. Multi-Pair Intelligence | 4 | Complete |
| 3. Dashboard & Analytics | 5 | Complete |

**By Phase (v1.1):**

| Phase | Plans | Duration | Status |
|-------|-------|----------|--------|
| 4. Historical Data Foundation | 3/3 | 19min | Complete |
| 5. Signal Analysis Integration | 3/3 | 11min | Complete |

## Accumulated Context

### Decisions

All decisions logged in PROJECT.md Key Decisions table.

Recent decisions affecting current work:
- v1.1 scope: 18 requirements across 4 categories (DATA, SGNL, BKTS, SIZE)
- Build order: data foundation -> signal analysis -> backtest engine -> dynamic sizing
- All v1.1 components are optional (feature flags, `| None = None` injection)
- v1.0 baseline preserved as fallback via `strategy_mode: simple`
- Decimal values stored as TEXT in SQLite to preserve precision
- WAL journal mode + NORMAL synchronous for database performance
- Exchange client fetch methods are thin wrappers -- pagination handled by higher-level fetchers
- HistoricalDataStore wraps database with typed methods; all Decimal stored as TEXT, restored on read
- Backward pagination uses endTime parameter (never startTime alone) per Bybit API requirement
- Bybit kline response reversed before processing (newest-first pitfall)
- Incremental updates: DEBUG per-pair, INFO summary (signal-to-noise balance)
- Orchestrator waits up to 30s for funding monitor first poll before historical fetch
- Dashboard mode delegates SIGINT/SIGTERM to uvicorn for clean shutdown
- Data status widget uses 4-state Jinja2 conditional (disabled, starting, fetching, normal)
- Index prices cached in separate dict on FundingMonitor (not modifying FundingRateData v1.0 type)
- Volume trend is a hard filter: volume_ok=False rejects pair regardless of composite score
- Graceful degradation: insufficient candle data returns True (don't reject for lack of data)
- Spot symbol derivation duplicated in SignalEngine (not imported from ranker) for module independence
- Composite score uses rate as proxy for net_yield; actual fee check remains in PositionManager
- Composite mode with signal_engine=None falls back to simple path (defensive)

### Pending Todos

None.

### Blockers/Concerns

- Bybit fee structures need verification (carried from v1.0)
- Look-ahead bias risk in backtesting (predicted vs settled funding rates differ)
- Funding rate trend indicators may produce false signals (mean-reverting series)

## Session Continuity

Last session: 2026-02-12
Stopped at: Completed 05-03-PLAN.md -- SignalEngine + orchestrator integration (Phase 5 complete)
Resume file: None
Next step: Plan Phase 06 (Backtest Engine)
