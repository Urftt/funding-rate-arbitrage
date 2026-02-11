# Architecture Patterns

**Domain:** Crypto Funding Rate Arbitrage Bot
**Researched:** 2026-02-11
**Confidence:** MEDIUM (based on training data and domain knowledge; web research tools unavailable)

## Recommended Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web Dashboard                            │
│                    (FastAPI/Flask + React)                       │
└────────────┬────────────────────────────────────────────────────┘
             │ REST API / WebSocket
             │
┌────────────▼────────────────────────────────────────────────────┐
│                      Bot Orchestrator                            │
│              (Main event loop, state machine)                    │
└─┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬─────────────┘
  │      │      │      │      │      │      │      │
  │      │      │      │      │      │      │      │
┌─▼──┐ ┌▼───┐ ┌▼────┐ ┌▼────┐ ┌▼───┐ ┌▼───┐ ┌▼───┐ ┌▼────────┐
│Data│ │Risk│ │Exec │ │Pos  │ │P&L │ │Ntfy│ │Cfg │ │Paper    │
│Feed│ │Mgr │ │Eng  │ │Mgr  │ │Eng │ │    │ │    │ │Trading  │
└─┬──┘ └┬───┘ └┬────┘ └┬────┘ └┬───┘ └────┘ └────┘ └─────────┘
  │      │      │       │       │
  │      │      │       │       │
┌─▼──────▼──────▼───────▼───────▼──────────────────────────────┐
│                   Exchange Adapter Layer                       │
│                  (Bybit WebSocket + REST)                      │
└────────────────────────────────────────────────────────────────┘
  │
┌─▼──────────────────────────────────────────────────────────────┐
│                      Persistence Layer                          │
│              (SQLite/PostgreSQL + Redis Cache)                 │
└────────────────────────────────────────────────────────────────┘
```

### Component Boundaries

| Component | Responsibility | Communicates With | Internal State |
|-----------|---------------|-------------------|----------------|
| **Web Dashboard** | User interface, controls, visualization | Bot Orchestrator (API/WS) | Session state only |
| **Bot Orchestrator** | Strategy execution, lifecycle management, coordination | All core components | Strategy state machine |
| **Data Feed Manager** | Market data ingestion, normalization, distribution | Exchange Adapter, Bot Orchestrator, Risk Manager | Price/funding cache |
| **Risk Manager** | Position limits, exposure checks, safety validations | Bot Orchestrator, Position Manager, Data Feed | Risk parameters, limits |
| **Execution Engine** | Order placement, fills tracking, slippage management | Exchange Adapter, Position Manager | Pending orders queue |
| **Position Manager** | Position state tracking, delta calculation, reconciliation | Exchange Adapter, Execution Engine, P&L Engine | Open positions map |
| **P&L Engine** | Realized/unrealized P&L, funding collection, performance | Position Manager, Data Feed, Persistence | P&L snapshots |
| **Notification Manager** | Alerts, error notifications, trade confirmations | Bot Orchestrator, Risk Manager | Notification queue |
| **Config Manager** | Strategy parameters, exchange credentials, runtime config | All components | Config cache |
| **Paper Trading Module** | Simulated execution, virtual positions, backtesting | Replaces Execution Engine in paper mode | Virtual balances |
| **Exchange Adapter** | API abstraction, rate limiting, connection management | Data Feed, Execution Engine, Position Manager | Connection pool, rate limits |
| **Persistence Layer** | Data storage, audit log, historical data | All components (via async writes) | Transaction log |

### Data Flow

#### 1. Market Data Flow (Real-time)
```
Exchange (WebSocket)
  → Exchange Adapter (normalize)
  → Data Feed Manager (distribute)
  → Bot Orchestrator (strategy logic)
  → Risk Manager (validate)
  → Execution Engine (orders)
  → Exchange Adapter (place orders)
  → Exchange
```

#### 2. Position Lifecycle Flow
```
Bot Orchestrator (signal)
  → Risk Manager (pre-trade check)
  → Execution Engine (create orders)
  → Exchange Adapter (submit)
  → Exchange (fills)
  → Exchange Adapter (fill events)
  → Position Manager (update state)
  → P&L Engine (calculate)
  → Persistence Layer (record)
  → Dashboard (display)
```

#### 3. Funding Collection Flow
```
Data Feed Manager (funding rate update)
  → Bot Orchestrator (evaluate positions)
  → P&L Engine (calculate expected funding)
  → Exchange (funding settlement at interval)
  → Exchange Adapter (funding event)
  → P&L Engine (record realized funding)
  → Persistence Layer (audit trail)
