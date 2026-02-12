# Architecture Patterns: v1.1 Strategy Intelligence

**Domain:** Crypto Funding Rate Arbitrage Bot -- Strategy Intelligence Layer
**Researched:** 2026-02-12
**Confidence:** HIGH (based on verified Bybit API docs, existing codebase analysis, and established patterns)

## Context: Existing Architecture

The v1.0 bot has a clean, well-factored architecture built on three key patterns:

1. **Orchestrator pattern** -- `Orchestrator` coordinates scan-rank-decide-execute cycle
2. **Dependency injection** -- All components injected via `_build_components()` in `main.py`
3. **Swappable executor** -- `Executor` ABC with `PaperExecutor`/`LiveExecutor` implementations

The core loop in `_autonomous_cycle()` follows this flow:
```
APPLY runtime config -> SCAN rates -> RANK opportunities -> DECIDE (close/open) -> MONITOR margin -> LOG
```

v1.1 adds three capabilities that must integrate without replacing existing patterns:
- **Historical data storage** -- Fetch and persist funding rates, klines, and market data
- **Signal analysis** -- Trend detection, pattern recognition feeding into entry/exit decisions
- **Dynamic position sizing** -- Conviction-based scaling replacing static `max_position_size_usd`

---

## Recommended Architecture: v1.1 Additions

```
                    ┌─────────────────────────────┐
                    │       Web Dashboard          │
                    │   (FastAPI + HTMX + WS)      │
                    │  + backtest results panel     │
                    │  + signal indicator panel     │
                    └──────────────┬───────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│                         Orchestrator                                │
│                                                                     │
│  _autonomous_cycle():                                               │
│    0. APPLY runtime config                                          │
│    1. SCAN rates (existing)                                         │
│    2. RANK opportunities (existing)                                 │
│  +-3. ANALYZE signals (NEW: SignalAnalyzer)                         │
│  +-4. SIZE positions (MODIFIED: DynamicPositionSizer)               │
│    5. DECIDE & EXECUTE (existing, but uses signal + size)           │
│    6. MONITOR margin (existing)                                     │
│    7. LOG status (existing)                                         │
└─┬────────┬────────┬────────┬──────────┬─────────┬──────────────────┘
  │        │        │        │          │         │
  │        │        │        │          │         │
┌─▼──┐  ┌─▼──┐  ┌──▼──┐  ┌─▼────┐  ┌──▼───┐  ┌─▼──────────────────┐
│Fund│  │Opp │  │Sig  │  │Dyn   │  │Back  │  │Historical Data     │
│Mon │  │Rank│  │Anlz │  │Sizer │  │test  │  │Store (aiosqlite)   │
│    │  │    │  │(NEW)│  │(NEW) │  │(NEW) │  │(NEW)               │
│ v1 │  │ v1 │  │     │  │      │  │      │  │                    │
└─┬──┘  └─┬──┘  └──┬──┘  └─┬────┘  └──┬───┘  └─┬──────────────────┘
  │        │        │       │          │         │
  │        │        └───────┼──────────┼─────────┤ reads from store
  │        │                │          │         │
  │        │                └──────────┼─────────┤ reads from store
  │        │                           │         │
  │        │                           └─────────┤ reads from store
  │        │                                     │
  └────────┼─────────────────────────────────────┤ writes to store
           │                                     │
┌──────────▼─────────────────────────────────────▼───────────────────┐
│                    Exchange Client (Bybit via ccxt)                 │
│  + fetch_funding_rate_history()  (NEW method on ExchangeClient)    │
│  + fetch_klines()                (NEW method on ExchangeClient)    │
└────────────────────────────────────────────────────────────────────┘
```

### New vs Modified Components

| Component | Status | Location | Purpose |
|-----------|--------|----------|---------|
| `HistoricalDataStore` | **NEW** | `src/bot/data/store.py` | SQLite persistence via aiosqlite |
| `HistoricalDataFetcher` | **NEW** | `src/bot/data/fetcher.py` | Bybit API historical data retrieval with pagination |
| `SignalAnalyzer` | **NEW** | `src/bot/strategy/signal_analyzer.py` | Trend/pattern analysis on funding rate history |
| `DynamicPositionSizer` | **NEW** | `src/bot/strategy/dynamic_sizer.py` | Conviction-based sizing replacing static sizer |
| `BacktestEngine` | **NEW** | `src/bot/backtest/engine.py` | Strategy replay against historical data |
| `BacktestExecutor` | **NEW** | `src/bot/backtest/executor.py` | Implements `Executor` ABC for backtesting |
| `ExchangeClient` | **MODIFIED** | `src/bot/exchange/client.py` | Add `fetch_funding_rate_history()`, `fetch_klines()` |
| `BybitClient` | **MODIFIED** | `src/bot/exchange/bybit_client.py` | Implement new abstract methods |
| `Orchestrator` | **MODIFIED** | `src/bot/orchestrator.py` | Insert signal analysis + dynamic sizing into cycle |
| `PositionSizer` | **PRESERVED** | `src/bot/position/sizing.py` | Kept as-is; `DynamicPositionSizer` wraps it |
| `OpportunityScore` | **EXTENDED** | `src/bot/models.py` | Add signal confidence field |
| `AppSettings` | **EXTENDED** | `src/bot/config.py` | Add strategy + backtest settings |

