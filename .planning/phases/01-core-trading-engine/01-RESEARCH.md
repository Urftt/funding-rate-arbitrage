# Phase 1: Core Trading Engine - Research

**Researched:** 2026-02-11
**Domain:** Bybit API integration, delta-neutral arbitrage execution, paper trading simulation
**Confidence:** MEDIUM-HIGH

## Summary

Phase 1 builds the foundation for a funding rate arbitrage bot: connecting to Bybit's V5 API, streaming real-time funding rates via WebSocket, executing simultaneous spot buy + perp short orders in paper mode, tracking simulated P&L including fees and funding payments, and continuously validating delta neutrality.

The research confirms that **ccxt** (v4.5.x) is the correct choice over pybit for this project. ccxt provides native Python async support via `ccxt.async_support` (critical for concurrent WebSocket streams and order placement), built-in rate limiting, WebSocket streaming via ccxt Pro (`ccxt.pro`), and a unified API that handles authentication, pagination, and Bybit V5 specifics. pybit (v5.14.0) is synchronous-only in its official release, which would require wrapping everything in thread executors -- an unnecessary complexity burden when ccxt already solves this.

Bybit's V5 API is well-suited for this use case. The Unified Trading Account allows spot and perp trading from a single account. The `/v5/market/tickers` endpoint returns `fundingRate`, `nextFundingTime`, and `fundingIntervalHour` for all perpetual pairs in a single call. WebSocket ticker streams push funding rate updates at 100ms frequency for derivatives. The funding rate sign convention is confirmed: **positive = longs pay shorts** (our strategy collects funding when positive). Bybit also offers a dedicated Demo Trading API (`api-demo.bybit.com`) that mirrors production endpoints, which can supplement our paper trading executor for validation.

**Primary recommendation:** Use ccxt with async support for all Bybit API interaction. Implement the swappable executor pattern (paper vs live) at the order execution layer, not the exchange client layer. Use Bybit's Demo Trading API for integration testing, but implement a local paper executor as the primary simulation engine for faster iteration and deterministic testing.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12+ | Runtime | Latest stable, best async performance, improved error messages |
| ccxt | 4.5.x | Bybit API client (REST + WebSocket) | Native async, Bybit certified, unified API for spot+perp, built-in rate limiting, WebSocket via ccxt Pro |
| pydantic | 2.5+ | Data validation & settings | Type-safe config, API response validation, `Decimal` support |
| pydantic-settings | 2.12+ | Configuration management | Env vars, .env files, type validation at startup |
| structlog | 25.5+ | Structured logging | JSON output, async context vars, processor chains |
| decimal | stdlib | Monetary calculations | Mandatory for all price/quantity/balance math |
| asyncio | stdlib | Concurrency | Native async/await for WebSocket streams + concurrent orders |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiolimiter | 1.2+ | Async rate limiting | Client-side rate limiting as safety net beyond ccxt's built-in |
| pytest | 8.x | Testing framework | All unit and integration tests |
| pytest-asyncio | 0.23+ | Async test support | Testing async exchange client and execution code |
| pytest-mock | 3.12+ | Mocking | Mock exchange API responses for deterministic tests |
| ruff | 0.4+ | Linting & formatting | Single tool replaces black+isort+flake8 |
| mypy | 1.8+ | Static type checking | Catch type errors in position sizing and API response handling |
| python-dotenv | 1.0+ | .env file loading | Development environment variable loading |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ccxt | pybit 5.14 | pybit is synchronous-only (official release). Would need thread executors for async. Lower-level, more boilerplate. Only advantage: official Bybit SDK. |
| ccxt | Raw aiohttp + Bybit REST | Maximum control but enormous boilerplate. Must implement auth, rate limiting, WebSocket reconnection, response parsing manually. |
| pydantic-settings | python-decouple | Less type safety, no nested model support, no validation |
| structlog | stdlib logging | No structured output, hard to query, no context binding |
| aiolimiter | Custom token bucket | Edge cases in timing, thread safety; aiolimiter is battle-tested |

**Installation:**
```bash
pip install "ccxt>=4.5.0" pydantic pydantic-settings structlog aiolimiter python-dotenv
pip install pytest pytest-asyncio pytest-mock ruff mypy  # dev dependencies
```

## Architecture Patterns

