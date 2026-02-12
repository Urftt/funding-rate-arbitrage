# Phase 7: Dynamic Position Sizing - Research

**Researched:** 2026-02-12
**Domain:** Dynamic position sizing, portfolio exposure management, signal-conviction-based allocation
**Confidence:** HIGH

## Summary

This phase adds dynamic position sizing that scales allocations based on composite signal conviction, constrained by a portfolio-level exposure cap. The current system uses a static `max_position_size_usd` for every position regardless of signal quality. Phase 7 replaces this with a `DynamicSizer` that maps composite signal scores (0-1 range, from Phase 5's SignalEngine) to position sizes within a configurable range (e.g., 30%-100% of max per-pair allocation), then validates that total portfolio exposure across all open positions does not exceed a configurable cap. Critically, SIZE-03 mandates that the DynamicSizer delegates to the existing `PositionSizer` for all exchange constraint validation (qty_step rounding, min_qty, min_notional checks) -- no duplicate logic.

The architectural challenge is integration, not algorithm complexity. The sizing formula itself is a simple linear or clamped mapping from score to allocation fraction. The complexity lies in: (1) wiring the DynamicSizer into the orchestrator's position-opening flow where the signal score is available, (2) computing remaining portfolio budget by summing existing position exposures, (3) preserving the v1.0 simple-mode path where dynamic sizing is irrelevant (static sizing remains default), and (4) integrating with the backtest engine which currently uses `initial_capital` as a fixed `max_position_size_usd`.

No external libraries are needed. All computations use Python's `Decimal` type and the existing `PositionSizer` for constraint validation. The DynamicSizer is a new class in `src/bot/position/dynamic_sizer.py` that composes (wraps) the existing `PositionSizer`, computing a signal-adjusted USD budget then delegating to `PositionSizer.calculate_matching_quantity()` for exchange-level validation.

**Primary recommendation:** Create a `DynamicSizer` class that takes a composite signal score and portfolio state, computes a signal-scaled USD budget, passes it to the existing `PositionSizer` as the effective `max_position_size_usd` (via a modified available_balance cap), and enforce a portfolio-wide exposure cap in the orchestrator before calling `open_position`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `decimal` | stdlib | All sizing computations | Already used throughout codebase; Decimal precision required per project convention |
| `pydantic-settings` | >=2.12 (already installed) | DynamicSizingSettings config | Already used for all config classes in config.py |
| `structlog` | >=25.5 (already installed) | Logging sizing decisions | Already used throughout for structured logging |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `bot.position.sizing.PositionSizer` | existing | Exchange constraint validation (qty_step, min_qty, min_notional) | Delegated to by DynamicSizer for all constraint checks |
| `bot.signals.models.CompositeSignal` | existing | Signal score source (0-1 range) | Input to DynamicSizer for conviction-based scaling |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Linear score-to-size mapping | Kelly criterion / sophisticated allocation | Over-engineered for v1.1; Kelly requires accurate win probability estimates we don't have yet. Linear is transparent and testable. |
| DynamicSizer wrapper class | Modifying PositionSizer directly | Would break v1.0 path; violates SIZE-03 (existing PositionSizer for constraint validation); new class composes existing one |
| Portfolio exposure cap in DynamicSizer | Portfolio exposure in RiskManager | RiskManager already does pre-trade checks; exposure cap is conceptually a sizing constraint, but implementation can live in either. Best to keep portfolio math in DynamicSizer and let RiskManager handle its existing checks. |

**Installation:**
No new packages needed. All dependencies already in `pyproject.toml`.

## Architecture Patterns

### Recommended Project Structure
```
src/bot/
├── position/
│   ├── __init__.py              # UNCHANGED
│   ├── sizing.py                # UNCHANGED (existing PositionSizer)
│   ├── dynamic_sizer.py         # NEW: DynamicSizer (SIZE-01, SIZE-02, SIZE-03)
│   ├── delta_validator.py       # UNCHANGED
│   └── manager.py               # UNCHANGED (PositionManager)
├── config.py                    # MODIFIED: Add DynamicSizingSettings
├── orchestrator.py              # MODIFIED: Wire DynamicSizer into open flow
├── main.py                      # MODIFIED: Create and inject DynamicSizer
└── backtest/
    └── engine.py                # MODIFIED: Use DynamicSizer in composite mode
```

### Pattern 1: DynamicSizer Wrapping PositionSizer (Delegation Pattern)
**What:** DynamicSizer computes a signal-adjusted USD budget, then delegates to the existing PositionSizer for quantity calculation and exchange constraint validation. This satisfies SIZE-03: "delegates to existing PositionSizer for exchange constraint validation -- no duplicate logic."
**When to use:** Every position open in composite strategy mode.
**Example:**
```python
# Source: Derived from existing codebase patterns
from decimal import Decimal
from bot.position.sizing import PositionSizer
from bot.config import DynamicSizingSettings

class DynamicSizer:
    """Signal-conviction-based position sizer with portfolio exposure cap.

    Wraps the existing PositionSizer, computing a signal-scaled USD budget
    before delegating to PositionSizer for exchange constraint validation.

    SIZE-01: Position size scales with signal confidence.
    SIZE-02: Total portfolio exposure capped at configurable limit.
    SIZE-03: Delegates to PositionSizer for qty_step, min_qty, min_notional.
    """

    def __init__(
        self,
        position_sizer: PositionSizer,
        settings: DynamicSizingSettings,
    ) -> None:
        self._sizer = position_sizer
        self._settings = settings

    def compute_signal_budget(
        self,
        signal_score: Decimal,
        current_exposure: Decimal,
    ) -> Decimal | None:
        """Compute USD budget for a new position based on signal score.

        1. Map signal score to allocation fraction:
           fraction = min_fraction + (max_fraction - min_fraction) * score
        2. Compute raw_budget = max_position_size_usd * fraction
        3. Cap by remaining portfolio budget:
           remaining = max_portfolio_exposure - current_exposure
        4. Return min(raw_budget, remaining), or None if no room

        Args:
            signal_score: Composite signal score in [0, 1] range.
            current_exposure: Sum of all open position notional values in USD.

        Returns:
            USD budget for the position, or None if portfolio cap reached.
        """
        # 1. Map score to fraction
        fraction = (
            self._settings.min_allocation_fraction
            + (self._settings.max_allocation_fraction
               - self._settings.min_allocation_fraction)
            * signal_score
        )

        # 2. Raw budget
        raw_budget = self._settings.max_position_size_usd * fraction

        # 3. Portfolio cap
        remaining = self._settings.max_portfolio_exposure - current_exposure
        if remaining <= Decimal("0"):
            return None

        # 4. Effective budget
        return min(raw_budget, remaining)

    def calculate_matching_quantity(
        self,
        signal_score: Decimal,
        current_exposure: Decimal,
        price: Decimal,
        available_balance: Decimal,
        spot_instrument: "InstrumentInfo",
        perp_instrument: "InstrumentInfo",
    ) -> Decimal | None:
        """Full flow: compute budget then delegate to PositionSizer.

        Args:
            signal_score: Composite signal score in [0, 1].
            current_exposure: Current total portfolio exposure in USD.
            price: Current asset price.
            available_balance: Available balance in quote currency.
            spot_instrument: Spot instrument constraints.
            perp_instrument: Perp instrument constraints.

        Returns:
            Valid quantity for both legs, or None if constraints not met.
        """
        budget = self.compute_signal_budget(signal_score, current_exposure)
        if budget is None:
            return None

        # Cap available_balance by the signal-adjusted budget
        effective_balance = min(available_balance, budget)

        # Delegate to PositionSizer for exchange constraint validation
        # We pass effective_balance as the balance and let PositionSizer
        # apply its own max_position_size_usd cap (which is the per-pair max).
        # The signal-adjusted budget is already <= max_position_size_usd.
        return self._sizer.calculate_matching_quantity(
            price=price,
            available_balance=effective_balance,
            spot_instrument=spot_instrument,
            perp_instrument=perp_instrument,
        )
```

### Pattern 2: Portfolio Exposure Computation
**What:** Sum the notional value of all open positions to compute current portfolio exposure. This is needed for SIZE-02 (portfolio cap).
**When to use:** Before each position open decision in the orchestrator.
**Example:**
```python
def compute_current_exposure(
    open_positions: list["Position"],
    ticker_service: "TickerService",
) -> Decimal:
    """Sum current notional value of all open positions.

    Uses entry price as proxy (actual mark price would require async fetch).
    For funding rate arb, spot + perp entry prices are close enough.

    Args:
        open_positions: List of currently open positions.
        ticker_service: Not used in simple version (use entry price).

    Returns:
        Total exposure in USD (sum of quantity * entry_price for each position).
    """
    total = Decimal("0")
    for pos in open_positions:
        # Use perp entry price as the notional reference
        total += pos.quantity * pos.perp_entry_price
    return total
```

### Pattern 3: DynamicSizingSettings Configuration
**What:** A new pydantic-settings class with SIZING_ env prefix, following the established pattern.
**When to use:** Configuring the DynamicSizer.
**Example:**
```python
class DynamicSizingSettings(BaseSettings):
    """Dynamic position sizing configuration.

    Controls how signal conviction maps to position size and
    the portfolio-level exposure cap.
    """
    model_config = SettingsConfigDict(env_prefix="SIZING_")

    enabled: bool = False  # Default off (v1.0 behavior preserved)
    max_position_size_usd: Decimal = Decimal("1000")  # Max per-pair (100% allocation)
    min_allocation_fraction: Decimal = Decimal("0.3")  # Weakest signal -> 30% of max
    max_allocation_fraction: Decimal = Decimal("1.0")  # Strongest signal -> 100% of max
    max_portfolio_exposure: Decimal = Decimal("5000")  # Total exposure cap across all positions
```

### Pattern 4: Optional Injection (v1.1 Convention)
**What:** The DynamicSizer is injected into the orchestrator as `| None = None`, consistent with the Phase 4/5 pattern for `HistoricalDataFetcher`, `HistoricalDataStore`, and `SignalEngine`.
**When to use:** When dynamic sizing is enabled.
**Example:**
```python
class Orchestrator:
    def __init__(
        self,
        # ... existing params ...
        dynamic_sizer: DynamicSizer | None = None,  # NEW: v1.1 dynamic sizing
    ) -> None:
        self._dynamic_sizer = dynamic_sizer
```

### Pattern 5: Orchestrator Integration -- Signal Score Pass-Through
**What:** In composite mode, the orchestrator already has the `CompositeOpportunityScore` (which contains `signal.score`). When dynamic sizing is enabled, pass this score to the DynamicSizer instead of using the static `max_position_size_usd`.
**When to use:** In `_open_profitable_positions_composite()`.
**Key insight:** The current orchestrator flow calls `self.open_position(opp.spot_symbol, opp.perp_symbol)` which does NOT pass a signal score. The integration must thread the score through to the sizing layer.

**Two integration approaches:**

**Approach A -- Orchestrator computes budget, passes as available_balance override:**
The orchestrator calls `dynamic_sizer.compute_signal_budget(score, exposure)`, then passes the result as the `available_balance` argument to `open_position()`. The existing `PositionSizer` inside `PositionManager` then handles exchange constraints. This requires minimal changes to `PositionManager`.

**Approach B -- DynamicSizer replaces PositionSizer inside PositionManager:**
Inject the DynamicSizer into PositionManager and have it call `dynamic_sizer.calculate_matching_quantity()` instead of `position_sizer.calculate_matching_quantity()`. This requires PositionManager to accept a signal score parameter.

**Recommendation: Approach A.** It requires fewer changes to existing classes, keeps signal concerns out of PositionManager (which is exchange-level), and is simpler to test. The orchestrator already fetches balance and instruments -- it just needs to also compute the effective budget from the signal score.

### Anti-Patterns to Avoid
- **Modifying PositionSizer directly:** Violates SIZE-03. The existing PositionSizer is the exchange constraint validator. Dynamic sizing is a layer above it.
- **Duplicating qty_step/min_qty/min_notional checks in DynamicSizer:** The whole point of SIZE-03 is delegation. DynamicSizer computes USD budget; PositionSizer validates exchange constraints.
- **Hardcoding the score-to-size formula:** Must be configurable for backtesting parameter sweeps.
- **Using float for any sizing computation:** Breaks the project's Decimal convention.
- **Forgetting the portfolio exposure check when multiple positions open in the same cycle:** The orchestrator iterates over multiple opportunities. Each new position opened reduces remaining portfolio budget.
- **Making dynamic sizing mandatory:** Must be opt-in (`enabled: bool = False`). When disabled, existing static sizing (`max_position_size_usd`) is used unchanged. This preserves v1.0 behavior and `strategy_mode: simple`.
- **Ignoring the backtest engine integration:** The BacktestEngine currently sets `max_position_size_usd = initial_capital` and uses static sizing. Dynamic sizing in composite backtest mode should be possible.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exchange constraint validation | qty_step rounding, min_qty checks in DynamicSizer | `PositionSizer.calculate_matching_quantity()` | SIZE-03 mandate; existing PositionSizer already handles all edge cases |
| Configuration management | Manual env var parsing | `pydantic-settings` with `DynamicSizingSettings` | Already used for all other config; provides validation, env loading |
| Portfolio exposure tracking | Separate exposure tracking service | Simple sum of `pos.quantity * pos.perp_entry_price` from `get_open_positions()` | Positions are already tracked in PositionManager; just sum them |
| Score normalization | Re-implementing score clamping | `CompositeSignal.score` is already 0-1 range from Phase 5 | Signal engine already normalizes and quantizes scores |

**Key insight:** The DynamicSizer is thin. It maps a score to a budget and delegates. The existing PositionSizer handles the hard part (exchange constraints). The existing SignalEngine handles the other hard part (score computation). Phase 7 connects them.

## Common Pitfalls

### Pitfall 1: Portfolio Exposure Drifting from Entry Prices
**What goes wrong:** Using entry prices for exposure calculation means the exposure estimate becomes stale as prices move. A position opened at $50,000 BTC could be worth $60,000 or $40,000.
**Why it happens:** Mark-to-market exposure requires current prices (async fetch), but entry prices are available synchronously.
**How to avoid:** For v1.1, use entry prices. This is acceptable because: (a) funding rate arb positions are delta-neutral, so price movement risk is hedged, (b) the exposure cap is a safety constraint, not precise accounting, (c) the alternative (fetching live prices for all positions on every cycle) adds latency and complexity. Document this simplification and consider mark-to-market for v1.2.
**Warning signs:** If large price movements cause the portfolio to significantly exceed the intended exposure cap despite the limit.

### Pitfall 2: Race Condition When Opening Multiple Positions per Cycle
**What goes wrong:** The orchestrator iterates over multiple high-scoring opportunities in a single cycle. If it opens three positions without updating `current_exposure` between opens, the portfolio cap is not enforced correctly.
**Why it happens:** The exposure is computed once at the start of the iteration, not updated after each successful open.
**How to avoid:** Recompute `current_exposure` after each successful position open within the same cycle. Alternatively, pre-allocate budget across all qualifying opportunities before opening any.
**Warning signs:** Portfolio exposure exceeding `max_portfolio_exposure` after a cycle where multiple positions opened.

### Pitfall 3: Minimum Allocation Producing Below-Minimum Positions
**What goes wrong:** A weak signal (score=0.1) with `min_allocation_fraction=0.3` could produce a budget of $300 (30% of $1000). At a high BTC price, this might produce a quantity below `min_qty` or `min_notional`.
**Why it happens:** The DynamicSizer computes a smaller budget, which when converted to quantity, falls below exchange minimums.
**How to avoid:** This is handled correctly by delegation to PositionSizer -- it returns `None` when constraints aren't met. The orchestrator already handles `None` (logs "insufficient size" and skips). No special handling needed in DynamicSizer.
**Warning signs:** Many "insufficient size" rejections for weak-signal pairs. This is expected behavior, not a bug.

### Pitfall 4: Dynamic Sizing Without Composite Signals
**What goes wrong:** Dynamic sizing is enabled but `strategy_mode` is `"simple"`, meaning there are no composite signal scores available to feed into DynamicSizer.
**Why it happens:** The simple path uses `OpportunityRanker` which produces `OpportunityScore` (no `.signal.score` field).
**How to avoid:** Dynamic sizing should only be active when `strategy_mode == "composite"`. The `enabled` flag is necessary but not sufficient -- also gate on the presence of a signal score. If no score is available, fall back to static sizing.
**Warning signs:** AttributeError on `.signal.score` when using dynamic sizing with simple mode.

### Pitfall 5: Backtest Engine Not Reflecting Dynamic Sizing
**What goes wrong:** Backtests always use `initial_capital` as `max_position_size_usd`, so dynamic sizing effects are invisible in backtest results even when composite mode is selected.
**Why it happens:** The BacktestEngine creates its own `PositionSizer` with `max_position_size_usd=config.initial_capital`. It doesn't create or use a DynamicSizer.
**How to avoid:** When the backtest is in composite mode and dynamic sizing parameters are provided, the BacktestEngine should create a DynamicSizer and use it for position opens. Add dynamic sizing parameters to `BacktestConfig`.
**Warning signs:** Backtest P&L is identical regardless of signal quality (all positions same size).

### Pitfall 6: Configuration Overlap with Existing Settings
**What goes wrong:** Both `TradingSettings.max_position_size_usd` and `DynamicSizingSettings.max_position_size_usd` exist, creating confusion about which one is authoritative.
**Why it happens:** The existing `TradingSettings.max_position_size_usd` is used by `PositionSizer` as an absolute cap. DynamicSizer also needs a per-pair max.
**How to avoid:** DynamicSizingSettings should NOT duplicate `max_position_size_usd`. Instead, the DynamicSizer should read it from TradingSettings (or RiskSettings.max_position_size_per_pair, which already exists). The DynamicSizer only adds: `min_allocation_fraction`, `max_allocation_fraction`, `max_portfolio_exposure`, and `enabled`. The existing per-pair cap becomes the "100% allocation" ceiling.
**Warning signs:** Changing one setting but not the other produces unexpected behavior.

## Code Examples

### DynamicSizingSettings Configuration
```python
# Source: Project convention from config.py
class DynamicSizingSettings(BaseSettings):
    """Dynamic position sizing configuration (Phase 7: SIZE-01, SIZE-02).

    Controls signal-conviction-based allocation scaling and portfolio exposure cap.
    Reads per-pair max from RiskSettings.max_position_size_per_pair.

    All fields configurable via SIZING_ environment variable prefix.
    """

    model_config = SettingsConfigDict(env_prefix="SIZING_")

    enabled: bool = False  # Default off; preserves v1.0 static sizing
    min_allocation_fraction: Decimal = Decimal("0.3")  # Weakest signal -> 30% of per-pair max
    max_allocation_fraction: Decimal = Decimal("1.0")  # Strongest signal -> 100%
    max_portfolio_exposure: Decimal = Decimal("5000")  # Total USD exposure cap
```

### Orchestrator Integration (Approach A)
```python
# In orchestrator._open_profitable_positions_composite():

async def _open_profitable_positions_composite(
    self,
    composite_scores: list,
) -> None:
    """Open positions on top composite-scored pairs within risk limits (v1.1)."""
    # Compute current exposure once, update after each open
    current_exposure = self._compute_current_exposure()

    for cs in composite_scores:
        if not cs.signal.passes_entry:
            continue

        opp = cs.opportunity
        can_open, reason = self._risk_manager.check_can_open(
            symbol=opp.perp_symbol,
            position_size_usd=self._settings.trading.max_position_size_usd,
            current_positions=self._position_manager.get_open_positions(),
        )
        if not can_open:
            continue

        # Dynamic sizing: compute signal-adjusted budget
        available_balance = await self._get_available_balance()
        if self._dynamic_sizer is not None:
            budget = self._dynamic_sizer.compute_signal_budget(
                signal_score=cs.signal.score,
                current_exposure=current_exposure,
            )
            if budget is None:
                logger.info(
                    "portfolio_exposure_cap_reached",
                    symbol=opp.perp_symbol,
                    current_exposure=str(current_exposure),
                )
                break  # No more budget for any pair
            available_balance = min(available_balance, budget)

        try:
            position = await self.open_position(
                opp.spot_symbol, opp.perp_symbol,
                available_balance=available_balance,
            )
            # Update exposure for next iteration
            current_exposure += position.quantity * position.perp_entry_price
        except Exception as e:
            logger.error("composite_open_failed", symbol=opp.perp_symbol, error=str(e))
```

### Computing Current Portfolio Exposure
```python
def _compute_current_exposure(self) -> Decimal:
    """Sum notional value of all open positions (entry-price-based).

    Uses quantity * perp_entry_price as the notional for each position.
    This is a simplification (not mark-to-market) that is acceptable for
    delta-neutral positions where price risk is hedged.

    Returns:
        Total USD exposure across all open positions.
    """
    total = Decimal("0")
    for pos in self._position_manager.get_open_positions():
        total += pos.quantity * pos.perp_entry_price
    return total
```

### Test Pattern: Strong vs Weak Signal Sizing
```python
# Success Criterion 1: strong signal gets larger position than weak signal
def test_strong_signal_gets_larger_position(dynamic_sizer, position_sizer):
    """A pair with score=0.9 gets a larger position than score=0.3."""
    strong_budget = dynamic_sizer.compute_signal_budget(
        signal_score=Decimal("0.9"),
        current_exposure=Decimal("0"),
    )
    weak_budget = dynamic_sizer.compute_signal_budget(
        signal_score=Decimal("0.3"),
        current_exposure=Decimal("0"),
    )
    assert strong_budget is not None
    assert weak_budget is not None
    assert strong_budget > weak_budget

# Success Criterion 2: portfolio exposure never exceeds cap
def test_portfolio_cap_enforced(dynamic_sizer):
    """Budget is None when current exposure >= cap."""
    budget = dynamic_sizer.compute_signal_budget(
        signal_score=Decimal("1.0"),
        current_exposure=Decimal("5000"),  # At cap
    )
    assert budget is None

# Success Criterion 3: delegates to PositionSizer
def test_delegates_to_position_sizer(dynamic_sizer, mock_position_sizer):
    """DynamicSizer calls PositionSizer.calculate_matching_quantity."""
    dynamic_sizer.calculate_matching_quantity(
        signal_score=Decimal("0.8"),
        current_exposure=Decimal("0"),
        price=Decimal("50000"),
        available_balance=Decimal("10000"),
        spot_instrument=spot_inst,
        perp_instrument=perp_inst,
    )
    mock_position_sizer.calculate_matching_quantity.assert_called_once()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `max_position_size_usd` for all positions | Signal-conviction-based dynamic sizing | Phase 7 (this work) | Higher-confidence opportunities get larger allocations |
| No portfolio-level exposure tracking | Portfolio exposure cap across all positions | Phase 7 (this work) | Prevents over-concentration; total risk bounded |
| PositionSizer used directly in orchestrator | DynamicSizer wraps PositionSizer | Phase 7 (this work) | Exchange constraint delegation preserved; sizing intelligence added above |

**Deprecated/outdated:**
- No deprecations. Static sizing remains the default (`enabled: false`). The v1.0 path is fully preserved.

## Key Design Decisions for Planner

### 1. Where Dynamic Budget is Computed
The DynamicSizer is a standalone class called by the orchestrator, NOT injected into PositionManager. The orchestrator has access to the signal score (from CompositeOpportunityScore) and the portfolio state (from get_open_positions). It computes the budget and passes it as `available_balance` to `open_position()`. This means PositionManager remains signal-agnostic.

### 2. Per-Pair Max Comes from Existing Settings
DynamicSizingSettings does NOT duplicate `max_position_size_usd`. Instead, DynamicSizer reads the per-pair max from the config it is given (either `RiskSettings.max_position_size_per_pair` or `TradingSettings.max_position_size_usd`). This avoids the configuration overlap pitfall.

### 3. Portfolio Exposure is Entry-Price Based
For v1.1, portfolio exposure = sum(quantity * perp_entry_price) for all open positions. This is synchronous, deterministic, and sufficient for delta-neutral positions. Mark-to-market is deferred to v1.2 (SIZE-05 in future requirements).

### 4. Dynamic Sizing Requires Composite Mode
Dynamic sizing only operates when `strategy_mode == "composite"` AND `sizing.enabled == True`. In simple mode, there are no signal scores to drive the sizing, so static sizing is always used. The orchestrator gates both conditions.

### 5. Backtest Integration
BacktestConfig should gain dynamic sizing parameters. When enabled in composite mode, the BacktestEngine creates a DynamicSizer and adjusts position opens accordingly. This allows parameter sweeps over allocation fractions.

### 6. Budget Recomputation Within a Cycle
When the orchestrator opens multiple positions in a single cycle, it must update `current_exposure` after each successful open. This prevents exceeding the portfolio cap. The simplest approach: compute exposure once, increment by `qty * price` after each open.

## Open Questions

1. **Exact formula for score-to-size mapping**
   - What we know: Linear mapping from score to allocation fraction is simplest and most transparent. `fraction = min_frac + (max_frac - min_frac) * score`.
   - What's unclear: Whether a non-linear mapping (e.g., quadratic, step function) would be better. Backtesting could reveal this.
   - Recommendation: Start with linear. It is configurable and can be replaced later. The parameter sweep can test different min/max fraction combinations.
   - **Confidence:** HIGH (linear is the standard starting point)

2. **Whether DynamicSizer should also affect position CLOSING**
   - What we know: SIZE-01 says "position size scales with signal confidence" which implies entry sizing. It does not mention exit sizing.
   - What's unclear: Should the bot partially close positions when their signal weakens? (e.g., reduce from full to half position)
   - Recommendation: Out of scope for v1.1. Exit decisions remain binary (close/hold) based on composite score vs exit threshold. Partial position management is significantly more complex.
   - **Confidence:** HIGH (not in requirements)

3. **Whether max_portfolio_exposure should account for both legs (spot + perp)**
   - What we know: Each delta-neutral position has two legs: a spot buy and a perp sell. The actual capital deployed is roughly 1x the notional (spot buy costs ~quantity*price, perp margin is a fraction of that).
   - What's unclear: Should exposure = notional of one leg (the convention in most risk systems) or the total capital deployed?
   - Recommendation: Use one-leg notional (quantity * perp_entry_price). This is the industry standard for measuring exposure in leveraged products. The spot leg is fully funded, and the perp leg requires only margin. Using one-leg notional is simpler and more intuitive for the user.
   - **Confidence:** HIGH (standard industry convention)

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/bot/position/sizing.py` -- current PositionSizer API, exchange constraint validation
- Existing codebase: `src/bot/position/manager.py` -- PositionManager.open_position flow, how quantity is calculated
- Existing codebase: `src/bot/orchestrator.py` -- composite strategy cycle, how positions are opened, signal score availability
- Existing codebase: `src/bot/config.py` -- Settings pattern, RiskSettings.max_position_size_per_pair, TradingSettings.max_position_size_usd
- Existing codebase: `src/bot/signals/models.py` -- CompositeSignal.score (0-1 range)
- Existing codebase: `src/bot/models.py` -- Position dataclass fields (quantity, perp_entry_price)
- Existing codebase: `src/bot/risk/manager.py` -- RiskManager.check_can_open (existing pre-trade checks)
- Existing codebase: `src/bot/backtest/engine.py` -- BacktestEngine position sizing setup
- Existing codebase: `src/bot/main.py` -- Component wiring, optional injection pattern
- REQUIREMENTS.md: SIZE-01, SIZE-02, SIZE-03 requirement specifications
- ROADMAP.md: Phase 7 success criteria

### Secondary (MEDIUM confidence)
- Phase 5 research: Signal scoring conventions, composite signal output format
- Portfolio sizing literature: Linear allocation scaling is the standard starting point for conviction-weighted sizing

### Tertiary (LOW confidence)
- Optimal allocation fractions (30%-100% range): Reasonable defaults, require backtesting to validate

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries; pure Decimal computation with existing deps
- Architecture: HIGH -- follows established project patterns (optional injection, config-driven, delegation)
- DynamicSizer design: HIGH -- simple delegation pattern; SIZE-03 mandate is clear and unambiguous
- Integration points: HIGH -- orchestrator, config, main.py wiring fully understood from code review
- Default parameters: LOW -- allocation fractions and portfolio cap are empirical, need backtesting
- Pitfalls: HIGH -- identified from code review (exposure drift, race conditions, config overlap)

**Research date:** 2026-02-12
**Valid until:** 2026-03-12 (30 days -- codebase is stable, no external dependency changes expected)
