# Roadmap: Funding Rate Arbitrage Bot

## Overview

This roadmap delivers a fully automated funding rate arbitrage bot from foundation to production-ready system. Phase 1 establishes core trading logic with paper trading validation, Phase 2 adds multi-pair intelligence and comprehensive risk controls, and Phase 3 delivers a full-featured dashboard for monitoring and control. The bot progresses from single-pair paper trading to multi-pair real-money operation with complete observability.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Core Trading Engine** - Paper trading with delta-neutral execution
- [x] **Phase 2: Multi-Pair Intelligence** - Real money mode with risk controls
- [ ] **Phase 3: Dashboard & Analytics** - Full-featured monitoring and control

## Phase Details

### Phase 1: Core Trading Engine
**Goal**: Bot can execute delta-neutral positions in paper trading mode and validate core arbitrage logic without risking capital.
**Depends on**: Nothing (first phase)
**Requirements**: MKTD-01, EXEC-01, EXEC-03, EXEC-04, PAPR-01, PAPR-02, PAPR-03, RISK-04
**Success Criteria** (what must be TRUE):
  1. Bot connects to Bybit API and displays real-time funding rates for perpetual pairs
  2. Bot opens simultaneous spot buy + perp short positions in paper mode with correct position sizing
  3. Bot tracks simulated P&L including fees and funding payments across paper trading sessions
  4. Bot validates delta neutrality continuously (spot quantity matches perp quantity within tolerance)
  5. Paper trading execution uses identical code path as real trading (swappable executor pattern)
**Plans**: 5 plans

Plans:
- [x] 01-01-PLAN.md -- Foundation: project scaffold, config, models, logging
- [x] 01-02-PLAN.md -- Exchange client (Bybit via ccxt) and funding rate monitor
- [x] 01-03-PLAN.md -- Fee calculator and position sizing (TDD)
- [x] 01-04-PLAN.md -- Executor pattern, paper executor, position manager, delta validator
- [x] 01-05-PLAN.md -- P&L tracker and orchestrator integration

### Phase 2: Multi-Pair Intelligence
**Goal**: Bot autonomously scans all pairs, ranks opportunities, executes profitable trades, and enforces comprehensive risk limits.
**Depends on**: Phase 1
**Requirements**: MKTD-02, MKTD-03, EXEC-02, RISK-01, RISK-02, RISK-03, RISK-05
**Success Criteria** (what must be TRUE):
  1. Bot scans all Bybit perpetual pairs and ranks by net yield after fees
  2. Bot only enters positions when funding rate exceeds configured minimum threshold
  3. Bot automatically closes positions when funding rate drops below exit threshold
  4. Bot enforces maximum position size per pair and maximum number of simultaneous positions
  5. Bot monitors margin ratio and alerts when below configured thresholds
  6. User can trigger emergency stop that immediately closes all open positions
**Plans**: 4 plans

Plans:
- [x] 02-01-PLAN.md -- Foundation: RiskSettings, OpportunityScore model, exchange client extensions
- [x] 02-02-PLAN.md -- OpportunityRanker: net yield scoring and ranking (TDD)
- [x] 02-03-PLAN.md -- RiskManager expansion and EmergencyController
- [x] 02-04-PLAN.md -- Orchestrator autonomous cycle and main.py wiring

### Phase 3: Dashboard & Analytics
**Goal**: User has complete visibility and control over bot operations through a real-time web dashboard.
**Depends on**: Phase 2
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06, DASH-07
**Success Criteria** (what must be TRUE):
  1. User can view all open positions with pair, entry price, size, unrealized P&L, and funding collected
  2. User can see funding rate overview across all Bybit perpetual pairs
  3. User can start/stop the bot and see current status and error alerts
  4. User can configure strategy parameters (funding thresholds, risk limits, pair filters) via the dashboard
  5. User can view trade history and performance analytics (Sharpe ratio, max drawdown, win rate)
**Plans**: TBD

Plans:
- [ ] TBD during plan-phase

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Core Trading Engine | 5/5 | ✓ Complete | 2026-02-11 |
| 2. Multi-Pair Intelligence | 4/4 | ✓ Complete | 2026-02-11 |
| 3. Dashboard & Analytics | 0/TBD | Not started | - |