### Recommended Project Structure
```
src/
  bot/
    __init__.py
    main.py                  # Entry point, asyncio.run()
    config.py                # Pydantic settings, all configuration
    models.py                # Shared data models (Position, Order, FundingRate, etc.)
    exchange/
      __init__.py
      client.py              # Exchange client interface (ABC)
      bybit_client.py        # Bybit implementation via ccxt
      types.py               # Exchange-specific type definitions
    execution/
      __init__.py
      executor.py            # Executor interface (ABC)
      paper_executor.py      # Paper trading executor (simulated fills)
      live_executor.py       # Live executor (delegates to exchange client)
    market_data/
      __init__.py
      funding_monitor.py     # WebSocket funding rate streaming + REST fallback
      ticker_service.py      # Price data aggregation
    position/
      __init__.py
      manager.py             # Position state tracking
      delta_validator.py     # Delta neutrality validation
      sizing.py              # Position size calculation with Decimal
    pnl/
      __init__.py
      tracker.py             # P&L tracking (realized, unrealized, funding)
      fee_calculator.py      # Fee modeling for profitability checks
    risk/
      __init__.py
      manager.py             # Pre-trade risk checks
    orchestrator.py          # Main bot loop, state machine
    logging.py               # structlog configuration
tests/
  conftest.py                # Shared fixtures (mock exchange, paper executor)
  test_exchange/
  test_execution/
  test_market_data/
  test_position/
  test_pnl/
  test_risk/
  test_orchestrator.py
```

### Pattern 1: Swappable Executor (Paper vs Live)
**What:** Abstract base class for order execution. Paper executor simulates fills locally; live executor sends to exchange. All strategy logic is identical regardless of mode.
**When to use:** Always -- this is the core of PAPR-02 (identical code path).
**Example:**
```python
# Source: Architecture pattern for PAPR-02 requirement
from abc import ABC, abstractmethod
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"

@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    category: str = "linear"  # "spot" or "linear"

@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: OrderSide
    filled_qty: Decimal
    filled_price: Decimal
    fee: Decimal
    timestamp: float
    is_simulated: bool = False

class Executor(ABC):
    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Place a single order. Returns fill result."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str, category: str) -> bool:
        """Cancel an open order."""
        ...

class PaperExecutor(Executor):
    """Simulates order execution using current market prices."""

    def __init__(self, exchange_client, fee_rate: Decimal = Decimal("0.001")):
        self.exchange_client = exchange_client  # For fetching current prices
        self.fee_rate = fee_rate
        self.virtual_balance: dict[str, Decimal] = {}
        self.positions: list = []

    async def place_order(self, request: OrderRequest) -> OrderResult:
        # Fetch current market price for realistic simulation
        ticker = await self.exchange_client.fetch_ticker(request.symbol)
        fill_price = Decimal(str(ticker['last']))
        fee = request.quantity * fill_price * self.fee_rate

        return OrderResult(
            order_id=f"paper_{uuid4().hex[:12]}",
            symbol=request.symbol,
            side=request.side,
            filled_qty=request.quantity,
            filled_price=fill_price,
            fee=fee,
            timestamp=time.time(),
            is_simulated=True,
        )

class LiveExecutor(Executor):
    """Executes real orders via exchange client."""

    def __init__(self, exchange_client):
        self.exchange_client = exchange_client

    async def place_order(self, request: OrderRequest) -> OrderResult:
        result = await self.exchange_client.create_order(
            symbol=request.symbol,
            type=request.order_type.value,
            side=request.side.value,
            amount=float(request.quantity),
            price=float(request.price) if request.price else None,
            params={"category": request.category},
        )
        return OrderResult(
            order_id=result['id'],
            symbol=result['symbol'],
            side=OrderSide(result['side']),
            filled_qty=Decimal(str(result['filled'])),
            filled_price=Decimal(str(result['average'])),
            fee=Decimal(str(result['fee']['cost'])),
            timestamp=result['timestamp'] / 1000,
            is_simulated=False,
        )
```