---

## Component Details

### 1. Historical Data Store (`src/bot/data/store.py`)

**Responsibility:** SQLite-based persistence for historical funding rates, klines, and market snapshots. Async via aiosqlite.

**Why SQLite + aiosqlite:**
- Already an async Python project; aiosqlite integrates naturally with asyncio
- No external database server to manage (single-file)
- Sufficient for the data volumes involved (funding rates = 3 records/day/symbol)
- Well-proven for time-series storage at this scale
- v1.0 already has in-memory-only storage; SQLite is the minimal step to persistence

**Schema design:**

```sql
-- Funding rate history (primary data for backtesting)
CREATE TABLE funding_rates (
    symbol      TEXT NOT NULL,
    rate        TEXT NOT NULL,  -- Decimal as string
    timestamp   INTEGER NOT NULL,  -- Unix ms
    interval_h  INTEGER NOT NULL DEFAULT 8,
    PRIMARY KEY (symbol, timestamp)
);
CREATE INDEX idx_fr_symbol_time ON funding_rates(symbol, timestamp DESC);

-- Price klines (for unrealized P&L simulation in backtests)
CREATE TABLE klines (
    symbol      TEXT NOT NULL,
    interval    TEXT NOT NULL,  -- '1h', '4h', etc.
    open_time   INTEGER NOT NULL,  -- Unix ms
    open        TEXT NOT NULL,
    high        TEXT NOT NULL,
    low         TEXT NOT NULL,
    close       TEXT NOT NULL,
    volume      TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, open_time)
);
CREATE INDEX idx_kl_symbol_interval_time ON klines(symbol, interval, open_time DESC);

-- Market snapshots (volume, open interest for market condition signals)
CREATE TABLE market_snapshots (
    symbol      TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    volume_24h  TEXT NOT NULL,
    mark_price  TEXT NOT NULL,
    PRIMARY KEY (symbol, timestamp)
);
```

**Interface:**

```python
class HistoricalDataStore:
    """Async SQLite store for historical market data."""

    def __init__(self, db_path: str = "data/history.db") -> None: ...

    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    # Write methods
    async def store_funding_rates(self, rates: list[FundingRateRecord]) -> int: ...
    async def store_klines(self, klines: list[KlineRecord]) -> int: ...
    async def store_market_snapshot(self, snapshot: MarketSnapshot) -> None: ...

    # Read methods for signal analysis
    async def get_funding_rates(
        self, symbol: str, start_ts: int, end_ts: int
    ) -> list[FundingRateRecord]: ...

    async def get_latest_funding_rates(
        self, symbol: str, n: int = 30
    ) -> list[FundingRateRecord]: ...

    async def get_klines(
        self, symbol: str, interval: str, start_ts: int, end_ts: int
    ) -> list[KlineRecord]: ...

    # Metadata
    async def get_data_range(self, symbol: str) -> tuple[int, int] | None: ...
    async def get_symbols_with_data(self) -> list[str]: ...
```

**Integration point:** Injected into `HistoricalDataFetcher`, `SignalAnalyzer`, `BacktestEngine`, and `FundingMonitor` (for auto-persisting live rates).

**Key design choice:** All monetary values stored as TEXT (string representation of Decimal). This preserves exact precision and matches the project's Decimal-everywhere convention. Conversion happens at the store boundary.

### 2. Historical Data Fetcher (`src/bot/data/fetcher.py`)

**Responsibility:** Fetch historical data from Bybit API and store it. Handles pagination, rate limiting, and gap detection.

**Bybit API endpoints used (verified against official docs):**

| Data | Endpoint | Limit | Pagination |
|------|----------|-------|------------|
| Funding rates | `/v5/market/history-fund-rate` | 200/request | Must pass `endTime`; returns records up to that time |
| Klines | `/v5/market/kline` | 1000/request | Use `start`/`end` timestamps |
| Mark price klines | `/v5/market/mark-price-kline` | 1000/request | Same as klines |

**Pagination strategy for funding rates:**
The Bybit API returns 200 records per call. Passing only `startTime` returns an error. The correct approach is to pass `endTime` and paginate backwards, using the oldest timestamp from the previous response as the next `endTime`.

```python
class HistoricalDataFetcher:
    """Fetches and stores historical data from Bybit API."""

    def __init__(
        self,
        exchange_client: ExchangeClient,
        store: HistoricalDataStore,
    ) -> None: ...

    async def fetch_funding_history(
        self,
        symbol: str,
        start_ts: int,  # Unix ms
        end_ts: int | None = None,  # None = now
    ) -> int:
        """Fetch funding rate history with backward pagination.

        Returns number of records stored.
        """
        ...

    async def fetch_kline_history(
        self,
        symbol: str,
        interval: str,  # "60", "240", "D"
        start_ts: int,
        end_ts: int | None = None,
    ) -> int: ...

    async def backfill_symbol(
        self, symbol: str, days_back: int = 90
    ) -> dict[str, int]:
        """Backfill all data types for a symbol. Returns counts."""
        ...

    async def backfill_all(
        self, symbols: list[str], days_back: int = 90
    ) -> dict[str, dict[str, int]]: ...
```

**Integration point:** Called at startup (backfill on first run), by backtest engine (ensure data exists), and potentially by a scheduled background task.

