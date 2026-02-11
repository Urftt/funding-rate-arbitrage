# Phase 2: Multi-Pair Intelligence - Research

**Researched:** 2026-02-11
**Domain:** Autonomous multi-pair scanning, opportunity ranking, risk management, emergency controls
**Confidence:** MEDIUM-HIGH

## Summary

Phase 2 transforms the Phase 1 monitor-only orchestrator into an autonomous trading engine that scans all Bybit perpetual pairs, ranks them by net yield after fees, and automatically opens/closes positions based on funding rate thresholds. The phase also builds comprehensive risk management: per-pair position limits, maximum simultaneous positions, margin ratio monitoring with alerts, and an emergency stop that immediately closes all open positions.

The existing Phase 1 codebase provides strong foundations: `FundingMonitor` already fetches all linear tickers and caches `FundingRateData` (including `volume_24h`, `interval_hours`), `PositionManager` handles delta-neutral open/close with rollback, and `RiskManager` is a stub explicitly awaiting Phase 2 expansion. The `Orchestrator._run_loop()` already reads profitable pairs but deliberately does not act on them. Phase 2's primary engineering challenge is the transition from passive monitoring to active position management with proper risk guardrails.

Bybit's V5 API provides all needed data: `GET /v5/account/wallet-balance` returns `accountMMRate` (maintenance margin ratio) and `totalMaintenanceMargin` at the account level, while `GET /v5/position/list` returns per-position `positionMM` and `positionIM`. The ccxt library exposes these via `fetch_balance()` (raw data in `balance['info']`) and `fetch_positions()`. For emergency close, Bybit supports `reduceOnly=true` with `qty="0"` to close entire positions, and `POST /v5/order/cancel-all` for bulk order cancellation.

**Primary recommendation:** Extend the existing `Orchestrator._run_loop()` with a scan-rank-decide-execute cycle. Build an `OpportunityRanker` that computes net yield after fees, a `RiskManager` that enforces all RISK-* requirements, and an `EmergencyController` that can atomically close all positions. Keep the existing component architecture (dependency injection, Executor ABC, TickerService cache) intact.

## Standard Stack

### Core (Already Installed -- No New Dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ccxt | >=4.5.0 | Bybit API (REST) for balance, positions, orders | Already in use from Phase 1. `fetch_balance()` returns margin data in `info` dict. |
| pydantic-settings | >=2.12 | New config sections for risk limits | Already in use. Extend with `RiskSettings` BaseSettings subclass. |
| structlog | >=25.5 | Structured logging for risk alerts | Already in use. Use `logger.warning()` for margin alerts. |
| asyncio | stdlib | Concurrent position close, signal handling | Already in use. Emergency close uses `asyncio.gather()`. |
| decimal | stdlib | All monetary/rate calculations | Already enforced project-wide. |

### Supporting (Already Installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest / pytest-asyncio | >=8.0 / >=0.23 | Testing scan/rank logic, risk checks | All new components need unit tests |
| ruff | >=0.4 | Linting new code | Continuous |

### No New Dependencies Required
Phase 2 uses only libraries already in `pyproject.toml`. The entire phase is algorithmic logic on top of existing infrastructure. No new packages needed.

## Architecture Patterns

### Recommended Module Structure (Extensions to Phase 1)
```
src/bot/
  config.py              # ADD: RiskSettings with env_prefix="RISK_"
  models.py              # ADD: OpportunityScore dataclass
  orchestrator.py         # MODIFY: Add autonomous trading loop
  exceptions.py           # ADD: RiskLimitExceeded, EmergencyStopTriggered
  market_data/
    opportunity_ranker.py  # NEW: Scores and ranks pairs by net yield
  risk/
    manager.py             # EXPAND: Per-pair limits, max positions, margin monitoring
    emergency.py           # NEW: Emergency stop controller
  exchange/
    client.py              # EXTEND: Add fetch_wallet_balance_raw, fetch_positions methods
```