### Pattern 2: Simultaneous Spot+Perp Order Placement
**What:** Open both legs of the delta-neutral position concurrently using `asyncio.gather`. Fail-safe: if either leg fails, cancel/reverse the other.
**When to use:** Every position open and close operation.
**Example:**
```python
# Source: Addresses Critical Pitfall #1 (incomplete delta hedge)
async def open_delta_neutral_position(
    self,
    symbol: str,
    spot_symbol: str,  # e.g., "BTC/USDT"
    perp_symbol: str,  # e.g., "BTC/USDT:USDT"
    quantity: Decimal,
) -> tuple[OrderResult, OrderResult]:
    spot_order = OrderRequest(
        symbol=spot_symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=quantity,
        category="spot",
    )
    perp_order = OrderRequest(
        symbol=perp_symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=quantity,
        category="linear",
    )

    try:
        spot_result, perp_result = await asyncio.wait_for(
            asyncio.gather(
                self.executor.place_order(spot_order),
                self.executor.place_order(perp_order),
            ),
            timeout=5.0,  # 5-second timeout for both legs
        )
    except asyncio.TimeoutError:
        # Emergency: cancel any pending orders
        await self._emergency_cancel(spot_symbol, perp_symbol)
        raise DeltaHedgeTimeout("Position opening timed out")
    except Exception as e:
        await self._emergency_cancel(spot_symbol, perp_symbol)
        raise DeltaHedgeError(f"Position opening failed: {e}")

    # Validate delta neutrality of the fills
    drift = abs(spot_result.filled_qty - perp_result.filled_qty)
    if drift / spot_result.filled_qty > Decimal("0.02"):  # 2% tolerance
        await self._emergency_close(spot_result, perp_result)
        raise DeltaDriftExceeded(f"Fill mismatch: spot={spot_result.filled_qty}, perp={perp_result.filled_qty}")

    return spot_result, perp_result
```

### Pattern 3: Funding Rate Monitor (WebSocket + REST Fallback)
**What:** Stream funding rates via WebSocket for real-time updates. Fall back to REST polling if WebSocket disconnects. Cache data with timestamps for freshness validation.
**When to use:** Continuous monitoring required by MKTD-01.
**Example:**
```python
# Source: Bybit V5 WebSocket ticker topic + REST /v5/market/tickers
import ccxt.pro as ccxtpro

class FundingMonitor:
    def __init__(self, exchange_config: dict):
        self.exchange = ccxtpro.bybit(exchange_config)
        self.funding_rates: dict[str, FundingRateData] = {}
        self._running = False

    async def start(self):
        self._running = True
        asyncio.create_task(self._stream_tickers())

    async def _stream_tickers(self):
        """Stream all perpetual tickers via WebSocket."""
        symbols = await self._get_perpetual_symbols()
        while self._running:
            try:
                # watch_tickers returns updated ticker data via WebSocket
                tickers = await self.exchange.watch_tickers(symbols)
                for symbol, ticker in tickers.items():
                    info = ticker.get('info', {})
                    funding_rate = info.get('fundingRate')
                    if funding_rate is not None:
                        self.funding_rates[symbol] = FundingRateData(
                            symbol=symbol,
                            rate=Decimal(str(funding_rate)),
                            next_funding_time=int(info.get('nextFundingTime', 0)),
                            interval_hours=int(info.get('fundingIntervalHour', 8)),
                            updated_at=time.time(),
                        )
            except Exception as e:
                logger.warning("WebSocket error, falling back to REST", error=str(e))
                await self._rest_fallback()
                await asyncio.sleep(5)

    async def get_all_funding_rates(self) -> list[FundingRateData]:
        """Return all cached funding rates, sorted by rate descending."""
        return sorted(
            self.funding_rates.values(),
            key=lambda x: x.rate,
            reverse=True,
        )
```