**Rate limiting:** Bybit's rate limit is 120 req/min for public endpoints. ccxt's `enableRateLimit: True` handles this automatically. The fetcher should add a small delay between paginated calls to be conservative.

### 3. Signal Analyzer (`src/bot/strategy/signal_analyzer.py`)

**Responsibility:** Analyze funding rate trends and market conditions to produce entry/exit signals with confidence scores.

**Signals to compute:**

| Signal | Method | Purpose |
|--------|--------|---------|
| Funding rate trend | EMA crossover on recent rates | Detect rising/falling funding rate trends |
| Rate stability | Standard deviation of last N rates | Avoid entering volatile-rate pairs |
| Rate persistence | Consecutive periods above threshold | Higher confidence for stable high rates |
| Volume confirmation | 24h volume relative to historical average | Avoid illiquid periods |
| Spread analysis | Spot-perp price spread vs historical | Detect convergence/divergence |

**Key design: Pure computation, no side effects.**
The `SignalAnalyzer` reads from `HistoricalDataStore` and produces `SignalResult` dataclasses. It does NOT make trading decisions -- the orchestrator uses signals to inform its existing decide logic.

```python
@dataclass
class SignalResult:
    """Analysis result for a single trading pair."""
    symbol: str
    trend: TrendDirection  # RISING, FALLING, STABLE
    trend_strength: Decimal  # 0.0 to 1.0
    rate_stability: Decimal  # lower = more stable = better
    consecutive_above_threshold: int  # funding periods
    volume_ratio: Decimal  # current vs historical average
    confidence: Decimal  # 0.0 to 1.0 composite score
    should_enter: bool
    should_exit: bool
    reasoning: str  # human-readable explanation

class TrendDirection(str, Enum):
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"

class SignalAnalyzer:
    """Analyzes funding rate history to produce trading signals."""

    def __init__(
        self,
        store: HistoricalDataStore,
        settings: SignalSettings,
    ) -> None: ...

    async def analyze(self, symbol: str) -> SignalResult: ...

    async def analyze_batch(
        self, symbols: list[str]
    ) -> dict[str, SignalResult]: ...

    # Internal computation methods (pure, testable)
    def _compute_ema(
        self, values: list[Decimal], span: int
    ) -> list[Decimal]: ...

    def _compute_trend(
        self, rates: list[FundingRateRecord]
    ) -> tuple[TrendDirection, Decimal]: ...

    def _compute_stability(
        self, rates: list[FundingRateRecord]
    ) -> Decimal: ...

    def _compute_persistence(
        self, rates: list[FundingRateRecord], threshold: Decimal
    ) -> int: ...

    def _compute_confidence(
        self, trend: TrendDirection, trend_strength: Decimal,
        stability: Decimal, persistence: int, volume_ratio: Decimal,
    ) -> Decimal: ...
```

**Integration into orchestrator cycle:**
The `SignalAnalyzer` is called AFTER ranking but BEFORE decide/execute. Its output enriches `OpportunityScore` with a confidence value that feeds into both the entry decision and the position sizer.

```python
# In Orchestrator._autonomous_cycle():
# ... existing SCAN and RANK steps ...

# 3. ANALYZE: Compute signals for ranked opportunities
signal_results = await self._signal_analyzer.analyze_batch(
    [opp.perp_symbol for opp in opportunities[:20]]  # top 20 only
)

# 4. ENRICH: Attach signals to opportunities
for opp in opportunities:
    signal = signal_results.get(opp.perp_symbol)
    if signal:
        opp.signal_confidence = signal.confidence
        opp.signal_should_enter = signal.should_enter

# 5. DECIDE & EXECUTE (existing logic, but now checks signal)
```

**Trend analysis approach: EMA crossover on funding rates.**
Use short-period EMA (3 funding periods = 24h) vs long-period EMA (9 funding periods = 3 days). When short EMA crosses above long EMA, the trend is rising. This is the simplest reliable trend detector and uses only the data we naturally have (funding rate history, sampled every 8h).

Standard moving averages are well-suited here because funding rates are already a discrete time series with fixed intervals (every 8h), unlike price data which is continuous. No need for complex time-series libraries.

### 4. Dynamic Position Sizer (`src/bot/strategy/dynamic_sizer.py`)

**Responsibility:** Calculate position size based on signal confidence and risk constraints, replacing the static `max_position_size_usd` approach.

**Key design: Wraps existing `PositionSizer`, does not replace it.**
The `DynamicPositionSizer` computes a `target_size_usd` based on conviction, then delegates to the existing `PositionSizer.calculate_matching_quantity()` which handles exchange constraints (qty_step, min_qty, min_notional). This preserves all existing exchange-constraint logic.