### Pattern 1: Scan-Rank-Decide-Execute Cycle
**What:** Each orchestrator loop iteration follows a strict pipeline: scan all pairs, rank by net yield, filter through risk checks, then open/close positions.
**When to use:** Every main loop iteration.
**Why:** Separates concerns cleanly -- ranker is pure computation, risk manager is pure validation, orchestrator is coordination only.
```python
# In Orchestrator._run_loop() -- Phase 2 autonomous cycle
async def _autonomous_cycle(self) -> None:
    """One iteration of the autonomous trading loop."""
    # 1. SCAN: Get all funding rates from monitor cache
    all_rates = self._funding_monitor.get_all_funding_rates()

    # 2. RANK: Score each pair by net yield after fees
    opportunities = self._ranker.rank_opportunities(
        funding_rates=all_rates,
        fee_calculator=self._fee_calculator,
        min_rate=self._settings.trading.min_funding_rate,
    )

    # 3. DECIDE: Check which positions to open/close
    #    Close positions where rate dropped below exit threshold
    for position in self._position_manager.get_open_positions():
        rate_data = self._funding_monitor.get_funding_rate(position.perp_symbol)
        if rate_data is None or rate_data.rate < self._settings.risk.exit_funding_rate:
            await self._close_position_safely(position.id)

    #    Open new positions within risk limits
    for opp in opportunities:
        can_open, reason = self._risk_manager.check_can_open(
            symbol=opp.perp_symbol,
            position_size_usd=self._settings.trading.max_position_size_usd,
            current_positions=self._position_manager.get_open_positions(),
        )
        if can_open:
            await self._open_position_safely(opp.spot_symbol, opp.perp_symbol)

    # 4. MONITOR: Check margin ratio
    await self._check_margin_ratio()
```

### Pattern 2: Opportunity Scoring with Net Yield
**What:** Rank pairs by net annualized yield after round-trip fees, not raw funding rate. This accounts for different fee impacts on different-priced assets.
**When to use:** Every scan cycle to determine which pairs are worth trading.
```python
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class OpportunityScore:
    """Scored trading opportunity for a funding rate pair."""
    spot_symbol: str
    perp_symbol: str
    funding_rate: Decimal          # Raw 8h funding rate
    funding_interval_hours: int    # 4 or 8 (varies per symbol)
    volume_24h: Decimal            # 24h volume for liquidity filter
    net_yield_per_period: Decimal  # rate - (round_trip_fee / min_holding_periods)
    annualized_yield: Decimal      # net_yield_per_period * (periods_per_year)
    passes_filters: bool           # Volume, rate, spot-availability checks

class OpportunityRanker:
    """Ranks funding rate opportunities by net yield after fees."""

    def rank_opportunities(
        self,
        funding_rates: list[FundingRateData],
        fee_calculator: FeeCalculator,
        min_rate: Decimal,
        min_volume_24h: Decimal = Decimal("1000000"),  # $1M minimum
    ) -> list[OpportunityScore]:
        scored = []
        for fr in funding_rates:
            if fr.rate < min_rate:
                continue
            if fr.volume_24h < min_volume_24h:
                continue
            # Must have matching spot pair
            spot_symbol = self._derive_spot_symbol(fr.symbol)
            if spot_symbol is None:
                continue

            # Net yield = funding_rate - amortized_round_trip_fee
            # Amortized over minimum holding periods (e.g., 3 periods)
            round_trip_pct = fee_calculator.round_trip_fee_pct()
            amortized_fee = round_trip_pct / Decimal("3")
            net_yield = fr.rate - amortized_fee

            # Annualize: periods_per_year = 365 * 24 / interval_hours
            periods_per_year = Decimal("365") * Decimal("24") / Decimal(str(fr.interval_hours))
            annualized = net_yield * periods_per_year

            scored.append(OpportunityScore(
                spot_symbol=spot_symbol,
                perp_symbol=fr.symbol,
                funding_rate=fr.rate,
                funding_interval_hours=fr.interval_hours,
                volume_24h=fr.volume_24h,
                net_yield_per_period=net_yield,
                annualized_yield=annualized,
                passes_filters=net_yield > Decimal("0"),
            ))

        # Sort by annualized yield descending
        return sorted(scored, key=lambda x: x.annualized_yield, reverse=True)
```

