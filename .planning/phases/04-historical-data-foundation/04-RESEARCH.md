# Phase 4: Historical Data Foundation - Research

**Researched:** 2026-02-12
**Domain:** Bybit historical data fetching, SQLite persistence, async data pipelines
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- USDT linear perpetuals only (consistent with v1.0 bot)
- Top 20 pairs by volume -- dynamically re-evaluated weekly
- When a new pair enters the top 20, fetch its full history (blocking)
- Default lookback: 1 year (configurable -- user can set shorter or longer)
- OHLCV interval: 1-hour candles
- Data persists in SQLite -- fetched once, never re-fetched (only gaps filled)
- Bulk historical fetch happens on bot startup
- Bot waits for fetch completion before starting trading (signals need full data)
- Retry with exponential backoff on API errors/downtime
- Resume per-pair on restart -- each pair tracks its last fetched timestamp
- API rate limits respected automatically (no 429 errors)
- Incremental updates appended on each scan cycle (not a separate background job)
- Auto-fill gaps on startup if bot was offline (detect missing intervals, fetch before trading)
- Keep all data forever -- no pruning (funding rate + candle data is small)
- Basic validation on insert: check for duplicates and missing intervals
- Log per-pair progress during initial bulk fetch (e.g., "Fetching BTC/USDT: 45/365 days")
- Dashboard data status widget showing: number of pairs tracked, total records, date range covered, last sync time
- Dashboard widget shows live fetch progress during initial loading (e.g., "12/20 pairs -- Fetching ETH/USDT")
- Data quality issues surfaced in both logs (warning level) and dashboard widget alerts
- Pair re-evaluation logged weekly

### Claude's Discretion
- Incremental scan-cycle update logging strategy (signal-to-noise balance)
- SQLite schema design and migration approach
- Exact retry backoff parameters
- Rate limit implementation details
- Dashboard widget layout and styling

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

## Summary

This phase builds the persistent historical data layer for the bot. It must fetch, store, and maintain historical funding rate and OHLCV (1-hour candle) data from Bybit for the top 20 USDT linear perpetual pairs by volume. The data is stored in SQLite via `aiosqlite`, fetched once on first run, and incrementally updated during each scan cycle. The bot blocks on startup until all historical data is loaded, with per-pair resume capability to survive interruptions.

The project already uses ccxt v4.5.37 with `ccxt.async_support.bybit` and has `enableRateLimit: True` configured. The existing `BybitClient` wraps ccxt and provides async methods. The key challenge is implementing reliable paginated backward-fetching: the Bybit funding rate history endpoint returns max 200 records per call, and the kline endpoint returns max 1000 records per call. For 1 year of 1-hour candles, that is ~8,760 candles requiring ~9 paginated calls per pair; for 1 year of funding rates at 8h intervals, that is ~1,095 records requiring ~6 calls per pair. With 20 pairs, this is roughly 300 API calls on initial load.

A critical discovery is that Bybit introduced dynamic funding rate settlement frequencies in late 2025 -- pairs can settle at 8h, 4h, 2h, or even 1h intervals, and these can change dynamically based on market conditions. The `fundingIntervalHour` field from the tickers API already captured by the existing `FundingMonitor` reflects each pair's current interval. The historical data schema must store the actual interval per record since it may vary over time for the same pair.

**Primary recommendation:** Use `aiosqlite` for async SQLite access with WAL mode, implement manual timestamp-based pagination for both ccxt `fetch_funding_rate_history` and `fetch_ohlcv`, and add two new abstract methods to `ExchangeClient` for historical data access. Store data in two tables (`funding_rate_history` and `ohlcv_candles`) with composite primary keys on `(symbol, timestamp)` for natural deduplication via `INSERT OR IGNORE`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiosqlite | 0.22.1 | Async SQLite access | Standard async bridge for sqlite3; non-blocking I/O on asyncio event loop; context manager support |
| ccxt | >=4.5.0 (currently 4.5.37) | Exchange API (already in project) | Already used; provides `fetch_funding_rate_history` and `fetch_ohlcv` with unified format |
| sqlite3 | stdlib | SQLite engine | No extra dependency; ships with Python 3.12; WAL mode for concurrent read/write |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiolimiter | >=1.2 (already in project) | Rate limiting | Already used in project; useful for additional rate limit safety on top of ccxt's built-in limiter |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| aiosqlite | SQLAlchemy async + aiosqlite | Overkill for 2 tables; raw SQL is simpler for time-series data |
| aiosqlite | sqlite3 (sync) in executor | aiosqlite wraps this pattern already; cleaner API |
| Manual pagination | ccxt `paginate: True` param | ccxt's auto-paginate is experimental, has known bugs with Bybit; manual is more reliable |