```python
class DynamicPositionSizer:
    """Conviction-based position sizing with risk constraints.

    Wraps the existing PositionSizer for exchange constraint handling.
    Replaces static max_position_size_usd with dynamic sizing.
    """

    def __init__(
        self,
        base_sizer: PositionSizer,
        settings: DynamicSizingSettings,
    ) -> None: ...

    def calculate_target_size_usd(
        self,
        confidence: Decimal,
        annualized_yield: Decimal,
        current_portfolio_exposure: Decimal,
        available_balance: Decimal,
    ) -> Decimal:
        """Compute target position size in USD.

        Scaling formula:
          base_size = min_position_size_usd
          conviction_multiplier = confidence * (annualized_yield / baseline_yield)
          target = base_size * conviction_multiplier
          target = clamp(target, min_position_size_usd, max_position_size_usd)
          target = min(target, max_portfolio_pct * available_balance - exposure)

        Returns target size in USD, already constrained.
        """
        ...

    def calculate_quantity(
        self,
        target_size_usd: Decimal,
        price: Decimal,
        available_balance: Decimal,
        spot_instrument: InstrumentInfo,
        perp_instrument: InstrumentInfo,
    ) -> Decimal | None:
        """Delegate to base_sizer with dynamic target.

        Temporarily overrides base_sizer's max_position_size_usd
        with our computed target, then calls
        base_sizer.calculate_matching_quantity().
        """
        ...
```

**Sizing model: Fractional Kelly with conviction scaling.**

Rather than full Kelly criterion (which requires accurate probability estimates we do not have), use a simplified conviction-based model:

1. **Base size:** Configurable minimum (e.g., $200)
2. **Conviction multiplier:** `confidence * (annualized_yield / baseline_yield)`, clamped to [1.0, max_multiplier]
3. **Risk constraints:**
   - Per-pair max: configurable cap (e.g., $2000)
   - Portfolio max: total exposure cannot exceed X% of balance
   - Correlation penalty: reduce size when many positions in similar assets
4. **Final size:** `base * multiplier`, clamped by all constraints

This is simpler and more robust than full Kelly because:
- We do not need to estimate win probability (hard for funding rates)
- The confidence score from `SignalAnalyzer` is already a composite of trend, stability, persistence
- Fractional approaches (half-Kelly, quarter-Kelly) are standard practice for robustness

**Integration into orchestrator:**

```python
# In Orchestrator._open_profitable_positions():
# Instead of using static self._settings.trading.max_position_size_usd:

target_size = self._dynamic_sizer.calculate_target_size_usd(
    confidence=opp.signal_confidence,
    annualized_yield=opp.annualized_yield,
    current_portfolio_exposure=current_exposure,
    available_balance=available_balance,
)
```

### 5. Backtest Engine (`src/bot/backtest/engine.py`)

**Responsibility:** Replay the orchestrator's strategy logic against historical data to evaluate parameter sets and compare strategies.

**Key design: Reuse existing components via the Executor ABC.**
The backtesting engine introduces a `BacktestExecutor` that implements the same `Executor` interface as `PaperExecutor` and `LiveExecutor`. This means ALL existing strategy logic (orchestrator, position manager, P&L tracker, opportunity ranker) runs unchanged during backtests.

This is the single most important architectural decision for v1.1: the backtest reuses the real trading logic, not a simplified simulation.

```python
class BacktestExecutor(Executor):
    """Executor that fills orders from historical price data.

    Implements the Executor ABC so the entire existing trading
    pipeline (PositionManager, Orchestrator) works unmodified.
    """

    def __init__(
        self, price_series: dict[str, list[KlineRecord]]
    ) -> None:
        self._prices = price_series
        self._current_time: int = 0
        self._fills: list[OrderResult] = []

    def set_time(self, timestamp: int) -> None:
        """Advance simulation clock."""
        self._current_time = timestamp

    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Fill at historical price for current simulation time."""
        price = self._get_price_at(request.symbol, self._current_time)
        # Apply simulated slippage and fees (same as PaperExecutor)
        ...

    async def cancel_order(self, order_id: str, symbol: str, category: str = "linear") -> bool:
        return True  # Instant fills, nothing to cancel
```

**Backtest engine orchestration:**

```python
class BacktestEngine:
    """Replays strategy against historical data."""

    def __init__(
        self,
        store: HistoricalDataStore,
        settings: AppSettings,
    ) -> None: ...

    async def run(
        self,
        symbols: list[str],
        start_ts: int,
        end_ts: int,
        strategy_params: dict | None = None,
    ) -> BacktestResult:
        """Run a single backtest.

        Steps:
        1. Load historical data from store
        2. Create BacktestExecutor with price series
        3. Build component graph (same as main._build_components)
           but with BacktestExecutor instead of Paper/Live
        4. Step through time: for each funding period:
           a. Update BacktestExecutor clock
           b. Feed historical rates to FundingMonitor (mock)
           c. Run one orchestrator cycle
           d. Record state
        5. Collect results from PnLTracker
        """
        ...

    async def optimize(
        self,
        symbols: list[str],
        start_ts: int,
        end_ts: int,
        param_grid: dict[str, list],
    ) -> list[BacktestResult]:
        """Run backtests across parameter combinations."""
        ...
```

**BacktestResult dataclass:**

```python
@dataclass
class BacktestResult:
    """Results of a single backtest run."""
    params: dict
    start_ts: int
    end_ts: int
    total_pnl: Decimal
    total_funding_collected: Decimal
    total_fees_paid: Decimal
    num_trades: int
    win_rate: Decimal | None
    sharpe_ratio: Decimal | None
    max_drawdown: Decimal | None
    positions: list[PositionPnL]
    # Comparison with baseline
    vs_simple_threshold: Decimal | None  # relative improvement
```