### Pattern 3: Expanded Risk Manager
**What:** Pre-trade and ongoing risk checks: per-pair position limits, max simultaneous positions, margin ratio monitoring.
**When to use:** Before every position open and continuously during monitoring.
```python
class RiskManager:
    """Comprehensive risk management for Phase 2."""

    def __init__(self, settings: RiskSettings, exchange_client: ExchangeClient) -> None:
        self._settings = settings
        self._exchange_client = exchange_client

    def check_can_open(
        self,
        symbol: str,
        position_size_usd: Decimal,
        current_positions: list[Position],
    ) -> tuple[bool, str]:
        """Pre-trade risk check. Returns (allowed, reason)."""
        # RISK-01: Max position size per pair
        if position_size_usd > self._settings.max_position_size_per_pair:
            return False, f"Exceeds max per-pair size: {self._settings.max_position_size_per_pair}"

        # RISK-02: Max simultaneous positions
        if len(current_positions) >= self._settings.max_simultaneous_positions:
            return False, f"At max positions: {self._settings.max_simultaneous_positions}"

        # Check no duplicate pair
        open_symbols = {p.perp_symbol for p in current_positions}
        if symbol in open_symbols:
            return False, f"Already have position in {symbol}"

        return True, ""

    async def check_margin_ratio(self) -> tuple[Decimal, bool]:
        """RISK-05: Monitor margin ratio, return (ratio, is_alert)."""
        balance = await self._exchange_client.fetch_balance()
        raw = balance.get("info", {}).get("result", {}).get("list", [{}])[0]
        mm_rate = Decimal(str(raw.get("accountMMRate", "0")))
        is_alert = mm_rate > self._settings.margin_alert_threshold
        return mm_rate, is_alert
```

### Pattern 4: Emergency Stop Controller
**What:** Atomically close all open positions and cancel all pending orders when triggered by user signal or margin breach.
**When to use:** RISK-03 requirement -- user-triggered emergency stop.
```python
class EmergencyController:
    """Emergency stop: close all positions immediately."""

    def __init__(
        self,
        position_manager: PositionManager,
        orchestrator_stop_callback: Callable,
    ) -> None:
        self._position_manager = position_manager
        self._stop_callback = orchestrator_stop_callback
        self._triggered = False

    async def trigger(self, reason: str) -> list[str]:
        """Close all positions, stop the bot. Returns list of closed position IDs."""
        self._triggered = True
        logger.critical("emergency_stop_triggered", reason=reason)

        closed_ids = []
        open_positions = self._position_manager.get_open_positions()

        # Close all positions concurrently
        close_tasks = []
        for pos in open_positions:
            close_tasks.append(self._close_single(pos.id))

        results = await asyncio.gather(*close_tasks, return_exceptions=True)
        for pos, result in zip(open_positions, results):
            if isinstance(result, Exception):
                logger.error("emergency_close_failed", position_id=pos.id, error=str(result))
            else:
                closed_ids.append(pos.id)

        # Stop the orchestrator
        await self._stop_callback()
        return closed_ids
```