**Installation:**
```bash
pip install aiosqlite>=0.22.0
```

Add to `pyproject.toml` dependencies:
```toml
"aiosqlite>=0.22",
```

## Architecture Patterns

### Recommended Project Structure
```
src/bot/
├── data/                        # NEW: Historical data module
│   ├── __init__.py
│   ├── models.py                # Data models for historical records
│   ├── database.py              # SQLite connection manager and schema
│   ├── store.py                 # HistoricalDataStore (read/write abstraction)
│   ├── fetcher.py               # HistoricalDataFetcher (API -> store pipeline)
│   └── pair_selector.py         # Top-20 pair selection by volume
├── exchange/
│   ├── client.py                # MODIFIED: Add fetch_funding_rate_history, fetch_ohlcv
│   └── bybit_client.py          # MODIFIED: Implement new abstract methods
├── dashboard/
│   ├── templates/partials/
│   │   └── data_status.html     # NEW: Data status widget template
│   ├── routes/api.py            # MODIFIED: Add /api/data-status endpoint
│   └── update_loop.py           # MODIFIED: Include data status in broadcasts
├── config.py                    # MODIFIED: Add HistoricalDataSettings
├── orchestrator.py              # MODIFIED: Integrate data fetch on startup
└── main.py                      # MODIFIED: Wire HistoricalDataStore + Fetcher
```

### Pattern 1: Timestamp-Based Backward Pagination
**What:** Fetch historical data by walking backward from `endTime` to `startTime` using the latest returned timestamp as the next `endTime`.
**When to use:** When fetching funding rate history or OHLCV candles from Bybit.
**Why:** Bybit's funding rate history endpoint returns data most-recent-first. Pass `endTime` to get records before that point. The kline endpoint also returns reverse-sorted data. Manual pagination avoids ccxt's experimental `paginate` feature which has known bugs.

**Example (funding rate history pagination):**
```python
async def fetch_funding_rates_paginated(
    self,
    exchange: ExchangeClient,
    symbol: str,
    since_ms: int,
    until_ms: int,
) -> list[dict]:
    """Fetch all funding rates between since_ms and until_ms via pagination."""
    all_records: list[dict] = []
    current_end = until_ms

    while current_end > since_ms:
        # ccxt fetch_funding_rate_history returns list of dicts:
        # [{"symbol", "fundingRate", "timestamp", "datetime", "info"}, ...]
        batch = await exchange.fetch_funding_rate_history(
            symbol=symbol,
            limit=200,
            params={"endTime": current_end},
        )

        if not batch:
            break

        # Filter to only records within our target range
        batch = [r for r in batch if r["timestamp"] >= since_ms]
        all_records.extend(batch)

        # Move backward: use the oldest timestamp in this batch
        oldest_ts = min(r["timestamp"] for r in batch)
        if oldest_ts >= current_end:
            break  # No progress, avoid infinite loop
        current_end = oldest_ts

    return all_records
```

### Pattern 2: Repository / Store Abstraction
**What:** A `HistoricalDataStore` class that owns the SQLite connection and provides typed read/write methods, keeping SQL isolated from business logic.
**When to use:** All database operations.

**Example:**
```python
class HistoricalDataStore:
    """Async SQLite store for historical funding rates and OHLCV candles."""

    def __init__(self, db_path: str = "data/historical.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._create_tables()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def get_last_funding_timestamp(self, symbol: str) -> int | None:
        """Get the most recent funding rate timestamp for resume capability."""
        cursor = await self._db.execute(
            "SELECT MAX(timestamp_ms) FROM funding_rate_history WHERE symbol = ?",
            (symbol,),
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None
```

