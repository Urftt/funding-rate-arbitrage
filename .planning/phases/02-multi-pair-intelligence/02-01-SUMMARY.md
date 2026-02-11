---
phase: 02-multi-pair-intelligence
plan: 01
subsystem: config, models, exchange
tags: [pydantic-settings, dataclass, decimal, abc, ccxt, margin, risk]

# Dependency graph
requires:
  - phase: 01-core-trading-engine
    provides: "AppSettings, models.py, exceptions.py, ExchangeClient ABC, BybitClient, PaperExecutor"
provides:
  - "RiskSettings with 8 configurable fields (RISK_ env prefix)"
  - "OpportunityScore dataclass for pair ranking"
  - "RiskLimitExceeded and EmergencyStopTriggered exceptions"
  - "ExchangeClient.fetch_wallet_balance_raw for margin monitoring"
  - "ExchangeClient.get_markets for cached market data access"
  - "simulate_paper_margin helper for paper mode risk management"
affects: [02-02-opportunity-ranker, 02-03-risk-manager, 02-04-orchestrator-v2]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RiskSettings as separate BaseSettings with RISK_ prefix"
    - "simulate_paper_margin as module-level helper mirroring exchange API shape"
    - "Sync get_markets on async ABC (loaded at connect time)"

key-files:
  created: []
  modified:
    - src/bot/config.py
    - src/bot/models.py
    - src/bot/exceptions.py
    - src/bot/exchange/client.py
    - src/bot/exchange/bybit_client.py
    - src/bot/execution/paper_executor.py
    - .env.example

key-decisions:
  - "paper_virtual_equity added to RiskSettings rather than separate config"
  - "get_markets is synchronous on ExchangeClient ABC since markets loaded at connect()"
  - "simulate_paper_margin is module-level function, not on PaperExecutor class"

patterns-established:
  - "Risk config via RISK_ env prefix with Decimal defaults"
  - "Paper mode helpers mimic live exchange API response shapes"

# Metrics
duration: 3min
completed: 2026-02-11
---

# Phase 2 Plan 1: Foundation Types and Exchange Extensions Summary

**RiskSettings config, OpportunityScore model, risk exceptions, and exchange client margin/market methods for Phase 2 multi-pair intelligence**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-11T20:52:18Z
- **Completed:** 2026-02-11T20:54:56Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- RiskSettings with 8 configurable fields loadable from RISK_ environment variables, composed into AppSettings.risk
- OpportunityScore dataclass with net yield and annualized yield calculations for pair ranking
- ExchangeClient ABC extended with fetch_wallet_balance_raw (margin monitoring) and get_markets (cached market access)
- BybitClient implements both new methods; simulate_paper_margin helper enables paper mode risk evaluation
- All 135 existing Phase 1 tests pass without modification

## Task Commits

Each task was committed atomically:

1. **Task 1: Add RiskSettings, OpportunityScore, and new exceptions** - `8f82160` (feat)
2. **Task 2: Extend ExchangeClient ABC and BybitClient with margin and market access** - `1000953` (feat)

## Files Created/Modified
- `src/bot/config.py` - Added RiskSettings class and scan_interval to TradingSettings; composed risk into AppSettings
- `src/bot/models.py` - Added OpportunityScore dataclass for funding rate opportunity ranking
- `src/bot/exceptions.py` - Added RiskLimitExceeded and EmergencyStopTriggered exceptions
- `src/bot/exchange/client.py` - Added fetch_wallet_balance_raw and get_markets abstract methods
- `src/bot/exchange/bybit_client.py` - Implemented fetch_wallet_balance_raw (UNIFIED account) and get_markets
- `src/bot/execution/paper_executor.py` - Added simulate_paper_margin module-level helper function
- `.env.example` - Documented all RISK_ variables and TRADING_SCAN_INTERVAL

## Decisions Made
- paper_virtual_equity field placed on RiskSettings (not separate config) since it's risk-related configuration
- get_markets is synchronous on the ABC since markets are always loaded at connect() time, avoiding unnecessary async overhead
- simulate_paper_margin is a module-level function (not on PaperExecutor) per plan specification, keeping PaperExecutor focused on order execution

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. All new RISK_ variables have sensible defaults.

## Next Phase Readiness
- All shared types, config, and exchange methods ready for Phase 2 plans 02-04
- OpportunityRanker (02-02) can use OpportunityScore and get_markets
- RiskManager (02-03) can use RiskSettings, fetch_wallet_balance_raw, simulate_paper_margin, and risk exceptions
- OrchestratorV2 (02-04) can use scan_interval and all above

## Self-Check: PASSED

- All 7 modified files verified present on disk
- Commit 8f82160 (Task 1) verified in git log
- Commit 1000953 (Task 2) verified in git log
- All 135 existing tests pass without modification

---
*Phase: 02-multi-pair-intelligence*
*Completed: 2026-02-11*