### Anti-Patterns to Avoid
- **Opening positions without risk checks:** Every position open MUST go through RiskManager.check_can_open() first. Never bypass risk checks.
- **Closing positions sequentially in emergency:** Use `asyncio.gather()` to close all positions concurrently. Sequential close leaves later positions exposed to market moves.
- **Using raw funding rate for ranking:** Always compute net yield after fees. A 0.05% funding rate on a pair with 0.31% round-trip fees is unprofitable short-term.
- **Ignoring funding interval differences:** Some Bybit pairs have 4h intervals, others 8h. The `fundingInterval` field (in minutes) from instruments-info must be used for correct annualization. The `FundingRateData.interval_hours` field already captures this.
- **Hardcoding risk thresholds:** All risk parameters must be configurable via environment variables using the existing pydantic-settings pattern.
- **Duplicate position on same pair:** Must check if a pair already has an open position before opening another.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Margin ratio calculation | Custom margin math from position data | Bybit API `accountMMRate` field from `GET /v5/account/wallet-balance` | Exchange calculates with exact liquidation engine logic; custom calc will diverge |
| Position close with reduce-only | Custom position tracking + reverse order | ccxt `create_order` with `params={'reduceOnly': True}` | Exchange enforces reduce-only semantics; prevents accidental position increase |
| Spot symbol derivation | Regex or string manipulation | ccxt `load_markets()` lookup: filter for `spot=True` with matching base/quote | Exchange metadata is authoritative; new pair formats won't break |
| Bulk order cancellation | Loop canceling one by one | Bybit `POST /v5/order/cancel-all` (via ccxt if available, else direct API) | Single API call, atomic, handles up to 500 orders |
| Funding rate annualization | Hardcoded `365 * 3` | Use `FundingRateData.interval_hours` to compute `periods_per_year = 8760 / interval_hours` | Intervals vary per symbol (4h, 8h); hardcoding produces wrong yields |

**Key insight:** The exchange is the source of truth for margin state. Never attempt to replicate the exchange's margin engine locally -- use the API fields (`accountMMRate`, `totalMaintenanceMargin`, `positionMM`) directly.

## Common Pitfalls

### Pitfall 1: Stale Margin Data Leading to False Safety
**What goes wrong:** Bot checks margin ratio, sees it's healthy, opens a new position. But the margin data was from 30+ seconds ago. The new position plus recent price movement pushes actual margin ratio past alert threshold or toward liquidation.
**Why it happens:** `fetch_balance()` is a REST snapshot, not real-time. Margin changes with every price tick when positions are open.
**How to avoid:** Always fetch fresh margin data immediately before opening a new position. Consider a margin buffer: if `accountMMRate` is within 2x of the alert threshold, refuse new positions. In Phase 2 with REST polling, add a `_last_margin_check` timestamp and enforce maximum staleness (e.g., 10 seconds).
**Warning signs:** Margin alerts firing immediately after opening a position; margin ratio oscillating near threshold.

### Pitfall 2: Race Condition in Position Count Check
**What goes wrong:** Two scan cycles run nearly simultaneously. Both check position count (e.g., 4 of max 5), both decide to open, result is 6 positions exceeding limit.
**Why it happens:** The orchestrator `_run_loop()` uses `asyncio.sleep()` which doesn't prevent overlapping cycles if one cycle takes longer than the interval.
**How to avoid:** The existing `PositionManager` already uses `asyncio.Lock` for open/close. Extend this pattern: the orchestrator's autonomous cycle should acquire a lock before the decide-execute phase. Alternatively, ensure only one cycle runs at a time by checking a `_cycle_running` flag.
**Warning signs:** Position count exceeding configured maximum; duplicate positions on the same pair.

### Pitfall 3: Emergency Close Partial Failure
**What goes wrong:** Emergency stop is triggered but one position fails to close (exchange error, rate limit, network issue). Bot stops monitoring but the position remains open and unmanaged.
**Why it happens:** `asyncio.gather()` with `return_exceptions=True` collects errors but doesn't retry. The bot shuts down after emergency, leaving failed positions orphaned.
**How to avoid:** Emergency close must retry failed positions (up to 3 attempts with exponential backoff). Log each failed position prominently as CRITICAL. After all retries, if positions remain, log the position details (symbol, quantity, side) so the user can manually close them.
**Warning signs:** Emergency stop completes but open positions remain in exchange account.