### Pattern 3: Fetcher Orchestrates Store + Exchange
**What:** A `HistoricalDataFetcher` coordinates between the exchange API and the store, handling pagination, progress reporting, and gap detection.
**When to use:** On startup (bulk fetch) and on each scan cycle (incremental append).

```python
class HistoricalDataFetcher:
    """Fetches historical data from exchange and stores it."""

    def __init__(
        self,
        exchange: ExchangeClient,
        store: HistoricalDataStore,
        settings: HistoricalDataSettings,
    ) -> None:
        self._exchange = exchange
        self._store = store
        self._settings = settings

    async def ensure_data_ready(self, symbols: list[str]) -> None:
        """Fetch all missing historical data. Blocks until complete."""
        for i, symbol in enumerate(symbols, 1):
            logger.info(
                "fetching_historical_data",
                symbol=symbol,
                progress=f"{i}/{len(symbols)}",
            )
            await self._fetch_funding_history(symbol)
            await self._fetch_ohlcv_history(symbol)
```

### Pattern 4: Feature Flag Integration (v1.1 Convention)
**What:** All v1.1 components are optional via `| None = None` injection in the orchestrator.
**When to use:** The `HistoricalDataStore` and `HistoricalDataFetcher` should be optional parameters in the orchestrator, activated only when configured.

### Anti-Patterns to Avoid
- **Using ccxt `paginate: True` parameter:** Experimental, known bugs with Bybit. Use manual timestamp-based pagination instead.
- **Fetching all pairs, not just top 20:** Would waste API calls and storage for rarely-traded pairs.
- **Using a single table for funding rates and candles:** Different schemas, different query patterns. Keep separate.
- **Storing timestamps as strings:** Use INTEGER for Unix milliseconds. Enables efficient range queries and comparisons.
- **Blocking the event loop during fetch:** Use async throughout. The existing ccxt async_support is already non-blocking.
- **Re-fetching existing data:** Use `INSERT OR IGNORE` with composite primary key `(symbol, timestamp_ms)` to naturally deduplicate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async SQLite access | Thread pool executor wrapper | aiosqlite 0.22.1 | Already handles thread management, context managers, error propagation |
| API rate limiting | Custom sleep/counter | ccxt `enableRateLimit: True` (already configured) | ccxt throttles automatically; 20ms between calls for Bybit |
| Exponential backoff | Manual retry loop | `asyncio` sleep with doubling interval | Simple pattern, but don't over-engineer; 3-5 retries with 1s/2s/4s/8s/16s is sufficient |
| Exchange API abstraction | Direct HTTP calls | ccxt unified methods | Already used; `fetch_funding_rate_history` and `fetch_ohlcv` normalize Bybit's response format |
| Deduplication logic | Pre-check existence queries | `INSERT OR IGNORE` with UNIQUE constraint | Database handles it atomically; much faster than SELECT-then-INSERT |

**Key insight:** The ccxt library already handles most exchange API complexity (auth, rate limiting, response normalization). The main custom work is the pagination loop and the SQLite persistence layer.

## Common Pitfalls

### Pitfall 1: Bybit Funding Rate History Pagination Quirks
**What goes wrong:** Passing only `startTime` to the Bybit funding rate history endpoint returns an error. Passing `since` in ccxt maps to `startTime` internally, which may trigger this error or return unexpected results.
**Why it happens:** Bybit's API requires either `endTime` alone, both `startTime` and `endTime`, or neither -- but NOT `startTime` alone.
**How to avoid:** Always pass `endTime` via `params={"endTime": timestamp_ms}`. Walk backward from "now" to the target start date. Filter results client-side to exclude records before the desired start.
**Warning signs:** Empty results or API errors when using `since` parameter without `endTime`.