### Pattern 4: Configuration with Pydantic Settings
**What:** Type-safe, validated configuration loaded from environment variables and .env files.
**When to use:** All configuration -- exchange credentials, trading parameters, risk limits.
**Example:**
```python
# Source: pydantic-settings 2.12+ official docs
from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr
from decimal import Decimal

class ExchangeSettings(BaseSettings):
    model_config = {"env_prefix": "BYBIT_"}

    api_key: SecretStr
    api_secret: SecretStr
    testnet: bool = False
    demo_trading: bool = True  # Use demo API by default

class TradingSettings(BaseSettings):
    model_config = {"env_prefix": "TRADING_"}

    mode: str = "paper"  # "paper" or "live"
    max_position_size_usd: Decimal = Decimal("1000")
    min_funding_rate: Decimal = Decimal("0.0001")  # 0.01% minimum
    delta_drift_tolerance: Decimal = Decimal("0.02")  # 2% max drift
    order_timeout_seconds: float = 5.0

class FeeSettings(BaseSettings):
    model_config = {"env_prefix": "FEES_"}

    spot_taker: Decimal = Decimal("0.001")      # 0.1% (Bybit base tier)
    spot_maker: Decimal = Decimal("0.001")      # 0.1%
    perp_taker: Decimal = Decimal("0.00055")    # 0.055%
    perp_maker: Decimal = Decimal("0.0002")     # 0.02%

class AppSettings(BaseSettings):
    exchange: ExchangeSettings = ExchangeSettings()
    trading: TradingSettings = TradingSettings()
    fees: FeeSettings = FeeSettings()
```

### Anti-Patterns to Avoid
- **Float for money:** Never use Python `float` for price, quantity, balance, or fee calculations. Always `Decimal`. `0.1 + 0.2 != 0.3` in float math.
- **Synchronous calls in async loop:** pybit is sync. If used, every call blocks the event loop. Use ccxt async or `asyncio.to_thread()` wrapping.
- **Sequential order placement:** Placing spot then perp sequentially creates a directional exposure window. Always use `asyncio.gather()` for simultaneous placement.
- **Hardcoded exchange specifics:** All Bybit-specific logic must live in the exchange client layer, not in strategy or orchestrator code.
- **Polling for real-time data:** Use WebSocket streams for ticker/funding data. REST polling wastes rate limit budget and adds latency.
- **Global mutable state:** Use asyncio.Lock for shared position state. Multiple coroutines reading/writing positions concurrently causes race conditions.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exchange API authentication | Custom HMAC signing, request headers | ccxt (handles auth internally) | HMAC timing, header format, recv_window are subtle. ccxt handles all V5 auth. |
| WebSocket reconnection | Custom reconnect logic with backoff | ccxt Pro WebSocket manager | Connection drops, partial messages, resubscription are complex edge cases |
| Rate limiting | Custom token bucket implementation | ccxt built-in + aiolimiter as safety net | ccxt tracks rate limit headers per-endpoint. Bybit has per-UID rolling limits. |
| Decimal serialization | Custom JSON encoder for Decimal | pydantic models with Decimal fields | pydantic handles Decimal validation, serialization, and coercion from strings |
| Funding rate parsing | Custom response parser for Bybit JSON | ccxt unified ticker format | ccxt normalizes Bybit's response into standard ticker format with funding fields |
| Order lifecycle tracking | Custom state machine for order status | ccxt order management + local position state | ccxt handles order status polling, fill tracking, partial fill aggregation |

**Key insight:** ccxt abstracts away the most error-prone parts of exchange integration (authentication, rate limiting, WebSocket management, response normalization). The custom code should focus on the strategy logic: when to open/close positions, P&L tracking, delta validation, and the paper trading simulation layer.

## Common Pitfalls

### Pitfall 1: Funding Rate Sign Confusion
**What goes wrong:** Misinterpreting funding rate sign causes opening positions backwards, paying funding instead of collecting it.
**Why it happens:** Different exchanges use different conventions. Developers assume positive = "I receive money."
**How to avoid:** Bybit convention is **confirmed**: positive funding rate = longs pay shorts. Our strategy (long spot + short perp) collects funding when rate is positive. Encode this as a named constant with documentation:
```python
# BYBIT CONVENTION: Positive funding rate means longs pay shorts.
# Our strategy: LONG spot + SHORT perp = we COLLECT when rate > 0
FUNDING_DIRECTION_COLLECT = "positive"  # We want positive rates
```
Add unit tests that verify: when funding rate > 0, our P&L shows funding income (not expense).
**Warning signs:** P&L shows negative funding payments; funding collected is always zero or negative.

### Pitfall 2: Incomplete Delta Hedge (Partial Fills)
**What goes wrong:** Spot order fills fully but perp order fills partially (or vice versa), leaving directional exposure.
**Why it happens:** Market orders can have partial fills on illiquid pairs. Concurrent orders don't guarantee matching fill quantities.
**How to avoid:** After both orders return, compare `filled_qty`. If drift exceeds tolerance (2%), immediately close the unhedged portion. Use `asyncio.gather()` with timeout for simultaneous placement. Never leave a one-sided position open.
**Warning signs:** Delta validator reports drift > 2%; position monitor shows mismatched spot/perp quantities.

