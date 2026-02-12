# Stack Research: Strategy Intelligence (v1.1)

**Domain:** Funding rate arbitrage -- backtesting, trend analysis, dynamic position sizing
**Researched:** 2026-02-12
**Confidence:** HIGH (existing stack is established; new additions are stdlib/well-verified)

## Existing Stack (DO NOT CHANGE)

Already validated in v1.0 -- included here for integration context only:

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.12 | Runtime |
| ccxt | >=4.5.0 | Exchange API (Bybit) -- async via `ccxt.async_support` |
| FastAPI | >=0.115 | Dashboard backend |
| HTMX + Tailwind | -- | Dashboard frontend |
| Jinja2 | >=3.1 | Template rendering |
| pydantic | >=2.5 | Config validation, data models |
| pydantic-settings | >=2.12 | Environment-based config |
| structlog | >=25.5 | Structured logging |
| aiolimiter | >=1.2 | Rate limiting |
| Decimal (stdlib) | -- | All monetary math |
| asyncio (stdlib) | -- | Concurrency |
| pytest / pytest-asyncio | >=8.0 / >=0.23 | Testing |

## Recommended NEW Stack Additions

### Core: NumPy -- Numerical Foundation

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| numpy | >=2.4.0 | Array math for trend analysis, moving averages, statistical calculations | Industry standard for numerical computing. Required by scipy. EMA/SMA calculations are 10-100x faster than pure Python loops. v2.4.2 is current (Feb 2026), supports Python 3.12. |