**Why custom engine instead of vectorbt/backtrader:**
- Funding rate arbitrage is NOT a standard OHLC-based strategy. It requires replaying funding rate snapshots, simulating 8h settlement cycles, and tracking dual-leg (spot+perp) positions. No existing framework handles this natively.
- The entire point is to reuse the REAL orchestrator/ranker/sizer logic via the Executor ABC. An external framework would require reimplementing the strategy from scratch, creating divergence between backtest and live.
- The project already has all the components (PositionManager, PnLTracker, FeeCalculator, analytics) -- the backtest engine just needs to feed them historical data and step through time.

### 6. ExchangeClient Extensions

**Two new abstract methods on `ExchangeClient` ABC:**

```python
class ExchangeClient(ABC):
    # ... existing methods ...

    @abstractmethod
    async def fetch_funding_rate_history(
        self,
        symbol: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Fetch historical funding rate records."""
        ...

    @abstractmethod
    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 200,
        category: str = "linear",
    ) -> list[dict]:
        """Fetch historical kline/candlestick data."""
        ...
```

**BybitClient implementation** maps directly to Bybit API v5 endpoints:
- `fetch_funding_rate_history` -> ccxt's `fetch_funding_rate_history()` or direct `/v5/market/history-fund-rate`
- `fetch_klines` -> ccxt's `fetch_ohlcv()` which maps to `/v5/market/kline`

---

## Data Flow Changes

### Live Trading Flow (modified steps marked with +)

```
1. SCAN: FundingMonitor polls exchange (existing)
      + FundingMonitor also writes to HistoricalDataStore (new)
2. RANK: OpportunityRanker scores pairs (existing, unchanged)
3. ANALYZE: SignalAnalyzer reads HistoricalDataStore (NEW step)
      produces SignalResult per symbol
4. DECIDE: Orchestrator uses signal.should_enter and
      signal.confidence (MODIFIED -- was threshold-only)
5. SIZE: DynamicPositionSizer uses signal.confidence
      to compute target size (MODIFIED -- was static)
6. EXECUTE: PositionManager + Executor (existing, unchanged)
7. MONITOR: RiskManager + margin checks (existing, unchanged)
```

### Backtest Flow (entirely new)

```
1. LOAD: BacktestEngine reads historical data from store
2. BUILD: Constructs component graph with BacktestExecutor
3. STEP: For each 8h funding period in range:
   a. Set BacktestExecutor time
   b. Feed historical rates to mock FundingMonitor
   c. Feed historical klines to mock TickerService
   d. Run one Orchestrator._autonomous_cycle()
4. COLLECT: Extract results from PnLTracker
5. ANALYZE: Compute metrics (reuses existing analytics/metrics.py)
```

### Historical Data Flow (new background process)

```
1. STARTUP: HistoricalDataFetcher.backfill_all() for configured symbols
2. CONTINUOUS: FundingMonitor writes each poll to store (append-only)
3. ON-DEMAND: BacktestEngine calls fetcher.backfill_symbol() if data missing
```

---

## Integration Points: Detailed

### Orchestrator Modifications

The `Orchestrator.__init__()` gains two new optional dependencies:

```python
class Orchestrator:
    def __init__(
        self,
        # ... existing 11 parameters ...
        signal_analyzer: SignalAnalyzer | None = None,    # NEW
        dynamic_sizer: DynamicPositionSizer | None = None,  # NEW
    ) -> None:
```

Making them optional (defaulting to `None`) means:
- v1.0 behavior is preserved when not injected
- Gradual rollout: add signals first, sizing later
- Tests can inject one without the other

The `_autonomous_cycle()` method adds steps 3 and 4 between RANK and DECIDE:

```python
async def _autonomous_cycle(self) -> None:
    # 0-2: existing (apply config, scan, rank)
    ...

    # 3. ANALYZE (new, optional)
    signal_results: dict[str, SignalResult] = {}
    if self._signal_analyzer is not None:
        symbols = [opp.perp_symbol for opp in opportunities[:20]]
        signal_results = await self._signal_analyzer.analyze_batch(symbols)

    # 4. ENRICH opportunities with signals (new)
    for opp in opportunities:
        signal = signal_results.get(opp.perp_symbol)
        if signal is not None:
            opp.signal_confidence = signal.confidence
            opp.signal_should_enter = signal.should_enter

    # 5-7: existing (close unprofitable, open profitable, monitor, log)
    # But _open_profitable_positions now checks signal_should_enter
    # and uses dynamic sizing if available
```

### Position Opening Modifications

`_open_profitable_positions()` currently uses static `self._settings.trading.max_position_size_usd`. With dynamic sizing:

```python
async def _open_profitable_positions(self, opportunities):
    for opp in opportunities:
        if not opp.passes_filters:
            continue

        # NEW: Check signal if available
        if hasattr(opp, 'signal_should_enter') and opp.signal_should_enter is False:
            continue

        # NEW: Dynamic sizing if available
        if self._dynamic_sizer is not None and hasattr(opp, 'signal_confidence'):
            target_size = self._dynamic_sizer.calculate_target_size_usd(
                confidence=opp.signal_confidence,
                annualized_yield=opp.annualized_yield,
                current_portfolio_exposure=self._get_current_exposure(),
                available_balance=available_balance,
            )
        else:
            target_size = self._settings.trading.max_position_size_usd

        # Existing risk check (now with dynamic size)
        can_open, reason = self._risk_manager.check_can_open(
            symbol=opp.perp_symbol,
            position_size_usd=target_size,
            current_positions=self._position_manager.get_open_positions(),
        )
        ...
```