```

#### 4. User Control Flow
```
Dashboard (user action)
  → Bot Orchestrator API (validate)
  → Config Manager (update if needed)
  → Bot Orchestrator (execute command)
  → Notification Manager (confirm)
  → Dashboard (update UI via WebSocket)
```

## Patterns to Follow

### Pattern 1: Event-Driven Architecture
**What:** Components communicate via async events, not direct calls
**When:** Real-time market data, order fills, funding updates
**Why:** Decouples components, enables parallel processing, handles async nature of crypto APIs
**Example:**
```python
# Good: Event-driven
class DataFeedManager:
    async def on_price_update(self, symbol: str, price: Decimal):
        event = PriceUpdateEvent(symbol=symbol, price=price, timestamp=time.time())
        await self.event_bus.publish("price_update", event)

class BotOrchestrator:
    async def start(self):
        await self.event_bus.subscribe("price_update", self.handle_price_update)
        await self.event_bus.subscribe("fill", self.handle_fill)
        await self.event_bus.subscribe("funding", self.handle_funding)
```

### Pattern 2: Strategy State Machine
**What:** Bot lifecycle managed as explicit state transitions
**When:** Bot startup, trading, pausing, emergency shutdown
**Why:** Prevents invalid state transitions, enables safe pause/resume, clear error recovery
**States:**
- INITIALIZING → SCANNING → OPENING → MONITORING → CLOSING → IDLE
- Any state → ERROR → RECOVERING → (previous state or IDLE)

**Example:**
```python
from enum import Enum, auto
from typing import Optional

class BotState(Enum):
    INITIALIZING = auto()
    SCANNING = auto()
    OPENING = auto()
    MONITORING = auto()
    CLOSING = auto()
    IDLE = auto()
    ERROR = auto()
    RECOVERING = auto()

class BotOrchestrator:
    def __init__(self):
        self.state = BotState.INITIALIZING
        self.valid_transitions = {
            BotState.INITIALIZING: [BotState.SCANNING, BotState.ERROR],
            BotState.SCANNING: [BotState.OPENING, BotState.IDLE, BotState.ERROR],
            BotState.OPENING: [BotState.MONITORING, BotState.ERROR],
            BotState.MONITORING: [BotState.CLOSING, BotState.SCANNING, BotState.ERROR],
            BotState.CLOSING: [BotState.IDLE, BotState.ERROR],
            BotState.IDLE: [BotState.SCANNING],
            BotState.ERROR: [BotState.RECOVERING],
            BotState.RECOVERING: [BotState.IDLE, BotState.SCANNING]
        }

    async def transition_to(self, new_state: BotState):
        if new_state not in self.valid_transitions[self.state]:
            raise InvalidStateTransition(f"Cannot transition from {self.state} to {new_state}")
        await self._on_exit_state(self.state)
        old_state = self.state
        self.state = new_state
        await self._on_enter_state(new_state)
        await self.event_bus.publish("state_change", StateChangeEvent(old_state, new_state))
```

### Pattern 3: Circuit Breaker for Exchange API
**What:** Automatically stop API calls when error rate exceeds threshold
**When:** Exchange API calls, especially during high volatility
**Why:** Prevents cascading failures, protects against bans, graceful degradation
**Example:**
```python
from enum import Enum
import asyncio
from datetime import datetime, timedelta