### Pitfall 4: Funding Rate Drops Between Scan and Execution
**What goes wrong:** Scan shows pair X at 0.05% funding rate. By the time the position opens (seconds later), the rate has already been adjusted or the next funding period is imminent with a lower predicted rate.
**Why it happens:** Funding rates on Bybit are calculated continuously but only settle every 4-8 hours. The displayed rate can change between scans.
**How to avoid:** Re-check the funding rate immediately before execution (from the cached data -- it's updated every 30s by FundingMonitor). Also check `next_funding_time`: if the next settlement is within 30 minutes, the current rate is about to be "consumed" and the next rate may differ. Consider skipping positions where settlement is imminent unless the rate has been stable across multiple scans.
**Warning signs:** Positions opened just before funding settlement; first funding payment significantly different from expected rate.

### Pitfall 5: Not Filtering Pre-Market / Low-Liquidity Pairs
**What goes wrong:** Bot opens a position on a pre-market perpetual pair that has no corresponding spot market. The spot buy leg fails or fills at a wildly different price.
**Why it happens:** Bybit has "Pre-Market Perpetual" contracts that trade before spot listing. These show up in the linear tickers but have no spot pair.
**How to avoid:** Before scoring any pair, verify that a matching spot symbol exists in `exchange.load_markets()`. Also enforce a minimum 24h volume threshold (e.g., $1M USD) to avoid illiquid pairs where slippage would destroy profitability.
**Warning signs:** `InstrumentInfo` lookup failing for spot symbol; unusually wide spreads in paper executor fills.

### Pitfall 6: Funding Interval Mismatch in Yield Calculation
**What goes wrong:** Bot assumes all pairs have 8h funding intervals. A pair with 4h intervals appears to have half the yield it actually has (or vice versa: an 8h pair appears twice as profitable when compared to a 4h pair at the same rate).
**Why it happens:** Different Bybit pairs have different funding intervals (commonly 4h or 8h). The `fundingIntervalHour` field varies per symbol.
**How to avoid:** Always use `FundingRateData.interval_hours` (already populated by FundingMonitor from `info.get('fundingIntervalHour', 8)`) in yield calculations. Annualize as: `rate * (8760 / interval_hours)`.
**Warning signs:** Pairs with identical funding rates showing different annualized yields (this is correct behavior if intervals differ).

## Code Examples

### Extending ExchangeClient for Margin Data
```python
# Add to ExchangeClient ABC (exchange/client.py)
@abstractmethod
async def fetch_wallet_balance_raw(self) -> dict:
    """Fetch raw wallet balance including margin fields.

    Returns the raw Bybit response dict with:
    - accountMMRate: Maintenance margin ratio
    - totalMaintenanceMargin: Total MM in USD
    - totalEquity: Total account equity in USD
    - totalAvailableBalance: Available for new positions
    """
    ...

# Implementation in BybitClient (exchange/bybit_client.py)
async def fetch_wallet_balance_raw(self) -> dict:
    """Fetch raw wallet balance for margin monitoring."""
    balance = await self._exchange.fetch_balance(params={"type": "UNIFIED"})
    raw_info = balance.get("info", {})
    result_list = raw_info.get("result", {}).get("list", [])
    if result_list:
        return result_list[0]
    return {}
```

### RiskSettings Configuration
```python
# Add to config.py
class RiskSettings(BaseSettings):
    """Risk management parameters for Phase 2."""

    model_config = SettingsConfigDict(env_prefix="RISK_")

    max_position_size_per_pair: Decimal = Decimal("1000")  # USD
    max_simultaneous_positions: int = 5
    exit_funding_rate: Decimal = Decimal("0.0001")  # 0.01% -- close below this
    margin_alert_threshold: Decimal = Decimal("0.8")  # Alert at 80% MMR
    margin_critical_threshold: Decimal = Decimal("0.9")  # Emergency at 90% MMR
    min_volume_24h: Decimal = Decimal("1000000")  # $1M minimum volume
    min_holding_periods: int = 3  # Minimum funding periods to hold
```

### Emergency Close All Positions
```python
# Source: Bybit V5 order API + ccxt patterns
async def emergency_close_all(
    position_manager: PositionManager,
    logger: BoundLogger,
) -> tuple[list[str], list[str]]:
    """Close all open positions concurrently.

    Returns:
        Tuple of (successfully_closed_ids, failed_ids).
    """
    open_positions = position_manager.get_open_positions()
    if not open_positions:
        logger.info("emergency_close_no_positions")
        return [], []

    closed = []
    failed = []

    async def close_with_retry(position_id: str, max_retries: int = 3) -> bool:
        for attempt in range(max_retries):
            try:
                await position_manager.close_position(position_id)
                return True
            except Exception as e:
                logger.error(
                    "emergency_close_attempt_failed",
                    position_id=position_id,
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))  # Backoff
        return False

    results = await asyncio.gather(
        *[close_with_retry(p.id) for p in open_positions],
        return_exceptions=True,
    )

    for pos, result in zip(open_positions, results):
        if result is True:
            closed.append(pos.id)
        else:
            failed.append(pos.id)
            logger.critical(
                "emergency_close_position_stuck",
                position_id=pos.id,
                symbol=pos.perp_symbol,
                quantity=str(pos.quantity),
            )

    return closed, failed
```

### Deriving Spot Symbol from Perp Symbol
```python
# Source: ccxt market data structure
def derive_spot_symbol(perp_symbol: str, markets: dict) -> str | None:
    """Derive the matching spot symbol for a perpetual symbol.

    Args:
        perp_symbol: e.g., "BTC/USDT:USDT"
        markets: ccxt markets dict from load_markets()

    Returns:
        Spot symbol (e.g., "BTC/USDT") or None if not available.
    """
    # ccxt perp format: "BTC/USDT:USDT" -> base="BTC", quote="USDT"
    market = markets.get(perp_symbol)
    if market is None:
        return None

    base = market.get("base")
    quote = market.get("quote")
    if not base or not quote:
        return None

    spot_symbol = f"{base}/{quote}"
    spot_market = markets.get(spot_symbol)

    if spot_market is None:
        return None
    if not spot_market.get("spot", False):
        return None
    if not spot_market.get("active", False):
        return None

    return spot_symbol
```

### Signal-Based Emergency Stop
```python
# Extend main.py signal handler for RISK-03
import signal
import asyncio

def setup_emergency_signals(
    loop: asyncio.AbstractEventLoop,
    emergency_controller: EmergencyController,
    orchestrator: Orchestrator,
) -> None:
    """Register SIGUSR1 for emergency stop, keep SIGINT/SIGTERM for graceful."""

    def _graceful_handler() -> None:
        logger.info("graceful_shutdown_signal")
        asyncio.create_task(orchestrator.stop())

    def _emergency_handler() -> None:
        logger.critical("emergency_stop_signal_received")
        asyncio.create_task(emergency_controller.trigger("user_signal"))

    # SIGINT/SIGTERM = graceful (finish current cycle, close positions cleanly)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _graceful_handler)

    # SIGUSR1 = emergency stop (immediate close all)
    loop.add_signal_handler(signal.SIGUSR1, _emergency_handler)
```

## Bybit API Endpoints (Phase 2 Additions)

### REST Endpoints Needed (Beyond Phase 1)
| Endpoint | Method | Purpose | Rate Limit | Phase 2 Requirement |
|----------|--------|---------|------------|---------------------|
| `/v5/account/wallet-balance?accountType=UNIFIED` | GET | Margin ratio monitoring (`accountMMRate`, `totalMaintenanceMargin`) | 50/s per UID | RISK-05 |
| `/v5/position/list?category=linear` | GET | Verify actual exchange positions match local state | 50/s per UID | Cross-validation |
| `/v5/order/cancel-all` | POST | Emergency: cancel all pending orders | Spot: no limit, Futures: max 500 | RISK-03 |
| `/v5/market/instruments-info?category=linear` | GET | Get `fundingInterval` per symbol, spot pair availability | Public, 600/5s per IP | MKTD-02 |

### Key Response Fields for Margin Monitoring
```json
// GET /v5/account/wallet-balance response (account-level fields)
{
  "accountMMRate": "0.0123",          // Maintenance margin rate (RISK-05)
  "accountIMRate": "0.0456",          // Initial margin rate
  "totalMaintenanceMargin": "12.34",  // Total MM in USD
  "totalInitialMargin": "45.67",      // Total IM in USD
  "totalEquity": "1000.00",           // Total equity in USD
  "totalAvailableBalance": "900.00",  // Available for new positions
  "totalMarginBalance": "950.00"      // Wallet + unrealized PnL
}
```

## Configuration Design

### New Environment Variables (Phase 2)
```bash
# Risk management (RISK-01, RISK-02, RISK-03, RISK-05)
RISK_MAX_POSITION_SIZE_PER_PAIR=1000      # USD per pair (RISK-01)
RISK_MAX_SIMULTANEOUS_POSITIONS=5          # Max open positions (RISK-02)
RISK_EXIT_FUNDING_RATE=0.0001             # Close below 0.01%/period (EXEC-02)
RISK_MARGIN_ALERT_THRESHOLD=0.8           # Alert at 80% MMR (RISK-05)
RISK_MARGIN_CRITICAL_THRESHOLD=0.9        # Emergency at 90% MMR (RISK-05)
RISK_MIN_VOLUME_24H=1000000              # $1M minimum volume filter

# Trading (extend existing TRADING_ prefix)
TRADING_SCAN_INTERVAL=60                  # Seconds between scan cycles
TRADING_MIN_HOLDING_PERIODS=3             # Minimum funding periods before considering exit
```

### AppSettings Extension
```python
class AppSettings(BaseSettings):
    # ... existing fields ...
    risk: RiskSettings = RiskSettings()  # ADD to existing AppSettings
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-pair monitoring | Multi-pair autonomous scanning | Phase 2 | Scans all pairs, ranks by net yield, opens best opportunities |
| Manual position open/close | Threshold-based automatic open/close | Phase 2 | Opens when rate > min_threshold, closes when rate < exit_threshold |
| No risk limits | Per-pair and portfolio-level limits | Phase 2 | Prevents over-concentration and excessive exposure |
| No margin monitoring | Real-time margin ratio alerting | Phase 2 | Uses Bybit `accountMMRate` from wallet-balance API |
| No emergency stop | Signal-based emergency close | Phase 2 | SIGUSR1 triggers immediate close of all positions |

## Open Questions

1. **Graceful vs. emergency shutdown semantics**
   - What we know: SIGINT/SIGTERM already trigger `orchestrator.stop()`. Phase 2 needs an additional "emergency close all" path.
   - What's unclear: Should graceful shutdown also close all positions, or only stop new trading? Should SIGINT send emergency close on second signal?
   - Recommendation: First SIGINT/SIGTERM = stop opening new positions and close all positions gracefully (one by one with P&L recording). SIGUSR1 = emergency (close all concurrently, no P&L, just get out). Second SIGINT = force exit.

2. **Paper mode margin simulation**
   - What we know: Paper executor simulates order fills. But `fetch_balance()` with `accountMMRate` requires a real exchange connection.
   - What's unclear: How to simulate margin ratio in paper mode without exchange data.
   - Recommendation: For paper mode, simulate margin ratio based on position count * max_position_size vs. a configured virtual equity. This is a rough approximation but sufficient for testing the monitoring logic. Set `paper_virtual_equity` config parameter.

3. **Position allocation strategy**
   - What we know: Multiple pairs may pass all filters simultaneously. Need to decide how to allocate capital.
   - What's unclear: Should the bot open positions on all qualifying pairs up to max_positions? Or prioritize top-N by yield?
   - Recommendation: Open positions top-down by annualized yield until max_simultaneous_positions is reached. Each position gets `max_position_size_per_pair` allocation. Simple, predictable, easy to reason about.

4. **Rate stability check before entry**
   - What we know: Funding rates can be volatile, especially during market events.
   - What's unclear: Should the bot require a rate to be above threshold for multiple consecutive scans before entering?
   - Recommendation: For Phase 2, require the rate to be above `min_funding_rate` in the current scan only. Rate stability (e.g., "above threshold for last 3 scans") is a Phase 3 enhancement. Keep Phase 2 simple and functional.

5. **ccxt access to raw Bybit margin fields**
   - What we know: ccxt's `fetch_balance()` returns parsed data that may not include `accountMMRate`. The raw data is accessible via `balance['info']['result']['list'][0]`.
   - What's unclear: Whether future ccxt versions will properly parse these fields into the unified balance structure.
   - Recommendation: Access margin data through the raw `info` dict. This is reliable because it's the raw Bybit API response. Wrap this in a dedicated method (`fetch_wallet_balance_raw()`) to isolate the raw access pattern.

## Sources

### Primary (HIGH confidence)
- [Bybit V5 - Get Wallet Balance](https://bybit-exchange.github.io/docs/v5/account/wallet-balance) - `accountMMRate`, `totalMaintenanceMargin`, `totalAvailableBalance` fields verified
- [Bybit V5 - Get Position Info](https://bybit-exchange.github.io/docs/v5/position) - `positionMM`, `positionIM`, `liqPrice` fields verified
- [Bybit V5 - Get Account Info](https://bybit-exchange.github.io/docs/v5/account/account-info) - `marginMode` field, account mode types
- [Bybit V5 - Cancel All Orders](https://bybit-exchange.github.io/docs/v5/order/cancel-all) - Bulk cancel endpoint, 500 order limit for futures
- [Bybit V5 - Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order) - `reduceOnly`, `closeOnTrigger` params, `qty="0"` for full close
- [Bybit V5 - Get Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument) - `fundingInterval` field (in minutes), pagination, `isPreListing`
- [Bybit V5 - Funding Rate History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) - Historical rate endpoint, 200 record limit
- [Bybit Introduction to Funding Rate](https://www.bybit.com/en/help-center/article/Introduction-to-Funding-Rate) - Settlement intervals (generally 8h, may vary), positive = longs pay shorts
- [Bybit Funding Fee Calculation](https://www.bybit.com/en/help-center/article/Funding-fee-calculation/) - Formula: Position Value * Funding Rate

### Secondary (MEDIUM confidence)
- [ccxt GitHub - Bybit position/margin issues](https://github.com/ccxt/ccxt/issues/27079) - `positionIM` parsing issue, raw `info` access confirmed as workaround
- [ccxt GitHub - fetch_balance unified account](https://github.com/ccxt/ccxt/issues/24878) - Raw balance data access via `balance['info']`
- [ccxt GitHub - close position with reduce_only](https://github.com/ccxt/ccxt/issues/14385) - `params={'reduceOnly': True}` confirmed working
- [CoinGlass - What is Funding Rate Arbitrage](https://www.coinglass.com/learn/what-is-funding-rate-arbitrage) - Net yield calculation, annualization formula
- [Gate.com - Funding Rate Arbitrage Strategy](https://www.gate.com/learn/articles/perpetual-contract-funding-rate-arbitrage/2166) - Risk management guidelines, leverage recommendations

### Tertiary (LOW confidence)
- [Bybit Adjustment of Funding Rate Interval](https://announcements.bybit.com/en/article/adjustment-of-funding-rate-interval-upper-and-lower-limit-of-funding-rate-for-bnxusdt-perpetual-contracts-blt820357765a9c3028/) - Example of per-symbol interval changes (confirms intervals are not static)
- Open-source funding rate arbitrage projects on GitHub (aoki-h-jp, kir1l, hamood1337) - Pattern reference only, not used for technical decisions

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new dependencies needed. All extensions use existing libraries already verified in Phase 1.
- Architecture patterns: HIGH - Extensions follow Phase 1's established patterns (dependency injection, Executor ABC, pydantic-settings). New components fit naturally into existing module structure.
- Bybit API specifics: HIGH - Wallet balance, position info, and order endpoints verified against official V5 documentation. Response field names confirmed.
- Risk management: MEDIUM-HIGH - Risk patterns are industry-standard. Margin monitoring via `accountMMRate` is verified. Paper mode margin simulation is an approximation (flagged in Open Questions).
- Pitfalls: MEDIUM-HIGH - Core pitfalls (stale margin, race conditions, emergency partial failure) are derived from analyzing the existing codebase and exchange API behavior. Prevention strategies are sound but untested.
- ccxt margin data access: MEDIUM - Raw `info` dict access is confirmed working by multiple GitHub issues, but proper unified parsing may change in future versions.

**Research date:** 2026-02-11
**Valid until:** 2026-03-11 (30 days - Bybit API is stable, fee/margin structures unlikely to change)