### Pitfall 3: Blocking the Async Event Loop
**What goes wrong:** A synchronous call (e.g., database write, HTTP request via `requests`) blocks the entire event loop. WebSocket messages queue up, market data becomes stale, order placement freezes.
**Why it happens:** Accidentally using sync libraries in async context. pybit is entirely synchronous.
**How to avoid:** Use ccxt async (not pybit). If any sync operation is unavoidable, wrap with `asyncio.to_thread()`. Use structlog's async-compatible context vars.
**Warning signs:** WebSocket heartbeat timeouts; increasing latency in order placement; "event loop blocked" warnings.

### Pitfall 4: Rate Limit Exhaustion During Critical Operations
**What goes wrong:** Bot burns through rate limits on market data polling, then cannot place orders during an emergency close.
**Why it happens:** Bybit rate limits are per-UID per-second (10-20/s for order operations). Polling prices via REST competes with order placement. Rate limit ban lasts 10+ minutes.
**How to avoid:** WebSocket for ALL market data (no REST polling for prices or funding rates). REST only for order placement and position queries. ccxt handles per-endpoint rate tracking. Keep 50% rate limit headroom.
**Warning signs:** HTTP 10006 errors ("Too many visits!"); X-Bapi-Limit-Status header approaching zero.

### Pitfall 5: Position Sizing Precision Errors
**What goes wrong:** Calculated position size doesn't match exchange constraints (lot size, tick size, min notional value). Order rejected.
**Why it happens:** Each symbol has different `minOrderQty`, `qtyStep`, `minNotionalValue`. Rounding independently for spot and perp causes mismatch.
**How to avoid:** Fetch instrument info via `/v5/market/instruments-info`. Round to `qtyStep` using Decimal quantize. Validate both spot and perp sizes use the same base quantity. Pre-validate before sending orders.
**Warning signs:** Order rejection errors with "invalid qty" or "lot size" messages.

### Pitfall 6: Stale Paper Trading Prices
**What goes wrong:** Paper executor uses cached price that's minutes old. Simulated P&L diverges from what real execution would produce.
**Why it happens:** Paper executor fetches price once and caches it, or uses price from a different moment than when the "order" was placed.
**How to avoid:** Paper executor must fetch the current market price (via WebSocket cache, not REST) at the moment of simulated execution. Simulate realistic slippage by applying a small spread.
**Warning signs:** Paper trading P&L looks unrealistically good; large discrepancy when comparing paper vs demo API results.

## Code Examples

Verified patterns from official sources:

### ccxt Async Bybit Initialization
```python
# Source: ccxt docs (https://docs.ccxt.com/) + PyPI ccxt 4.5.x
import ccxt.async_support as ccxt

exchange = ccxt.bybit({
    'apiKey': api_key,
    'secret': api_secret,
    'options': {
        'defaultType': 'swap',  # For perpetual operations
    },
    'enableRateLimit': True,  # ccxt manages rate limits
})

# For demo/paper trading via Bybit's demo API:
exchange_demo = ccxt.bybit({
    'apiKey': demo_api_key,
    'secret': demo_api_secret,
    'urls': {
        'api': {
            'public': 'https://api-demo.bybit.com',
            'private': 'https://api-demo.bybit.com',
        },
    },
    'enableRateLimit': True,
})
```

### Fetching All Perpetual Funding Rates
```python
# Source: Bybit V5 /v5/market/tickers (https://bybit-exchange.github.io/docs/v5/market/tickers)
async def fetch_all_funding_rates(exchange) -> list[dict]:
    """Fetch funding rates for all USDT perpetual pairs."""
    tickers = await exchange.fetch_tickers(params={'category': 'linear'})

    funding_data = []
    for symbol, ticker in tickers.items():
        info = ticker.get('info', {})
        funding_rate = info.get('fundingRate')
        if funding_rate is not None:
            funding_data.append({
                'symbol': symbol,
                'funding_rate': Decimal(str(funding_rate)),
                'next_funding_time': int(info.get('nextFundingTime', 0)),
                'funding_interval_hours': int(info.get('fundingIntervalHour', 8)),
                'mark_price': Decimal(str(ticker.get('last', 0))),
                'volume_24h': Decimal(str(info.get('volume24h', 0))),
            })

    return sorted(funding_data, key=lambda x: x['funding_rate'], reverse=True)
```