class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Blocking calls
    HALF_OPEN = "half_open"  # Testing recovery

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED

    async def call(self, func, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if datetime.now() - self.last_failure_time > timedelta(seconds=self.timeout):
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerOpen("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            if self.state == CircuitState.HALF_OPEN:
                self.failures = 0
                self.state = CircuitState.CLOSED
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = datetime.now()
            if self.failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
            raise
```

### Pattern 4: Delta Neutrality Validator
**What:** Continuous validation that spot + perp positions maintain delta neutrality
**When:** After every position change, on scheduled intervals
**Why:** Core requirement of funding rate arbitrage; delta drift means directional exposure
**Example:**
```python
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class DeltaNeutralityCheck:
    spot_position: Decimal
    perp_position: Decimal
    delta_drift: Decimal
    drift_percentage: Decimal
    is_neutral: bool
    timestamp: float

class RiskManager:
    def __init__(self, max_drift_percentage: Decimal = Decimal("0.02")):  # 2%
        self.max_drift_percentage = max_drift_percentage

    async def validate_delta_neutrality(
        self,
        spot_qty: Decimal,
        perp_qty: Decimal
    ) -> DeltaNeutralityCheck:
        """
        For delta neutral: spot_qty + perp_qty ≈ 0
        (perp is negative since we're short)
        """
        delta_drift = abs(spot_qty + perp_qty)
        total_exposure = abs(spot_qty)

        if total_exposure == 0:
            drift_percentage = Decimal("0")
        else:
            drift_percentage = (delta_drift / total_exposure) * Decimal("100")

        is_neutral = drift_percentage <= self.max_drift_percentage

        return DeltaNeutralityCheck(
            spot_position=spot_qty,
            perp_position=perp_qty,
            delta_drift=delta_drift,
            drift_percentage=drift_percentage,
            is_neutral=is_neutral,
            timestamp=time.time()
        )
```

### Pattern 5: Async Queue-Based Execution
**What:** Order execution requests go through async queue
**When:** Multiple strategy signals, concurrent position updates
**Why:** Prevents race conditions, ensures sequential execution, handles backpressure
**Example:**
```python
import asyncio
from dataclasses import dataclass
from typing import Optional

@dataclass
class OrderRequest:
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    price: Optional[Decimal]
    priority: int = 0

class ExecutionEngine:
    def __init__(self):
        self.order_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.processing_task: Optional[asyncio.Task] = None

    async def start(self):
        self.processing_task = asyncio.create_task(self._process_orders())

    async def submit_order(self, order: OrderRequest):
        await self.order_queue.put((order.priority, order))

    async def _process_orders(self):
        while True:
            priority, order = await self.order_queue.get()
            try:
                await self._execute_order(order)
            except Exception as e:
                await self.handle_execution_error(order, e)
            finally:
                self.order_queue.task_done()
```

### Pattern 6: Position Reconciliation Loop
**What:** Periodically compare local position state with exchange state
**When:** Every N seconds (e.g., 30s), after fills, on startup
**Why:** Handles missed WebSocket messages, detects discrepancies, ensures system consistency
**Example:**
```python
class PositionManager:
    async def reconciliation_loop(self):
        while True:
            try:
                await asyncio.sleep(30)  # Every 30 seconds
                local_positions = await self.get_local_positions()
                exchange_positions = await self.exchange_adapter.get_positions()

                discrepancies = self._find_discrepancies(local_positions, exchange_positions)

                if discrepancies:
                    await self.notification_manager.alert(
                        "Position reconciliation discrepancies found",
                        details=discrepancies
                    )
                    await self._resolve_discrepancies(discrepancies)

            except Exception as e:
                await self.handle_reconciliation_error(e)
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Synchronous Blocking Calls
**What:** Using synchronous API calls in async event loop
**Why bad:** Blocks entire event loop, prevents concurrent operations, causes missed market data
**Instead:** Always use async/await with aiohttp or exchange library's async client
```python
# Bad
def get_funding_rate(symbol: str):
    response = requests.get(f"https://api.bybit.com/funding/{symbol}")
    return response.json()

# Good
async def get_funding_rate(symbol: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.bybit.com/funding/{symbol}") as response:
            return await response.json()
```

### Anti-Pattern 2: Shared Mutable State Without Locks
**What:** Multiple coroutines modifying same data structure without synchronization
**Why bad:** Race conditions, corrupted state, unpredictable behavior
**Instead:** Use asyncio.Lock for critical sections or immutable data structures
```python
# Bad
class PositionManager:
    def __init__(self):
        self.positions = {}  # Shared mutable state

    async def update_position(self, symbol, qty):
        current = self.positions.get(symbol, 0)
        await asyncio.sleep(0.1)  # Simulating async work
        self.positions[symbol] = current + qty  # Race condition!

# Good
class PositionManager:
    def __init__(self):
        self.positions = {}
        self._lock = asyncio.Lock()

    async def update_position(self, symbol, qty):
        async with self._lock:
            current = self.positions.get(symbol, 0)
            await asyncio.sleep(0.1)
            self.positions[symbol] = current + qty
```

### Anti-Pattern 3: Hardcoded Exchange-Specific Logic
**What:** Bybit API details scattered throughout codebase
**Why bad:** Makes it impossible to add other exchanges, tight coupling, hard to test
**Instead:** Encapsulate all exchange logic in adapter layer with common interface
```python
# Bad
class BotOrchestrator:
    async def get_funding_rate(self, symbol):
        # Bybit-specific logic in orchestrator
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}"
        response = await self.http_client.get(url)
        return response['result']['list'][0]['fundingRate']

# Good
class ExchangeAdapter(ABC):
    @abstractmethod
    async def get_funding_rate(self, symbol: str) -> Decimal:
        pass

class BybitAdapter(ExchangeAdapter):
    async def get_funding_rate(self, symbol: str) -> Decimal:
        url = f"{self.base_url}/v5/market/tickers"
        params = {"category": "linear", "symbol": symbol}
        response = await self._request("GET", url, params=params)
        return Decimal(response['result']['list'][0]['fundingRate'])

class BotOrchestrator:
    def __init__(self, exchange: ExchangeAdapter):
        self.exchange = exchange

    async def get_funding_rate(self, symbol):
        return await self.exchange.get_funding_rate(symbol)
```

### Anti-Pattern 4: Missing Error Recovery Strategy
**What:** Try/except that logs error but doesn't recover or notify
**Why bad:** Silent failures, stuck states, positions left unmanaged
**Instead:** Explicit error handling with state transitions and notifications
```python
# Bad
async def open_position(self, symbol, qty):
    try:
        await self.place_orders(symbol, qty)
    except Exception as e:
        logger.error(f"Failed to open position: {e}")
        # Now what? Position half-opened? System state unclear.

# Good
async def open_position(self, symbol, qty):
    try:
        await self.place_orders(symbol, qty)
    except InsufficientBalanceError as e:
        await self.transition_to(BotState.ERROR)
        await self.notification_manager.alert("Insufficient balance", critical=True)
        await self.strategy.disable()
    except ExchangeAPIError as e:
        await self.retry_with_backoff(self.place_orders, symbol, qty)
    except Exception as e:
        await self.transition_to(BotState.ERROR)
        await self.notification_manager.alert(f"Unexpected error: {e}", critical=True)
        await self.safe_shutdown()
```

### Anti-Pattern 5: Storing Secrets in Code/Git
**What:** API keys, passwords in source files or config committed to git
**Why bad:** Security breach, credential leak, impossible to rotate
**Instead:** Environment variables, secrets manager, .env files in .gitignore
```python
# Bad
class BybitAdapter:
    def __init__(self):
        self.api_key = "abc123"  # NEVER!
        self.api_secret = "xyz789"

# Good
import os
from dotenv import load_dotenv

class BybitAdapter:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("BYBIT_API_KEY")
        self.api_secret = os.getenv("BYBIT_API_SECRET")
        if not self.api_key or not self.api_secret:
            raise ValueError("Missing BYBIT_API_KEY or BYBIT_API_SECRET in environment")
```

### Anti-Pattern 6: No Rate Limiting
**What:** Sending API requests without respecting exchange rate limits
**Why bad:** Account banned, IP blocked, API errors
**Instead:** Implement token bucket or leaky bucket rate limiter
```python
# Bad
async def scan_all_pairs(self):
    for symbol in self.symbols:
        funding_rate = await self.exchange.get_funding_rate(symbol)
        # Hitting API 100+ times in quick succession!

# Good
from aiolimiter import AsyncLimiter

class ExchangeAdapter:
    def __init__(self):
        # Bybit: 120 requests per minute for public endpoints
        self.rate_limiter = AsyncLimiter(120, 60)

    async def get_funding_rate(self, symbol: str):
        async with self.rate_limiter:
            return await self._fetch_funding_rate(symbol)
```

## Scalability Considerations

| Concern | At MVP (1-5 pairs) | At Scale (20+ pairs) | At High Frequency |
|---------|-------------------|---------------------|-------------------|
| **Data Feed** | Single WebSocket connection | Connection pooling, symbol batching | Dedicated data feed service, Redis pub/sub |
| **Position Tracking** | In-memory dictionary | SQLite with indexes | PostgreSQL with partitioning |
| **Order Queue** | asyncio.Queue | Priority queue with persistence | Distributed queue (RabbitMQ/Redis) |
| **State Storage** | Local SQLite | PostgreSQL | PostgreSQL + Redis cache |
| **Risk Checks** | Synchronous validation | Async validation with caching | Pre-computed risk limits, stream processing |
| **Dashboard Updates** | Polling every 5s | WebSocket updates | Server-sent events with backpressure |
| **Backtesting Data** | CSV files | SQLite/PostgreSQL | Time-series DB (TimescaleDB/InfluxDB) |

## Build Order Implications

### Phase 1: Foundation Layer (No Dependencies)
**Build first because:** Everything depends on these
- **Config Manager** — All components need configuration
- **Persistence Layer** — Audit trail required from start
- **Exchange Adapter** — Gateway to exchange, needed for all operations

### Phase 2: Data Layer (Depends on: Phase 1)
**Build second because:** Strategy logic needs market data
- **Data Feed Manager** — Ingests and distributes market data
- **Position Manager** — Tracks position state

### Phase 3: Logic Layer (Depends on: Phase 1, 2)
**Build third because:** Needs data and execution infrastructure
- **Risk Manager** — Pre-trade checks before execution
- **Execution Engine** — Places orders based on strategy
- **P&L Engine** — Tracks profitability

### Phase 4: Orchestration Layer (Depends on: Phase 1, 2, 3)
**Build fourth because:** Coordinates all other components
- **Bot Orchestrator** — Main strategy loop, state machine

### Phase 5: Interface Layer (Depends on: All previous)
**Build fifth because:** Visualizes and controls the system
- **Web Dashboard** — User interface
- **Notification Manager** — Alerts and monitoring

### Dependency Graph
```
Config Manager ─────────────┐
Persistence Layer ──────────┼──┐
Exchange Adapter ───────────┼──┼──┐
                            │  │  │
Data Feed Manager ◄─────────┘  │  │
Position Manager ◄─────────────┘  │
                                  │
Risk Manager ◄────────────────────┤
Execution Engine ◄────────────────┤
P&L Engine ◄──────────────────────┘

Bot Orchestrator ◄────────────────(all above)

Web Dashboard ◄───────────────────(all above)
Notification Manager ◄────────────(all above)
```

### Critical Path
1. **Exchange Adapter** → Can't trade without API
2. **Data Feed Manager** → Can't make decisions without market data
3. **Execution Engine** → Can't place orders without execution
4. **Position Manager** → Can't track without position state
5. **Bot Orchestrator** → Can't automate without orchestration

### Parallel Development Opportunities
- **Config Manager** + **Persistence Layer** (independent)
- **Risk Manager** + **P&L Engine** (both use Position Manager, don't depend on each other)
- **Web Dashboard** + **Notification Manager** (both consume data, don't produce it)

### Testing Strategy by Layer
| Layer | Testing Approach |
|-------|------------------|
| Exchange Adapter | Mock API responses, test with Bybit testnet |
| Data Feed | Replay historical data, validate normalization |
| Risk Manager | Unit tests with edge cases (zero balance, max positions) |
| Execution Engine | Paper trading mode, simulated fills |
| Position Manager | Reconciliation tests, state invariant checks |
| Bot Orchestrator | Integration tests with mocked components |
| Dashboard | E2E tests, visual regression tests |

## Notes on Paper Trading Mode

**Implementation Strategy:** Paper trading should NOT be a separate codebase or rewrite of logic. Instead:

```python
class ExecutionEngine:
    def __init__(self, mode: str = "paper"):
        if mode == "paper":
            self.executor = PaperExecutor()
        elif mode == "live":
            self.executor = LiveExecutor()
        else:
            raise ValueError(f"Invalid mode: {mode}")

    async def place_order(self, order: OrderRequest):
        return await self.executor.place_order(order)

class PaperExecutor:
    """Simulates order execution without hitting exchange"""
    async def place_order(self, order: OrderRequest):
        # Simulate latency
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # Simulate fill at market price (optimistic)
        fill = Fill(
            order_id=generate_id(),
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.price or await self.get_market_price(order.symbol),
            fee=order.quantity * Decimal("0.001"),  # Simulate 0.1% fee
            timestamp=time.time()
        )

        await self.event_bus.publish("fill", fill)
        return fill

class LiveExecutor:
    """Real execution via exchange adapter"""
    async def place_order(self, order: OrderRequest):
        return await self.exchange_adapter.place_order(order)
```

**Advantages:**
- Single codebase for both modes
- Easy switching via configuration
- Paper mode tests real strategy logic
- Smooth transition to live trading

## Confidence Note

This architecture is based on domain knowledge of trading systems and Python async patterns from my training data (cutoff January 2025).

**Confidence Level: MEDIUM**
- Core patterns (event-driven, state machine, circuit breaker) are industry-standard for trading bots
- Python asyncio best practices are well-established
- Specific Bybit API details and current library ecosystem not verified (web search unavailable)
- Exchange adapter implementation details would benefit from current Bybit API documentation
- Rate limits and specific API behaviors should be verified against current Bybit documentation

**Recommended verification:**
- Bybit API v5 documentation for current rate limits and WebSocket specifications
- Current Python crypto trading libraries (ccxt, python-bybit) for async support
- Recent architecture examples from GitHub repositories of similar bots

## Sources

Due to tool restrictions (web search and read permissions unavailable), this architecture document is based on:
- Training data knowledge of trading bot architectures (cutoff January 2025)
- General software engineering patterns for async Python applications
- Domain knowledge of crypto derivatives and funding rate mechanics
- Standard practices for financial system design

**Next steps:** Verify specific technical details with:
- Official Bybit API documentation
- Current Python asyncio best practices (2026)
- Active crypto trading bot projects on GitHub