### Pitfall 2: Dynamic Funding Rate Intervals
**What goes wrong:** Assuming all pairs have 8-hour funding intervals. Since October 2025, Bybit uses dynamic settlement frequencies (8h, 4h, 2h, or even 1h) that change based on market conditions.
**Why it happens:** The `fundingIntervalHour` field varies per pair and can change over time.
**How to avoid:** Store the funding interval alongside each historical funding rate record. Do NOT assume a fixed interval. The `fundingIntervalHour` is already captured in the tickers response by `FundingMonitor`.
**Warning signs:** Gap detection reports "missing" records when a pair actually switched from 8h to 4h intervals.

### Pitfall 3: Bybit Kline Response is Reverse-Sorted
**What goes wrong:** Treating kline data as chronologically sorted causes incorrect time-range pagination.
**Why it happens:** Bybit's `/v5/market/kline` endpoint returns candles in reverse chronological order (newest first).
**How to avoid:** After fetching, reverse the batch before processing. When paginating, use the oldest timestamp as the next `end` parameter.
**Warning signs:** Duplicate records or skipped time ranges during pagination.

### Pitfall 4: OHLCV Limit is 1000, Funding Rate Limit is 200
**What goes wrong:** Using the same pagination limit for both endpoints, wasting API calls on OHLCV or hitting errors on funding rates.
**Why it happens:** Different Bybit endpoints have different max limits.
**How to avoid:** Use `limit=200` for funding rate history, `limit=1000` for kline data.
**Warning signs:** Truncated results or unnecessary API calls.

### Pitfall 5: ccxt Symbol Format vs Bybit Native Format
**What goes wrong:** Using Bybit native symbols (e.g., `BTCUSDT`) instead of ccxt unified symbols (e.g., `BTC/USDT:USDT`) or vice versa.
**Why it happens:** ccxt converts between formats, but when storing in the database you need consistency.
**How to avoid:** Always use ccxt unified symbol format (`BTC/USDT:USDT` for perpetuals) in the database and in all internal APIs. The ccxt methods handle the conversion to Bybit format automatically.
**Warning signs:** Duplicate records with different symbol formats, failed lookups.

### Pitfall 6: SQLite Concurrent Write Contention
**What goes wrong:** Multiple coroutines writing to SQLite simultaneously causes "database is locked" errors.
**Why it happens:** SQLite allows only one writer at a time, even in WAL mode.
**How to avoid:** Use a single `aiosqlite.Connection` instance shared across the application (aiosqlite internally serializes writes via its thread). Do NOT create multiple connections for writes. WAL mode enables concurrent reads during writes.
**Warning signs:** `OperationalError: database is locked` errors.

### Pitfall 7: Not Accounting for API Downtime Gaps
**What goes wrong:** Bot assumes data is continuous after restart, but API was down or pair was delisted/relisted, creating real gaps that are not errors.
**Why it happens:** Funding rate records only exist for settlement times. If a pair's settlement frequency changed, the expected interval changes too.
**How to avoid:** Gap detection should use the pair's `fundingIntervalHour` to determine expected intervals. Log gaps as warnings but do not treat them as fatal errors.
**Warning signs:** Infinite retry loops trying to fill gaps that are actually legitimate.

## Code Examples

Verified patterns from official sources:

### SQLite Schema Design
```sql
-- Source: SQLite best practices for time-series data
-- Uses INTEGER for timestamps (Unix ms) for efficient range queries
-- Composite primary key for natural deduplication

CREATE TABLE IF NOT EXISTS funding_rate_history (
    symbol          TEXT    NOT NULL,
    timestamp_ms    INTEGER NOT NULL,
    funding_rate    TEXT    NOT NULL,  -- Stored as TEXT to preserve Decimal precision
    interval_hours  INTEGER NOT NULL DEFAULT 8,
    PRIMARY KEY (symbol, timestamp_ms)
);

CREATE TABLE IF NOT EXISTS ohlcv_candles (
    symbol          TEXT    NOT NULL,
    timestamp_ms    INTEGER NOT NULL,
    open            TEXT    NOT NULL,
    high            TEXT    NOT NULL,
    low             TEXT    NOT NULL,
    close           TEXT    NOT NULL,
    volume          TEXT    NOT NULL,
    PRIMARY KEY (symbol, timestamp_ms)
);

-- Track per-pair fetch state for resume capability
CREATE TABLE IF NOT EXISTS fetch_state (
    symbol          TEXT    NOT NULL,
    data_type       TEXT    NOT NULL,  -- 'funding' or 'ohlcv'
    earliest_ms     INTEGER,          -- Earliest record we have
    latest_ms       INTEGER,          -- Latest record we have
    last_fetched_at INTEGER,          -- When we last ran a fetch
    PRIMARY KEY (symbol, data_type)
);

-- Track which pairs are in the top-20 and when they were last re-evaluated
CREATE TABLE IF NOT EXISTS tracked_pairs (
    symbol          TEXT    PRIMARY KEY,
    added_at        INTEGER NOT NULL,
    last_volume_24h TEXT,              -- Last known 24h volume for ranking
    is_active       INTEGER NOT NULL DEFAULT 1
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_funding_symbol_ts
    ON funding_rate_history(symbol, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_ts
    ON ohlcv_candles(symbol, timestamp_ms);
```

### ccxt fetch_funding_rate_history Return Format
```python
# Source: ccxt unified API (verified via installed ccxt 4.5.37)
# Returns list of dicts with these keys:
record = {
    "info": { ... },          # Raw Bybit response
    "symbol": "BTC/USDT:USDT",  # Unified ccxt symbol
    "fundingRate": 0.0001,    # Funding rate as float
    "timestamp": 1700000000000,  # Unix ms
    "datetime": "2023-11-14T22:13:20.000Z",  # ISO 8601
}
```

### ccxt fetch_ohlcv Return Format
```python
# Source: ccxt unified API (verified via installed ccxt 4.5.37)
# Returns list of lists: [timestamp, open, high, low, close, volume]
candle = [
    1700000000000,  # Unix ms timestamp
    37000.0,        # Open
    37100.0,        # High
    36900.0,        # Low
    37050.0,        # Close
    123.456,        # Volume (base coin for linear)
]
```

### Bulk Insert with Deduplication
```python
# Source: SQLite INSERT OR IGNORE + aiosqlite executemany
async def insert_funding_rates(
    self,
    records: list[dict],
) -> int:
    """Insert funding rate records, ignoring duplicates."""
    if not records:
        return 0

    data = [
        (r["symbol"], r["timestamp"], str(r["fundingRate"]), r.get("intervalHours", 8))
        for r in records
    ]

    async with self._db.cursor() as cursor:
        await cursor.executemany(
            """INSERT OR IGNORE INTO funding_rate_history
               (symbol, timestamp_ms, funding_rate, interval_hours)
               VALUES (?, ?, ?, ?)""",
            data,
        )
        await self._db.commit()
        return cursor.rowcount  # Number of actually inserted rows
```

### Top 20 Pairs by Volume Selection
```python
# Source: Existing FundingMonitor.get_all_funding_rates() already has volume data
# The bot already fetches all linear tickers with volume_24h

def select_top_pairs(
    funding_rates: list[FundingRateData],
    count: int = 20,
) -> list[str]:
    """Select top N USDT linear perpetual pairs by 24h volume."""
    # Filter to USDT pairs only (exclude USDC perpetuals)
    usdt_pairs = [
        fr for fr in funding_rates
        if fr.symbol.endswith(":USDT")
    ]
    # Sort by 24h volume descending
    usdt_pairs.sort(key=lambda x: x.volume_24h, reverse=True)
    return [fr.symbol for fr in usdt_pairs[:count]]
```

### Startup Flow Integration
```python
# In orchestrator.start() or a new pre-start hook:
async def _ensure_historical_data(self) -> None:
    """Fetch/update historical data before starting trading loop."""
    if self._data_fetcher is None:
        return  # Historical data feature not enabled

    # 1. Determine top 20 pairs
    all_rates = self._funding_monitor.get_all_funding_rates()
    top_pairs = select_top_pairs(all_rates, count=20)

    # 2. Fetch/update data for all pairs (blocking)
    await self._data_fetcher.ensure_data_ready(top_pairs)

    logger.info("historical_data_ready", pairs=len(top_pairs))
```