### Funding P&L Simulation (Paper Mode)
```python
# Source: Bybit funding fee formula (https://www.bybit.com/en/help-center/article/Funding-fee-calculation/)
# Funding Fee = Position Value * Funding Rate
# Position Value = Quantity * Mark Price
from decimal import Decimal

def calculate_funding_payment(
    position_qty: Decimal,
    mark_price: Decimal,
    funding_rate: Decimal,
    is_short: bool,
) -> Decimal:
    """
    Calculate funding payment for a position.

    Bybit convention: positive rate = longs pay shorts.
    If we are SHORT perp and rate is positive, we RECEIVE funding.
    """
    position_value = position_qty * mark_price
    raw_payment = position_value * funding_rate

    if is_short:
        # Short position: positive rate means we receive payment
        return raw_payment  # Positive = income
    else:
        # Long position: positive rate means we pay
        return -raw_payment  # Negative = expense
```

### Instrument Info for Position Sizing
```python
# Source: Bybit V5 /v5/market/instruments-info
async def get_lot_constraints(exchange, symbol: str) -> dict:
    """Fetch trading constraints for a symbol."""
    markets = await exchange.load_markets()
    market = markets.get(symbol)
    if not market:
        raise ValueError(f"Symbol {symbol} not found")

    return {
        'min_qty': Decimal(str(market['limits']['amount']['min'])),
        'max_qty': Decimal(str(market['limits']['amount']['max'])),
        'qty_step': Decimal(str(market['precision']['amount'])),
        'min_notional': Decimal(str(market['limits']['cost']['min'] or 0)),
        'tick_size': Decimal(str(market['precision']['price'])),
    }

def round_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round a value down to the nearest step increment."""
    return (value // step) * step
```

## Bybit API Reference (Phase 1 Endpoints)

### REST Endpoints Needed
| Endpoint | Method | Purpose | Rate Limit |
|----------|--------|---------|------------|
| `/v5/market/tickers?category=linear` | GET | All perpetual funding rates + prices | Public, 600/5s per IP |
| `/v5/market/instruments-info?category=linear` | GET | Lot sizes, tick sizes, constraints | Public, 600/5s per IP |
| `/v5/market/funding/history` | GET | Historical funding rates per symbol | Public, 600/5s per IP |
| `/v5/order/create` | POST | Place spot or perp order | 10-20/s per UID |
| `/v5/order/cancel` | POST | Cancel open order | 10-20/s per UID |
| `/v5/position/list?category=linear` | GET | Current perp positions | 50/s per UID |
| `/v5/account/wallet-balance` | GET | Account balance | 50/s per UID |

### WebSocket Topics Needed
| Topic | Stream | Purpose | Push Frequency |
|-------|--------|---------|----------------|
| `tickers.{symbol}` | `wss://stream.bybit.com/v5/public/linear` | Real-time funding rate + price | 100ms (derivatives) |
| `tickers.{symbol}` | `wss://stream.bybit.com/v5/public/spot` | Real-time spot price | 50ms |
| `position` | `wss://stream.bybit.com/v5/private` | Position updates (live mode) | Real-time |
| `order` | `wss://stream.bybit.com/v5/private` | Order fill notifications (live mode) | Real-time |
| `wallet` | `wss://stream.bybit.com/v5/private` | Balance updates (live mode) | Real-time |

### Authentication
- HMAC-SHA256 signature: `timestamp + apiKey + recvWindow + payload`
- Headers: `X-BAPI-API-KEY`, `X-BAPI-TIMESTAMP`, `X-BAPI-SIGN`, `X-BAPI-RECV-WINDOW`
- Timestamp must be within 5 seconds of server time
- ccxt handles all of this internally