### FundingMonitor Auto-Persistence

The `FundingMonitor._poll_once()` method optionally writes to the store:

```python
class FundingMonitor:
    def __init__(
        self,
        exchange: ExchangeClient,
        ticker_service: TickerService,
        poll_interval: float = 30.0,
        store: HistoricalDataStore | None = None,  # NEW
    ) -> None:
        ...
        self._store = store

    async def _poll_once(self) -> None:
        # ... existing polling logic ...

        # NEW: Persist to store (fire-and-forget, non-blocking)
        if self._store is not None:
            records = [
                FundingRateRecord(symbol=fr.symbol, rate=fr.rate, timestamp=fr.next_funding_time)
                for fr in self._funding_rates.values()
            ]
            try:
                await self._store.store_funding_rates(records)
            except Exception:
                logger.warning("store_funding_rates_failed", exc_info=True)
```

### Configuration Extensions

```python
class SignalSettings(BaseSettings):
    """Signal analysis parameters."""
    model_config = SettingsConfigDict(env_prefix="SIGNAL_")

    enabled: bool = True
    short_ema_span: int = 3     # funding periods (24h)
    long_ema_span: int = 9      # funding periods (3 days)
    min_confidence: Decimal = Decimal("0.3")  # below this, skip entry
    min_consecutive_periods: int = 2  # min periods above threshold
    lookback_periods: int = 30   # how much history to analyze

class DynamicSizingSettings(BaseSettings):
    """Dynamic position sizing parameters."""
    model_config = SettingsConfigDict(env_prefix="SIZING_")

    enabled: bool = True
    min_position_size_usd: Decimal = Decimal("200")
    max_position_size_usd: Decimal = Decimal("2000")
    max_multiplier: Decimal = Decimal("5")  # max conviction scaling
    baseline_yield: Decimal = Decimal("0.10")  # 10% annualized = 1x
    max_portfolio_pct: Decimal = Decimal("0.5")  # 50% max exposure

class BacktestSettings(BaseSettings):
    """Backtesting configuration."""
    model_config = SettingsConfigDict(env_prefix="BACKTEST_")

    db_path: str = "data/history.db"
    default_lookback_days: int = 90
    slippage_bps: Decimal = Decimal("5")  # basis points

class AppSettings(BaseSettings):
    # ... existing fields ...
    signal: SignalSettings = SignalSettings()        # NEW
    sizing: DynamicSizingSettings = DynamicSizingSettings()  # NEW
    backtest: BacktestSettings = BacktestSettings()  # NEW
```

### Main Wiring Changes (`main.py`)

```python
async def _build_components(settings: AppSettings) -> dict[str, Any]:
    # ... existing components 1-15 ...

    # 16. Historical data store
    store = HistoricalDataStore(settings.backtest.db_path)
    await store.connect()

    # 17. Historical data fetcher
    fetcher = HistoricalDataFetcher(exchange_client, store)

    # 18. Signal analyzer (if enabled)
    signal_analyzer = None
    if settings.signal.enabled:
        signal_analyzer = SignalAnalyzer(store, settings.signal)

    # 19. Dynamic position sizer (if enabled)
    dynamic_sizer = None
    if settings.sizing.enabled:
        dynamic_sizer = DynamicPositionSizer(position_sizer, settings.sizing)

    # Inject new deps into orchestrator
    orchestrator.signal_analyzer = signal_analyzer
    orchestrator.dynamic_sizer = dynamic_sizer

    # Update funding monitor with store
    funding_monitor._store = store  # or use setter method

    return {
        # ... existing components ...
        "store": store,
        "fetcher": fetcher,
        "signal_analyzer": signal_analyzer,
        "dynamic_sizer": dynamic_sizer,
    }
```

---

## Patterns to Follow

### Pattern 1: Extend Executor ABC for Backtesting

The v1.0 architecture's best feature is the swappable Executor. v1.1 adds a third implementation:

```
Executor (ABC)
  +-- PaperExecutor (simulated fills from live prices)
  +-- LiveExecutor (real exchange orders)
  +-- BacktestExecutor (fills from historical data)  # NEW
```

This pattern means the ENTIRE trading pipeline -- PositionManager, PnLTracker, FeeCalculator, analytics -- runs unchanged in all three modes. No special backtest logic leaking into production code.

### Pattern 2: Optional Injection for Gradual Feature Rollout

All new components are optional (`| None = None`). This means:
- Features can be enabled/disabled via config without code changes
- Each feature can be built and tested independently
- v1.0 behavior is the default fallback
- The orchestrator's existing tests pass without modification

### Pattern 3: Store Boundary with Decimal Conversion

All data crosses the SQLite boundary as strings:
- **Write:** `str(decimal_value)` before INSERT
- **Read:** `Decimal(row["value"])` after SELECT
- Never store or retrieve raw floats

This matches the project's existing Decimal-everywhere convention.

### Pattern 4: Computation Modules Are Pure