**Confidence:** HIGH -- verified via [numpy.org/news](https://numpy.org/news/) and [PyPI](https://pypi.org/project/numpy/). NumPy 2.4.2 released 2026-02-01, supports Python 3.11-3.14.

**Integration:** NumPy arrays work alongside Decimal for different domains. Use Decimal for monetary calculations (position sizes, fees, P&L). Use NumPy for statistical analysis (trend slopes, moving averages, z-scores) where float precision is acceptable and speed matters.

**Pattern:**
```python
# Convert Decimal funding rates to numpy for analysis
rates_decimal: list[Decimal] = [fr.rate for fr in historical_rates]
rates_np = np.array([float(r) for r in rates_decimal], dtype=np.float64)

# Fast statistical analysis
slope = np.polyfit(np.arange(len(rates_np)), rates_np, 1)[0]
ema = _exponential_moving_average(rates_np, span=12)

# Results back to Decimal for trading decisions
if Decimal(str(slope)) > threshold:
    ...
```

---

### Core: SciPy -- Statistical Testing and Optimization

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| scipy | >=1.17.0 | `scipy.stats.linregress` for trend detection, `scipy.optimize.brute` for parameter grid search, `scipy.stats.percentileofscore` for rate regime classification | Provides rigorous statistical tests (p-values for trend significance) that hand-rolled code cannot match. Grid search via `brute()` is perfect for small parameter spaces (3-5 params) without adding heavy frameworks. |

**Confidence:** HIGH -- verified via [SciPy docs v1.17.0](https://docs.scipy.org/doc/scipy/release.html). Released 2026-01-10, requires Python 3.11-3.14 and NumPy >=1.26.4.

**Why scipy.optimize.brute over Optuna:** Our backtesting parameter space is small (entry threshold, exit threshold, min holding periods, max positions, position size -- roughly 5 parameters). `scipy.optimize.brute` handles this cleanly with zero additional dependencies beyond scipy itself. Optuna (v4.7.0) pulls in SQLAlchemy, Alembic, colorlog, tqdm, and pyyaml -- heavy dependency bloat for a problem that grid search solves in seconds. Save Optuna for if/when the parameter space grows to 10+ dimensions or needs Bayesian optimization.

**Key functions we will use:**

```python
from scipy.stats import linregress, percentileofscore
from scipy.optimize import brute

# Trend detection: Is funding rate increasing or decreasing?
slope, intercept, r_value, p_value, std_err = linregress(
    np.arange(len(rates)), rates
)
is_trending = p_value < 0.05 and abs(slope) > min_slope

# Regime classification: Where does current rate sit historically?
percentile = percentileofscore(historical_rates, current_rate)

# Parameter optimization for backtesting
def objective(params):
    entry, exit_rate, min_hold = params
    return -backtest_sharpe(entry, exit_rate, min_hold)  # Minimize negative Sharpe

optimal = brute(objective, ranges=[
    (0.0001, 0.001, 0.0001),  # entry threshold range
    (0.00005, 0.0005, 0.00005),  # exit threshold range
    (1, 8, 1),  # min holding periods
])
```

---

### Core: aiosqlite -- Async Historical Data Storage

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| aiosqlite | >=0.22.0 | Async SQLite for persisting historical funding rates, OHLCV data, and backtest results | Zero-infrastructure storage that fits the existing asyncio architecture. No database server needed. SQLite with WAL mode handles concurrent reads (dashboard) with single writer (data collector) at thousands of ops/sec. stdlib sqlite3 underneath. |

**Confidence:** HIGH -- verified via [PyPI](https://pypi.org/project/aiosqlite/) and [GitHub](https://github.com/omnilib/aiosqlite). v0.22.1 released 2025-12-23, requires Python >=3.9.

**Why aiosqlite over PostgreSQL/TimescaleDB:** The v1.0 architecture is intentionally stateless (in-memory dicts). Historical data for backtesting needs persistence, but PostgreSQL adds operational complexity (server process, connection pooling, migrations) that this project does not need. SQLite files are self-contained, require no server, and can store millions of funding rate records efficiently. The data volume is modest: ~200 symbols x 3 rates/day x 365 days = ~219K rows/year.

**Why aiosqlite over sync sqlite3:** The bot runs on asyncio. Blocking the event loop with synchronous SQLite calls would freeze the trading engine during database writes. aiosqlite wraps sqlite3 in a background thread with an async interface that integrates naturally with the existing `async def` patterns throughout the codebase.

**Schema pattern:**
```python
async with aiosqlite.connect("data/historical.db") as db:
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS funding_rates (
            symbol TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            rate TEXT NOT NULL,  -- Store as text for Decimal precision
            PRIMARY KEY (symbol, timestamp_ms)
        )
    """)
```

---

## Supporting Libraries

### NO new supporting libraries needed

The following capabilities will be built with the core additions above plus stdlib:

| Capability | Implementation | Libraries Used |
|-----------|----------------|----------------|
| Exponential Moving Average (EMA) | ~10 lines of numpy code | numpy |
| Simple Moving Average (SMA) | `np.convolve()` with uniform weights | numpy |
| Linear trend detection | `scipy.stats.linregress()` | scipy |
| Rate regime classification | `scipy.stats.percentileofscore()` | scipy |
| Funding rate mean reversion score | Z-score: `(rate - mean) / std` | numpy |
| Parameter grid search | `scipy.optimize.brute()` | scipy |
| Historical data persistence | SQLite with WAL mode | aiosqlite |
| Backtest event replay | Custom iterator over historical data | stdlib (dataclasses, itertools) |
| Conviction scoring | Weighted sum of trend + regime + momentum signals | numpy |
| Kelly criterion position sizing | `f = (bp - q) / b` | stdlib Decimal |

---

## Historical Data Acquisition (via existing ccxt)

No new library needed. ccxt already supports the required Bybit API endpoints.

### Funding Rate History

ccxt method: `exchange.fetch_funding_rate_history(symbol, since, limit, params)`

Bybit API: `GET /v5/market/funding/history` -- returns up to 200 records per call. Pagination via `endTime` parameter (walk backwards). Public endpoint but ccxt may require auth config.

**Known issues (verified via GitHub issues):**
- Pagination with `since` + `limit` has bugs in some ccxt versions. Use `params={"paginate": True}` for automatic pagination, or implement manual backwards-walking with `endTime`.
- Max 200 records per request from Bybit API.

### OHLCV / Kline History

ccxt method: `exchange.fetch_ohlcv(symbol, timeframe, since, limit, params)`

Bybit API: `GET /v5/market/kline` -- returns up to 1000 records per call. Available intervals: 1, 3, 5, 15, 30, 60, 120, 240, 360, 720, D, W, M.

**Data collection strategy:**
1. On first run, backfill historical data (walk backwards from now)
2. On subsequent runs, fetch only new data since last stored timestamp
3. Store in SQLite via aiosqlite
4. Backtest engine reads from SQLite, never hits API

---

## ExchangeClient Interface Extension

The existing `ExchangeClient` ABC needs two new methods for data collection:

```python
# Add to bot/exchange/client.py
@abstractmethod
async def fetch_funding_rate_history(
    self, symbol: str, since: int | None = None, limit: int | None = None,
    params: dict | None = None,
) -> list[dict]:
    """Fetch historical funding rates for a symbol."""
    ...

@abstractmethod
async def fetch_ohlcv(
    self, symbol: str, timeframe: str = "1h",
    since: int | None = None, limit: int | None = None,
    params: dict | None = None,
) -> list[list]:
    """Fetch OHLCV candles for a symbol."""
    ...
```

These map directly to ccxt's existing async methods -- the `BybitClient` implementation is trivial delegation.

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| numpy + scipy | pandas | Pandas is 30MB+ and pulls in pytz, dateutil, etc. We need array math and stats, not DataFrames. NumPy + SciPy are leaner and the existing codebase has zero pandas patterns to maintain consistency with. |
| numpy + scipy | polars | Same argument as pandas -- we don't need DataFrame operations. Polars is excellent but adds unnecessary abstraction for our use case (arrays of Decimal-converted floats). |
| scipy.optimize.brute | optuna (v4.7.0) | Optuna pulls SQLAlchemy, Alembic, colorlog, tqdm, pyyaml as mandatory deps. Our parameter space is 3-5 dimensions -- grid search handles this trivially. Optuna's Bayesian optimization is overkill and the dependency footprint is unacceptable for this scope. |
| scipy.optimize.brute | scikit-learn GridSearchCV | scikit-learn is 50MB+ with joblib, threadpoolctl dependencies. Designed for ML model hyperparams, not trading strategy params. |
| aiosqlite (SQLite) | PostgreSQL + asyncpg | PostgreSQL requires a running server process, connection pooling config, and schema migration tooling. Our data volume (~200K rows/year) is trivial for SQLite. The bot runs single-instance. No concurrent write contention. |
| aiosqlite (SQLite) | JSON files | JSON files work for prototyping (as the 50shadesofgwei project demonstrates) but degrade with millions of records. SQLite provides indexed queries, range scans by timestamp, and atomic writes without custom serialization code. |
| aiosqlite (SQLite) | DuckDB | DuckDB is excellent for analytics but adds a 50MB+ binary dependency. SQLite is stdlib-adjacent (ships with Python), and our query patterns are simple (range scans by symbol+timestamp). |
| Custom backtest engine | backtesting.py | backtesting.py is designed for price-action strategies (buy/sell signals on OHLCV). Funding rate arbitrage is fundamentally different: entry/exit on funding rate thresholds, P&L from funding payments not price movement. A custom engine that replays funding rate events is simpler and more accurate than adapting a price-action framework. |
| Custom backtest engine | backtrader | Same issue as backtesting.py -- designed for directional trading. Also, backtrader is not actively maintained (last release 2019). |
| pymannkendall | scipy.stats.linregress | pymannkendall (v1.4.3, last updated Jan 2023) is unmaintained. scipy.stats.linregress provides trend detection with p-values. For non-parametric needs, implement Mann-Kendall in ~20 lines of numpy rather than adding a stale dependency. |

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| pandas | Heavy (30MB+), introduces DataFrame paradigm foreign to codebase, not needed for array operations | numpy for arrays, Decimal for money |
| polars | Unnecessary DataFrame abstraction for this use case | numpy |
| optuna | Pulls SQLAlchemy/Alembic/5+ transitive deps for a 3-5 param optimization | scipy.optimize.brute |
| scikit-learn | 50MB+ ML framework for a simple grid search | scipy.optimize.brute |
| ta-lib / ta (technical analysis) | Designed for price-action indicators (RSI, MACD). Funding rate analysis needs custom metrics, not stock market indicators | numpy rolling calculations |
| backtrader / backtesting.py | Price-action backtesting frameworks incompatible with funding rate arbitrage model | Custom replay engine |
| PostgreSQL / asyncpg | Operational overhead for modest data volume | aiosqlite (SQLite) |
| Redis | No cache invalidation needs; in-memory dicts sufficient for hot data | Existing dict-based caches |
| pymannkendall | Unmaintained since Jan 2023 | scipy.stats.linregress or hand-rolled Mann-Kendall with numpy |
| statsmodels | Heavy dependency (pulls patsy, scipy already covers what we need) | scipy.stats |

---

## Installation

### New production dependencies

```bash
pip install "numpy>=2.4.0" "scipy>=1.17.0" "aiosqlite>=0.22.0"
```

### pyproject.toml additions

```toml
dependencies = [
    # ... existing deps ...
    "numpy>=2.4.0",
    "scipy>=1.17.0",
    "aiosqlite>=0.22.0",
]
```

### No new dev dependencies needed

The existing pytest + pytest-asyncio + pytest-mock stack covers testing for all new features. No additional test frameworks required.

---

## Version Compatibility Matrix

| Package | Version | Python 3.12 | Depends On | Verified |
|---------|---------|-------------|------------|----------|
| numpy | >=2.4.0 | Yes (3.11-3.14) | None | [PyPI](https://pypi.org/project/numpy/) 2026-02-01 |
| scipy | >=1.17.0 | Yes (3.11-3.14) | numpy >=1.26.4 | [SciPy docs](https://docs.scipy.org/doc/scipy/release.html) 2026-01-10 |
| aiosqlite | >=0.22.0 | Yes (>=3.9) | None (wraps stdlib sqlite3) | [PyPI](https://pypi.org/project/aiosqlite/) 2025-12-23 |

**Total new dependencies: 3 packages** (numpy, scipy, aiosqlite). SciPy depends on NumPy, so the actual new dependency tree is: numpy + scipy + aiosqlite. No transitive surprises.

---

## Stack Patterns by Feature Area

### If building the backtesting engine:
- Use aiosqlite for historical data storage (funding rates + OHLCV)
- Use ccxt's existing `fetch_funding_rate_history` and `fetch_ohlcv` for data collection
- Use numpy for fast array operations during simulation replay
- Use scipy.optimize.brute for parameter optimization
- Use existing Decimal-based PnL/fee calculators for accurate simulation
- Build custom event replay (not a framework) -- iterate over time-sorted records

### If building trend analysis:
- Use numpy for EMA, SMA, rolling statistics (mean, std, z-score)
- Use scipy.stats.linregress for linear trend detection with p-value significance
- Use scipy.stats.percentileofscore for historical regime classification
- Store computed signals in memory (small footprint, recomputed on startup)

### If building dynamic position sizing:
- Use existing Decimal arithmetic (PositionSizer pattern) for all sizing math
- Use numpy only for conviction score calculation (weighted signal aggregation)
- Convert conviction score to Decimal before applying to position size
- Kelly criterion and risk constraints stay in pure Decimal -- no numpy needed for money math

---

## Sources

- [NumPy releases](https://github.com/numpy/numpy/releases) -- v2.4.2 confirmed Feb 2026
- [SciPy v1.17.0 release notes](https://docs.scipy.org/doc/scipy/release.html) -- confirmed Jan 2026
- [aiosqlite on PyPI](https://pypi.org/project/aiosqlite/) -- v0.22.1 confirmed Dec 2025
- [Bybit API: Get Funding Rate History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) -- 200 records/page, pagination via endTime
- [Bybit API: Get Kline](https://bybit-exchange.github.io/docs/v5/market/kline) -- 1000 records/page, intervals 1m to Monthly
- [ccxt fetchFundingRateHistory issues](https://github.com/ccxt/ccxt/issues/15990) -- pagination bugs documented
- [ccxt fetchFundingRateHistory auth](https://github.com/ccxt/ccxt/issues/15974) -- auth may be required
- [Optuna v4.7.0](https://pypi.org/project/optuna/) -- confirmed but rejected due to dependency weight
- [pymannkendall](https://pypi.org/project/pymannkendall/) -- v1.4.3, last updated Jan 2023, rejected as unmaintained
- [scipy.optimize.brute docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.brute.html) -- grid search reference
- [scipy.stats.linregress docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.linregress.html) -- trend detection reference
- [50shadesofgwei/funding-rate-arbitrage backtesting](https://deepwiki.com/50shadesofgwei/funding-rate-arbitrage/5.1-backtesting-framework) -- reference architecture using JSON files

---
*Stack research for: Funding Rate Arbitrage v1.1 Strategy Intelligence*
*Researched: 2026-02-12*