### Configuration Settings
```python
class HistoricalDataSettings(BaseSettings):
    """Historical data fetch and storage settings."""

    model_config = SettingsConfigDict(env_prefix="HISTORICAL_")

    enabled: bool = True
    db_path: str = "data/historical.db"
    lookback_days: int = 365          # 1 year default
    ohlcv_interval: str = "1h"       # 1-hour candles
    top_pairs_count: int = 20
    pair_reeval_interval_hours: int = 168  # Weekly (7 * 24)
    max_retries: int = 5
    retry_base_delay: float = 1.0     # Seconds, doubles each retry
    fetch_batch_delay: float = 0.1    # Seconds between paginated calls (safety margin)
```

### Exponential Backoff Retry
```python
async def _fetch_with_retry(
    self,
    fetch_fn,
    *args,
    max_retries: int = 5,
    base_delay: float = 1.0,
    **kwargs,
) -> list:
    """Execute a fetch function with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            return await fetch_fn(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "fetch_retry",
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=str(e),
            )
            await asyncio.sleep(delay)
    return []  # unreachable, but satisfies type checker
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed 8h funding intervals | Dynamic intervals (8h/4h/2h/1h) | Oct 2025 | Must store interval per record; gap detection must be interval-aware |
| ccxt `paginate: True` | Manual timestamp-based pagination | Ongoing | ccxt auto-pagination is still experimental; manual is safer |
| aiosqlite Thread subclass | aiosqlite Connection (non-Thread) | v0.22.0 (Dec 2025) | Must use context manager or await `close()` explicitly |

**Deprecated/outdated:**
- ccxt `paginate` parameter for funding rate history: experimental and buggy with Bybit; do not rely on it
- Bybit v3 API: fully deprecated, v5 is current (ccxt 4.5.x uses v5 internally)
- aiosqlite Connection as Thread: removed in v0.22.0; use as context manager

## Recommendations (Claude's Discretion Areas)

### SQLite Schema Design
**Recommendation:** Four tables as shown in Code Examples above (`funding_rate_history`, `ohlcv_candles`, `fetch_state`, `tracked_pairs`). Use TEXT for all decimal values to preserve precision (consistent with the project's `Decimal` convention). Use INTEGER for timestamps in Unix milliseconds. Composite primary keys for natural deduplication.

**Migration approach:** Use a simple version check table. On first connection, check if a `schema_version` table exists. If not, create all tables. For future schema changes, add version-gated ALTER statements. No need for a full migration framework for 4 tables.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
```

### Retry Backoff Parameters
**Recommendation:** 5 retries maximum, starting at 1 second, doubling each time: 1s, 2s, 4s, 8s, 16s. Total max wait: 31 seconds. This covers transient API errors and brief rate limit responses without excessively delaying startup.

### Rate Limit Implementation
**Recommendation:** Rely on ccxt's built-in `enableRateLimit: True` (already configured, 20ms between calls). Add a small additional safety delay of 100ms between paginated batches to avoid hitting the IP-based 600 req/5s limit. The existing `aiolimiter` package in the project could be used for a secondary limiter if needed, but is likely unnecessary given ccxt's built-in handling.

### Incremental Update Logging Strategy
**Recommendation:** During scan-cycle incremental updates, log at DEBUG level for individual pair updates (e.g., "appended 1 funding rate for BTC/USDT:USDT"). Log at INFO level only the summary (e.g., "incremental_update_complete pairs=20 new_funding_records=20 new_candles=20"). This keeps signal-to-noise ratio high during normal operation while preserving detail at DEBUG.

### Dashboard Widget Layout and Styling
**Recommendation:** Add a "Data Status" panel as a fourth card in the top row (change from 3-col to 4-col grid, or add below the existing 3-col row). The widget should show:
- **Normal state:** "20 pairs tracked | 175,200 records | Jan 2025 -- Feb 2026 | Last sync: 2m ago"
- **Loading state:** Progress bar with "12/20 pairs -- Fetching ETH/USDT:USDT (45%)"
- **Warning state:** Yellow indicator for quality issues (e.g., "3 pairs have data gaps")

