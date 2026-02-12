---
phase: 04-historical-data-foundation
plan: 01
subsystem: database, exchange
tags: [sqlite, aiosqlite, async, dataclass, decimal, wal-mode]

# Dependency graph
requires:
  - phase: 01-core-trading-engine
    provides: "ExchangeClient ABC, BybitClient, AppSettings, FundingRateData model"
provides:
  - "HistoricalFundingRate and OHLCVCandle dataclasses for historical data"
  - "HistoricalDatabase async SQLite manager with 5-table schema"
  - "select_top_pairs function for USDT perpetual pair selection by volume"
  - "HistoricalDataSettings configuration with HISTORICAL_ env prefix"
  - "fetch_funding_rate_history and fetch_ohlcv on ExchangeClient/BybitClient"
affects: [04-02-PLAN, 04-03-PLAN, 05-signal-analysis, 06-backtest-engine]

# Tech tracking
tech-stack:
  added: [aiosqlite]
  patterns: [async-context-manager-database, text-stored-decimals, wal-journal-mode]

key-files:
  created:
    - src/bot/data/__init__.py
    - src/bot/data/models.py
    - src/bot/data/database.py
    - src/bot/data/pair_selector.py
  modified:
    - src/bot/config.py
    - src/bot/exchange/client.py
    - src/bot/exchange/bybit_client.py
    - pyproject.toml

key-decisions:
  - "Decimal values stored as TEXT in SQLite to preserve precision (project convention)"
  - "WAL journal mode + NORMAL synchronous for concurrent read/write performance"
  - "Schema version table for future migration support"
  - "No pagination in exchange client methods -- callers handle iteration"

patterns-established:
  - "Async context manager pattern for database lifecycle (HistoricalDatabase.__aenter__/__aexit__)"
  - "Exchange client methods as thin single-call wrappers, pagination handled by higher-level fetchers"

# Metrics
duration: 3min
completed: 2026-02-12
---

# Phase 4 Plan 1: Data Foundation Summary

**Async SQLite data layer with 5-table schema, Decimal-precision models, USDT pair selector, and ccxt historical data fetch methods on ExchangeClient**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-12T11:39:48Z
- **Completed:** 2026-02-12T11:42:57Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Created `src/bot/data/` package with HistoricalFundingRate and OHLCVCandle dataclasses using Decimal fields
- Built HistoricalDatabase async SQLite manager creating 5 tables (schema_version, funding_rate_history, ohlcv_candles, fetch_state, tracked_pairs) with WAL mode and composite indexes
- Added select_top_pairs function filtering USDT perpetuals by 24h volume
- Extended ExchangeClient ABC and BybitClient with fetch_funding_rate_history and fetch_ohlcv methods
- Added HistoricalDataSettings to AppSettings with 9 configurable fields via HISTORICAL_ env prefix

## Task Commits

Each task was committed atomically:

1. **Task 1: Data models, database manager, config, and pair selector** - `ce60da7` (feat)
2. **Task 2: Exchange client historical data methods** - `90fb6ac` (feat)

## Files Created/Modified
- `src/bot/data/__init__.py` - Package exports for data module public API
- `src/bot/data/models.py` - HistoricalFundingRate and OHLCVCandle dataclasses with Decimal fields
- `src/bot/data/database.py` - HistoricalDatabase async SQLite connection manager with schema creation
- `src/bot/data/pair_selector.py` - select_top_pairs function for USDT perpetual selection by volume
- `src/bot/config.py` - Added HistoricalDataSettings class and wired into AppSettings
- `src/bot/exchange/client.py` - Added fetch_funding_rate_history and fetch_ohlcv abstract methods
- `src/bot/exchange/bybit_client.py` - Implemented both historical data fetch methods via ccxt
- `pyproject.toml` - Added aiosqlite>=0.22 dependency

## Decisions Made
- Decimal values stored as TEXT in SQLite to preserve precision (consistent with project convention of never using float for monetary values)
- WAL journal mode with NORMAL synchronous for better concurrent read/write performance
- Schema version table included from the start for future migration support
- Exchange client fetch methods are thin single-call wrappers -- pagination is deliberately excluded and will be handled by the HistoricalDataFetcher in plan 02

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Data models ready for HistoricalDataStore (plan 02) to use for insert/query operations
- Database schema ready for data persistence
- Exchange client methods ready for HistoricalDataFetcher (plan 02) to call with pagination
- HistoricalDataSettings configurable via environment variables
- All 206 existing tests pass with no regressions

## Self-Check: PASSED

All 8 files verified present. Both commit hashes (ce60da7, 90fb6ac) found in git log.

---
*Phase: 04-historical-data-foundation*
*Completed: 2026-02-12*
