---
phase: 01-core-trading-engine
plan: 02
subsystem: exchange
tags: [ccxt, bybit, async, funding-rate, websocket, rest-polling, decimal]

# Dependency graph
requires:
  - phase: 01-01
    provides: "Installable package, ExchangeSettings config, FundingRateData model, structlog logging"
provides:
  - "ExchangeClient ABC defining exchange interface contract"
  - "BybitClient wrapping ccxt async with demo trading URL override"
  - "InstrumentInfo dataclass with lot size, tick size, min notional constraints"
  - "round_to_step utility for position sizing quantity rounding"
  - "FundingMonitor with REST polling, Decimal parsing, sorted/filtered retrieval"
  - "TickerService shared price cache with async-safe staleness detection"
affects: [01-03, 01-04, 01-05, position-sizing, paper-executor, orchestrator]

# Tech tracking
tech-stack:
  added: []
  patterns: [abc-interface-concrete-impl, async-lock-price-cache, rest-polling-with-retry, ccxt-async-wrapper]

key-files:
  created:
    - src/bot/exchange/types.py
    - src/bot/exchange/client.py
    - src/bot/exchange/bybit_client.py
    - src/bot/market_data/funding_monitor.py
    - src/bot/market_data/ticker_service.py
    - tests/test_exchange/__init__.py
    - tests/test_exchange/test_bybit_client.py
    - tests/test_market_data/__init__.py
    - tests/test_market_data/test_funding_monitor.py
  modified:
    - src/bot/exchange/__init__.py
    - src/bot/market_data/__init__.py

key-decisions:
  - "REST polling (30s) for funding rates instead of WebSocket -- rates change every 8h, simplifies Phase 1"
  - "TickerService as shared price cache decouples FundingMonitor from PaperExecutor consumers"
  - "InstrumentInfo not frozen -- allows mutable usage patterns downstream"

patterns-established:
  - "ABC interface + concrete implementation: ExchangeClient (ABC) -> BybitClient (concrete)"
  - "Shared async price cache: TickerService with asyncio.Lock for concurrent reads/writes"
  - "REST polling loop: try/except with structlog warning, sleep, retry pattern"
  - "Decimal everywhere: all funding rates, prices, quantities parsed as Decimal from string"

# Metrics
duration: 4min
completed: 2026-02-11
---

# Phase 1 Plan 02: Exchange Client and Funding Monitor Summary

**Bybit exchange client via ccxt async with REST-polled funding rate monitor, shared price cache, and InstrumentInfo position sizing constraints**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-11T20:00:00Z
- **Completed:** 2026-02-11T20:04:48Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- ExchangeClient ABC defining 10-method interface contract for all exchange operations (connect, close, fetch_ticker, fetch_tickers, fetch_perpetual_symbols, get_instrument_info, create_order, cancel_order, fetch_balance, load_markets)
- BybitClient wrapping ccxt async with demo trading URL override, market caching, instrument info extraction as Decimal values, and proper async cleanup
- FundingMonitor that REST-polls all linear perpetual tickers, parses funding rates as Decimal, caches results, and provides sorted/filtered retrieval (get_all_funding_rates, get_profitable_pairs)
- TickerService shared price cache with asyncio.Lock for thread-safe reads/writes and staleness detection (is_stale, get_price_age)
- 47 tests total across both test suites, all using mocked exchange data

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement exchange client interface and Bybit implementation** - `aa78520` (feat)
2. **Task 2: Implement funding rate monitor and shared ticker service** - `9bd54f1` (feat)

## Files Created/Modified
- `src/bot/exchange/types.py` - InstrumentInfo dataclass and round_to_step utility for position sizing
- `src/bot/exchange/client.py` - ExchangeClient ABC defining the exchange interface contract
- `src/bot/exchange/bybit_client.py` - Concrete Bybit implementation via ccxt async with demo trading support
- `src/bot/exchange/__init__.py` - Updated exports (BybitClient, ExchangeClient, InstrumentInfo, round_to_step)
- `src/bot/market_data/funding_monitor.py` - FundingMonitor with REST polling, funding rate caching, profitable pair filtering
- `src/bot/market_data/ticker_service.py` - TickerService shared price cache with async Lock and staleness detection
- `src/bot/market_data/__init__.py` - Updated exports (FundingMonitor, TickerService)
- `tests/test_exchange/__init__.py` - Test package init
- `tests/test_exchange/test_bybit_client.py` - 23 tests: round_to_step, InstrumentInfo, symbol filtering, instrument extraction, delegation
- `tests/test_market_data/__init__.py` - Test package init
- `tests/test_market_data/test_funding_monitor.py` - 24 tests: TickerService cache/staleness, funding parsing/sorting/filtering, lifecycle

## Decisions Made
- **REST polling over WebSocket for Phase 1:** Funding rates change every 8 hours, so 30-second REST polling is sufficient. This avoids ccxt Pro WebSocket complexity and the Open Question #1 about delta message reliability. WebSocket can be added in Phase 2 for lower latency.
- **TickerService as shared decoupled cache:** Solves Open Question #3 from research. FundingMonitor writes prices; PaperExecutor (Plan 04) reads them. No tight coupling between consumers.
- **InstrumentInfo is a plain dataclass (not frozen):** The linter removed frozen=True, allowing downstream flexibility for position sizing code.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ExchangeClient interface ready for position sizing code (Plan 03) to call get_instrument_info
- FundingMonitor ready for orchestrator (Plan 05) to call get_profitable_pairs for trade signal
- TickerService ready for PaperExecutor (Plan 04) to read cached prices for simulated fills
- All monetary values use Decimal consistently (enforced by type annotations and tests)

## Self-Check: PASSED

- All 11 created/modified files verified present on disk
- Commit aa78520 verified in git log (Task 1)
- Commit 9bd54f1 verified in git log (Task 2)
- All 47 tests pass (23 exchange + 24 market data)

---
*Phase: 01-core-trading-engine*
*Completed: 2026-02-11*