### Bybit Demo Trading API
- REST: `https://api-demo.bybit.com` (same V5 endpoints)
- WebSocket: `wss://stream-demo.bybit.com` (private streams only; public data uses mainnet)
- Virtual funds via `/v5/account/demo-apply-money`: up to 15 BTC, 200 ETH, 100,000 USDT per request
- Orders expire after 7 days
- Same API key format as production (create from mainnet account's demo trading section)

## Bybit Fee Schedule (Verified February 2026)

| Fee Type | Maker | Taker | Notes |
|----------|-------|-------|-------|
| Spot trading | 0.100% | 0.100% | Base tier (Non-VIP) |
| USDT Perpetual | 0.020% | 0.055% | Base tier (Non-VIP) |
| Funding fee | N/A | N/A | Position Value * Funding Rate, settled every 8h |

**Fee implications for arbitrage profitability:**
- Opening: spot taker (0.1%) + perp taker (0.055%) = 0.155% total entry cost
- Closing: spot taker (0.1%) + perp taker (0.055%) = 0.155% total exit cost
- Total round-trip fee: ~0.31%
- Funding rate of 0.01%/8h = 0.03%/day = need ~10+ days to break even on fees alone
- Funding rate of 0.05%/8h = 0.15%/day = need ~2 days to break even
- **Minimum viable funding rate: ~0.03%/8h (0.09%/day) to break even within 3-4 days**

**Using maker orders can significantly reduce costs:**
- Opening with maker: spot maker (0.1%) + perp maker (0.02%) = 0.12% entry
- Total round-trip with maker: ~0.24%
- Break-even is ~20% faster with maker orders

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Bybit V3 API (separate spot/derivatives) | V5 Unified API (single endpoint for all) | 2023 | Single API for spot + perp. Use V5 exclusively. |
| pybit sync-only | ccxt async (ccxt 4.x) | ccxt 4.x release 2024 | Native async support, no thread executor workarounds |
| REST polling for market data | WebSocket streaming via ccxt Pro | Standard practice | 100ms updates vs seconds of latency, no rate limit impact |
| Standard Trading Account | Unified Trading Account (UTA) | 2023 | Spot + perp from same account, shared margin |
| Manual testnet for paper trading | Bybit Demo Trading API | 2024 | Production-grade paper trading with separate API domain |
| structlog threadlocal | structlog contextvars | structlog 21+ | Proper async context propagation |
| pydantic v1 Settings | pydantic-settings v2.12+ (separate package) | 2023 | Faster, cleaner API, SecretStr support |

**Deprecated/outdated:**
- Bybit API V1, V2, V3: All deprecated. Use V5 exclusively.
- pybit sync approach: Not suitable for async trading bots. Use ccxt async instead.
- `structlog.threadlocal`: Deprecated. Use `structlog.contextvars` for async.

## Open Questions

1. **ccxt Pro watch_tickers reliability for funding rate deltas**
   - What we know: ccxt Pro `watch_tickers()` streams via WebSocket. Funding rate is available in `ticker['info']['fundingRate']`.
   - What's unclear: Delta messages from Bybit may not always include fundingRate field (only changed fields sent). ccxt may or may not handle this correctly by merging with cached snapshot.
   - Recommendation: Test empirically during implementation. Implement REST fallback that refreshes full ticker data every 60 seconds as safety net. This is a LOW risk because funding rates change slowly (every 8 hours).

2. **Spot symbol naming convention in ccxt**
   - What we know: Perpetual symbols in ccxt use format `BTC/USDT:USDT`. Spot symbols use `BTC/USDT`.
   - What's unclear: Whether all perpetual pairs have matching spot pairs available for trading, and whether Bybit allows spot+perp in same UTA for all pairs.
   - Recommendation: During market scanning, validate that each perp pair has a corresponding spot pair. Filter out pairs without spot availability.

3. **Paper executor price source synchronization**
   - What we know: Paper executor needs current market prices for realistic simulation.
   - What's unclear: Best way to share WebSocket price cache between funding monitor and paper executor without tight coupling.
   - Recommendation: Use a shared in-memory price cache (dict with asyncio.Lock) that the funding monitor updates and the paper executor reads from. This avoids making separate REST calls for paper fills.

4. **Bybit Demo API limitations for integration testing**
   - What we know: Demo API supports most endpoints but "does not have a complete function compared with real trading." Orders expire after 7 days.
   - What's unclear: Whether Demo API accurately simulates funding fee settlement (does it actually credit/debit funding every 8h?).
   - Recommendation: Use Demo API for integration testing of order placement and position querying. Do NOT rely on it for funding fee simulation -- our paper executor must handle funding simulation independently.

## Sources

### Primary (HIGH confidence)
- [Bybit V5 API - Funding Rate History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) - Endpoint params, response format
- [Bybit V5 API - Rate Limits](https://bybit-exchange.github.io/docs/v5/rate-limit) - Per-UID limits, IP limits, WebSocket limits
- [Bybit V5 API - Get Tickers](https://bybit-exchange.github.io/docs/v5/market/tickers) - Funding rate fields in ticker response
- [Bybit V5 API - WebSocket Connect](https://bybit-exchange.github.io/docs/v5/ws/connect) - WebSocket URLs, auth, heartbeat
- [Bybit V5 API - WebSocket Ticker](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker) - Push frequency, snapshot/delta behavior
- [Bybit V5 API - Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order) - Order parameters, categories
- [Bybit V5 API - Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument) - Lot sizes, funding interval, price filters
- [Bybit V5 API - Demo Trading](https://bybit-exchange.github.io/docs/v5/demo) - Demo API domains, virtual funds, limitations
- [Bybit V5 API - Account Modes](https://bybit-exchange.github.io/docs/v5/acct-mode) - Unified Trading Account capabilities
- [Bybit Funding Fee Calculation](https://www.bybit.com/en/help-center/article/Funding-fee-calculation/) - Formula, sign convention, settlement times
- [Bybit Introduction to Funding Rate](https://www.bybit.com/en/help-center/article/Introduction-to-Funding-Rate) - Positive = longs pay shorts
- [pybit GitHub](https://github.com/bybit-exchange/pybit) - v5.14.0, sync-only, Feb 2026 release
- [pybit PyPI](https://pypi.org/project/pybit/) - v5.14.0, Python >=3.9.1
- [ccxt PyPI](https://pypi.org/project/ccxt/) - v4.5.37, Feb 2026, Bybit certified
- [ccxt Documentation](https://docs.ccxt.com/) - Async support, Bybit as certified exchange

### Secondary (MEDIUM confidence)
- [Bybit Trading Fee Structure](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure/) - Fee tiers verified via multiple sources
- [Bybit Trading Fees Page](https://www.bybit.com/en/announcement-info/fee-rate/) - Current fee schedule
- [All Bybit Fees (Feb 2026) - TradersUnion](https://tradersunion.com/brokers/crypto/view/bybit/fees/) - Third-party verification of fee rates
- [pydantic-settings PyPI](https://pypi.org/project/pydantic-settings/) - v2.12.0, Nov 2025
- [structlog PyPI](https://pypi.org/project/structlog/) - v25.5.0, Oct 2025
- [structlog Contextvars Guide](https://johal.in/structlog-contextvars-python-async-logging-2026/) - Async logging patterns
- [aiolimiter GitHub](https://github.com/mjpieters/aiolimiter) - v1.2.1, leaky bucket for asyncio
- [ccxt Pro Manual](https://github.com/ccxt/ccxt/wiki/ccxt.pro.manual) - WebSocket methods documentation

### Tertiary (LOW confidence)
- [ccxt Bybit Ticker Issue #22785](https://github.com/ccxt/ccxt/issues/22785) - Funding rate delta message inconsistency (needs empirical validation)
- Bybit Arbitrage Trading help article (403 - could not access, existence confirmed via search)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - ccxt 4.5.x verified on PyPI (Feb 2026), Bybit certified. pydantic-settings, structlog verified with current versions.
- Bybit API specifics: HIGH - Rate limits, endpoints, WebSocket specs, funding convention all verified against official V5 documentation.
- Fee structures: MEDIUM-HIGH - Verified via official Bybit help center + third-party sources. Base tier rates confirmed. VIP tiers not deeply explored (not needed for Phase 1).
- Architecture patterns: MEDIUM - Patterns are industry-standard for trading bots. ccxt async + executor pattern is well-established. Specific ccxt Pro WebSocket behavior for funding rate deltas needs empirical validation.
- Pitfalls: MEDIUM-HIGH - Core pitfalls (delta hedge, sign confusion, rate limits) verified against Bybit docs. Prevention strategies are sound but untested in this specific codebase.

**Research date:** 2026-02-11
**Valid until:** 2026-03-11 (30 days - APIs are stable, fee structures may change)