`SignalAnalyzer._compute_ema()`, `DynamicPositionSizer.calculate_target_size_usd()`, and analytics functions take data in, return results out. No I/O, no side effects, no state mutation. This makes them trivially testable with TDD (matching the project's existing test-first approach with 206+ tests).

### Pattern 5: Time-Stepped Backtest Simulation

The backtest does not try to replay real-time. It steps through discrete funding periods:

```
For each 8h period:
  1. Set BacktestExecutor.current_time
  2. Feed MockFundingMonitor with that period's rates
  3. Feed MockTickerService with that period's prices
  4. Call Orchestrator._autonomous_cycle() once
```

This is correct for funding rate arbitrage because:
- Funding rates change on 8h boundaries (not continuously)
- Position entry/exit decisions happen at cycle boundaries
- No need for tick-level simulation (the strategy is inherently low-frequency)

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Separate Backtest Strategy Implementation

**What goes wrong:** Writing backtest logic that duplicates the orchestrator's decision-making.
**Why it happens:** Seems simpler than wiring up the real components.
**Consequence:** Backtest results do not reflect live behavior. The whole point of backtesting is defeated.
**Prevention:** Always use the BacktestExecutor through the real Orchestrator. Never write `if backtesting:` branches in strategy code.

### Anti-Pattern 2: Loading All Historical Data Into Memory

**What goes wrong:** `SELECT * FROM funding_rates` into a list for an entire year.
**Why it happens:** Simpler code.
**Consequence:** Memory exhaustion for large datasets (500+ symbols x 365 days x 3 rates/day = 500K+ records).
**Prevention:** Always query with time bounds. Use generators/async iterators for large result sets. The `SignalAnalyzer` only needs the last 30 periods per symbol, not the full history.

### Anti-Pattern 3: Coupling Signal Logic to Orchestrator

**What goes wrong:** Putting trend analysis computations inside `Orchestrator._autonomous_cycle()`.
**Why it happens:** Quick to implement.
**Consequence:** Orchestrator becomes untestable monolith. Cannot reuse signals in backtest or dashboard.
**Prevention:** `SignalAnalyzer` is a standalone component. Orchestrator calls `analyze_batch()` and gets results. No computation leaks into orchestrator.

### Anti-Pattern 4: Breaking the PositionSizer Contract

**What goes wrong:** `DynamicPositionSizer` bypasses `PositionSizer.calculate_matching_quantity()` and computes quantities directly.
**Why it happens:** Seems more direct.
**Consequence:** Loses exchange constraint validation (qty_step, min_qty, min_notional). Orders get rejected.
**Prevention:** `DynamicPositionSizer` computes `target_size_usd`, then delegates quantity calculation to the existing `PositionSizer` with that target.

---

## Suggested Build Order

The build order is determined by dependency chains and the ability to validate each layer independently.

### Phase 1: Data Foundation

**Build:** `HistoricalDataStore` + `HistoricalDataFetcher` + `ExchangeClient` extensions
**Why first:** Everything else depends on historical data. Without persistence, signal analysis and backtesting have nothing to work with.
**Validates:** Data can be fetched from Bybit, stored in SQLite, and retrieved correctly.
**Test approach:** Unit tests with mock exchange responses. Integration test fetching real data from Bybit testnet.

### Phase 2: Signal Analysis

**Build:** `SignalAnalyzer` + `SignalSettings` + models (`SignalResult`, `TrendDirection`)
**Why second:** Pure computation on stored data. Does not require backtest engine. Can be validated visually against known market data.
**Validates:** Trend detection, stability metrics, confidence scoring produce sensible outputs.
**Test approach:** TDD with known data sets. Feed in synthetic funding rate sequences with known trends, verify correct signals.

### Phase 3: Dynamic Position Sizing

**Build:** `DynamicPositionSizer` + `DynamicSizingSettings`
**Why third:** Depends on signal confidence from Phase 2. Pure computation, easily tested.
**Validates:** Conviction scaling produces correct sizes. Exchange constraints still respected (via delegation to existing `PositionSizer`).
**Test approach:** TDD. Parameterized tests: low confidence -> small size, high confidence -> large size, respects caps.

### Phase 4: Orchestrator Integration

**Build:** Modify `Orchestrator` to use `SignalAnalyzer` + `DynamicPositionSizer`. Modify `FundingMonitor` for auto-persistence. Update `main.py` wiring.
**Why fourth:** All new components are ready and tested. This phase wires them together.
**Validates:** End-to-end live flow works with signals and dynamic sizing. Existing tests still pass (optional injection).
**Test approach:** Integration tests with mocked components. Verify existing orchestrator tests pass unchanged.

### Phase 5: Backtest Engine

**Build:** `BacktestExecutor` + `BacktestEngine` + `BacktestSettings` + `BacktestResult`
**Why fifth:** Requires all previous phases. The backtest reuses the full component graph.
**Validates:** Strategy replay produces results consistent with known outcomes. Compare backtest of v1.0-style simple threshold vs v1.1 signal-enhanced strategy.
**Test approach:** Backtest known period with known outcomes. Verify P&L matches manual calculation.

### Phase 6: Dashboard Extensions

**Build:** Backtest results panel, signal indicators on opportunity table.
**Why last:** Display layer for features built in previous phases. Not on critical path.
**Validates:** User can trigger backtests, view results, see signal confidence on opportunities.

### Dependency Graph

```
Phase 1: Data Foundation ──────────────┐
                                        │
Phase 2: Signal Analysis ◄─────────────┤
                                        │
Phase 3: Dynamic Sizing ◄──────────────┤ (needs signals)
                                        │
Phase 4: Orchestrator Integration ◄────┤ (needs signals + sizing)
                                        │
Phase 5: Backtest Engine ◄─────────────┘ (needs everything)

Phase 6: Dashboard ◄── Phase 4, 5 (display layer)
```

Phases 2 and 3 could be built in parallel since they only depend on Phase 1 and Phase 3 uses Phase 2's output type but not its implementation. However, building sequentially is cleaner for testing.

---

## Scalability Considerations

| Concern | Current (v1.0) | After v1.1 | Future Growth |
|---------|----------------|------------|---------------|
| **Data storage** | In-memory only | SQLite file (sufficient for 100K+ records) | Could migrate to PostgreSQL if multi-instance |
| **Backtest speed** | N/A | Sequential, single-threaded (fine for 90-day runs) | Could parallelize parameter grid with asyncio.gather |
| **Signal computation** | N/A | Per-symbol, synchronous within batch | Could cache computed signals with TTL |
| **Memory usage** | All state in-memory | Historical data in SQLite, queried as needed | Already bounded by query limits |
| **API rate limits** | ccxt rate limiter | Same + conservative delay in fetcher | Sufficient for current scale |

---

## File Structure After v1.1

```
src/bot/
  __init__.py
  config.py             # MODIFIED: add Signal/Sizing/Backtest settings
  models.py             # MODIFIED: add signal fields to OpportunityScore
  orchestrator.py       # MODIFIED: add signal/sizing integration
  main.py               # MODIFIED: wire new components
  exceptions.py
  logging.py
  data/                 # NEW package
    __init__.py
    store.py            # HistoricalDataStore (aiosqlite)
    fetcher.py          # HistoricalDataFetcher
    models.py           # FundingRateRecord, KlineRecord, etc.
  strategy/             # NEW package
    __init__.py
    signal_analyzer.py  # SignalAnalyzer
    dynamic_sizer.py    # DynamicPositionSizer
  backtest/             # NEW package
    __init__.py
    engine.py           # BacktestEngine
    executor.py         # BacktestExecutor (implements Executor ABC)
    result.py           # BacktestResult
  analytics/
    metrics.py          # EXISTING (reused by backtest)
  exchange/
    client.py           # MODIFIED: add new abstract methods
    bybit_client.py     # MODIFIED: implement new methods
    types.py
  execution/
    executor.py         # EXISTING (BacktestExecutor implements this)
    paper_executor.py
    live_executor.py
  market_data/
    funding_monitor.py  # MODIFIED: optional store persistence
    opportunity_ranker.py
    ticker_service.py
  position/
    sizing.py           # EXISTING (wrapped by DynamicPositionSizer)
    manager.py
    delta_validator.py
  pnl/
    fee_calculator.py
    tracker.py
  risk/
    emergency.py
    manager.py
  dashboard/
    app.py
    routes/             # MODIFIED: add backtest + signal routes
    update_loop.py
```

---

## Sources

- [Bybit API: Get Funding Rate History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) -- official endpoint documentation, verified 2026-02-12
- [Bybit API: Get Kline](https://bybit-exchange.github.io/docs/v5/market/kline) -- official endpoint documentation, verified 2026-02-12
- [Bybit API: Get Mark Price Kline](https://bybit-exchange.github.io/docs/v5/market/mark-kline) -- official endpoint documentation, verified 2026-02-12
- [ccxt GitHub: Bybit funding rate history issues](https://github.com/ccxt/ccxt/issues/17854) -- pagination limitations documented
- [ccxt GitHub: fetch_funding_rate_history since/limit](https://github.com/ccxt/ccxt/issues/15990) -- parameter handling quirks
- [aiosqlite PyPI](https://pypi.org/project/aiosqlite/) -- async SQLite for Python
- [50shadesofgwei/funding-rate-arbitrage backtesting framework](https://deepwiki.com/50shadesofgwei/funding-rate-arbitrage/5.1-backtesting-framework) -- reference architecture for funding rate backtesting
- [QuantStart: Event-Driven Backtesting with Python](https://www.quantstart.com/articles/Event-Driven-Backtesting-with-Python-Part-I/) -- foundational pattern for custom backtest engines
- [Kelly Criterion for position sizing](https://www.pyquantnews.com/the-pyquant-newsletter/use-kelly-criterion-optimal-position-sizing) -- position sizing theory
- Existing codebase analysis: `src/bot/orchestrator.py`, `src/bot/execution/executor.py`, `src/bot/position/sizing.py`, `src/bot/main.py`

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Bybit API integration | HIGH | Verified against official API docs |
| Executor pattern extension | HIGH | Proven pattern in existing codebase, natural extension |
| Signal analysis approach | MEDIUM | EMA crossover is standard but funding rate patterns need empirical validation |
| Dynamic sizing model | MEDIUM | Conviction scaling is sound but parameters need backtest tuning |
| aiosqlite for storage | HIGH | Well-established library, verified active maintenance |
| Build order | HIGH | Based on dependency analysis of actual codebase |
| Custom backtest vs framework | HIGH | Funding rate arb requires custom data flow that frameworks do not support |
