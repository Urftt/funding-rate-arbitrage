# Phase 4: Historical Data Foundation - Context

**Gathered:** 2026-02-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Fetch, store, and persist historical funding rate and OHLCV price data from Bybit. Provides the data layer that all v1.1 intelligence features (signal analysis, backtesting, dynamic sizing) build on. Signal computation, backtesting, and position sizing are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Data scope & granularity
- USDT linear perpetuals only (consistent with v1.0 bot)
- Top 20 pairs by volume — dynamically re-evaluated weekly
- When a new pair enters the top 20, fetch its full history (blocking)
- Default lookback: 1 year (configurable — user can set shorter or longer)
- OHLCV interval: 1-hour candles
- Data persists in SQLite — fetched once, never re-fetched (only gaps filled)

### Fetch timing & behavior
- Bulk historical fetch happens on bot startup
- Bot waits for fetch completion before starting trading (signals need full data)
- Retry with exponential backoff on API errors/downtime
- Resume per-pair on restart — each pair tracks its last fetched timestamp
- API rate limits respected automatically (no 429 errors)

### Data freshness & updates
- Incremental updates appended on each scan cycle (not a separate background job)
- Auto-fill gaps on startup if bot was offline (detect missing intervals, fetch before trading)
- Keep all data forever — no pruning (funding rate + candle data is small)
- Basic validation on insert: check for duplicates and missing intervals

### Progress visibility
- Log per-pair progress during initial bulk fetch (e.g., "Fetching BTC/USDT: 45/365 days")
- Dashboard data status widget showing: number of pairs tracked, total records, date range covered, last sync time
- Dashboard widget shows live fetch progress during initial loading (e.g., "12/20 pairs — Fetching ETH/USDT")
- Data quality issues surfaced in both logs (warning level) and dashboard widget alerts
- Pair re-evaluation logged weekly

### Claude's Discretion
- Incremental scan-cycle update logging strategy (signal-to-noise balance)
- SQLite schema design and migration approach
- Exact retry backoff parameters
- Rate limit implementation details
- Dashboard widget layout and styling

</decisions>

<specifics>
## Specific Ideas

- User noted Bybit has mostly USDC pairs but few USDT pairs — staying USDT-only for consistency with v1.0
- 90-day lookback felt thin for Bitcoin's 4-year cycles — 1 year default chosen as a balance
- "If we keep our own SQL database then we only have to load the prices once" — persistence is key, avoid redundant fetching

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-historical-data-foundation*
*Context gathered: 2026-02-12*