Match the existing card styling in the dashboard (Tailwind CSS classes, same background/border patterns).

## Open Questions

1. **ccxt symbol format in `fetch_funding_rate_history` for Bybit USDT perpetuals**
   - What we know: The unified format is `BTC/USDT:USDT` for perps. The method signature accepts `symbol` as first parameter.
   - What's unclear: Whether Bybit's `fetch_funding_rate_history` requires the native format (`BTCUSDT`) or ccxt handles conversion. The `fetch_tickers` already works with ccxt unified format.
   - Recommendation: Test with unified symbol format during implementation; ccxt should convert automatically. If not, convert via `exchange.market_id(symbol)`.

2. **Exact Bybit rate limit for market data endpoints**
   - What we know: IP-based limit is 600 requests per 5 seconds globally. Per-endpoint limits for market data are not explicitly documented separately.
   - What's unclear: Whether kline and funding rate history have their own per-endpoint limits beyond the IP limit.
   - Recommendation: Use ccxt's built-in rate limiter plus 100ms safety delay between batches. Monitor for 429 errors during initial testing and adjust if needed.

3. **Demo trading API support for historical data endpoints**
   - What we know: The project supports Bybit Demo Trading (separate API URLs). The existing `BybitClient` overrides URLs when `demo_trading: true`.
   - What's unclear: Whether `api-demo.bybit.com` supports `/v5/market/funding/history` and `/v5/market/kline` endpoints, or if market data must always come from the production API.
   - Recommendation: Market data endpoints are likely identical between demo and production APIs since they serve the same market data. Test during implementation.

## Sources

### Primary (HIGH confidence)
- Bybit API v5: Get Funding Rate History -- https://bybit-exchange.github.io/docs/v5/market/history-fund-rate (endpoint path, parameters, pagination behavior, max 200 records)
- Bybit API v5: Kline endpoint -- https://bybit-exchange.github.io/docs/v5/market/kline (parameters, max 1000 records, reverse-sorted)
- Bybit API v5: Rate Limits -- https://bybit-exchange.github.io/docs/v5/rate-limit (600 req/5s IP limit)
- Bybit API v5: Get Tickers -- https://bybit-exchange.github.io/docs/v5/market/tickers (volume24h, turnover24h fields for linear)
- ccxt 4.5.37 installed locally -- method signatures verified via `inspect.signature()`
- aiosqlite 0.22.1 (PyPI) -- https://pypi.org/project/aiosqlite/ (API, version, Python compat)
- Existing codebase -- `src/bot/exchange/bybit_client.py`, `src/bot/exchange/client.py`, `src/bot/config.py`, `src/bot/orchestrator.py`, `src/bot/main.py`

### Secondary (MEDIUM confidence)
- ccxt GitHub issues -- https://github.com/ccxt/ccxt/issues/17854, https://github.com/ccxt/ccxt/issues/15990 (pagination bugs, workarounds)
- Bybit dynamic funding rate announcement -- https://crypto-economy.com/bybit-introduces-automatic-funding-rate-frequency-adjustments-for-perpetual-contracts/ (dynamic intervals since Oct 2025)
- aiosqlite official docs -- https://aiosqlite.omnilib.dev/en/stable/api.html (API reference)

### Tertiary (LOW confidence)
- ccxt `paginate` parameter behavior -- based on WebSearch; experimental feature, exact behavior may vary by ccxt version
- Bybit market data endpoint-specific rate limits -- not explicitly documented; using conservative approach

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- aiosqlite and ccxt are verified, versions confirmed from installed packages and PyPI
- Architecture: HIGH -- patterns derived from existing codebase conventions and verified API contracts
- Pitfalls: HIGH -- pagination quirks and dynamic intervals verified via official Bybit docs and ccxt issue tracker
- Code examples: MEDIUM -- return formats verified from ccxt source, but actual pagination behavior needs runtime testing

**Research date:** 2026-02-12
**Valid until:** 2026-03-12 (30 days -- stable domain, Bybit API v5 is mature)
