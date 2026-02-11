# Domain Pitfalls: Crypto Funding Rate Arbitrage Bot

**Domain:** Cryptocurrency funding rate arbitrage (spot-perp delta neutral)
**Researched:** 2026-02-11
**Confidence:** LOW (based on training data without current verification)

> **IMPORTANT NOTE:** This document was created without access to research tools. All findings are based on training data knowledge of crypto arbitrage systems and should be verified against current documentation, community post-mortems, and practitioner experience before being considered authoritative.

## Critical Pitfalls

Mistakes that cause rewrites, major losses, or project failure.

### Pitfall 1: Incomplete Delta Hedge During Volatile Moves
**What goes wrong:** Bot opens spot position, then market moves before perp hedge is placed. You're no longer delta neutral and exposed to directional risk. In volatile crypto markets, even a 1-second delay can result in 1-5% slippage, wiping out weeks of funding rate profits.

**Why it happens:**
- Sequential order placement (spot first, then perp)
- No order timeout detection
- Assuming orders fill at expected prices
- Not accounting for partial fills
- Network latency to exchange

**Consequences:**
- Directional exposure during high volatility = massive losses
- A single BTC move of $2000 on unhedged $10K position = $2000 loss vs typical funding income of $10-50/day
- Can lose a month's profit in minutes

**Prevention:**
- Place both orders simultaneously via async calls
- Implement strict timeout thresholds (1-3 seconds max)
- If either order fails/times out, immediately cancel both and exit
- Monitor fill ratios — if spot fills 100% but perp only 70%, immediately close the unhedged portion
- Use limit orders close to market price with aggressive time-in-force settings
- Consider using exchange-native hedging features if available

**Detection (warning signs):**
- Position monitor shows spot != perp quantity
- Unrealized P&L swinging wildly (should be near zero for delta neutral)
- Order logs show large time gaps between spot and perp fills
- Slippage metrics exceed expected ranges

**Phase assignment:** Phase 1 (Core Trading Engine) — Must be solved before any real money trading

---

### Pitfall 2: Funding Rate Sign Confusion
**What goes wrong:** Bot misinterprets funding rate sign and opens positions backwards. When funding is positive (longs pay shorts), you should be SHORT perp + LONG spot. Reversing this means paying funding instead of collecting it.

**Why it happens:**
- Exchange API inconsistencies (some report from long perspective, some from short)
- Bybit specifically: positive funding = longs pay shorts, but this isn't universal
- Copy-pasting code from other exchanges without adapting
- Not testing with negative funding scenarios
- Confusion about what "positive funding" means

**Consequences:**
- Paying funding instead of collecting it (100% profit inversion)
- Can take days to notice if not monitoring actual funding payments
- Compounding losses as you pay funding every 8 hours

**Prevention:**
- Document exchange-specific conventions clearly in code comments
- Create a mapping layer that normalizes funding rates to consistent internal representation
- Unit tests with both positive and negative funding scenarios
- Paper trading validation: manually verify first few trades collect (not pay) funding
- Add assertion checks: "if expected_funding > 0 then perp_position must be SHORT"
- Dashboard shows funding direction explicitly ("COLLECTING" vs "PAYING")

**Detection:**
- Funding payments are negative when they should be positive
- Dashboard shows increasing losses every 8 hours instead of profits
- Realized P&L trends negative without market moves

**Phase assignment:** Phase 1 (Core Trading Engine) — Critical logic error

---

### Pitfall 3: Ignoring Exchange Fee Impact on Profitability
**What goes wrong:** Bot opens positions where gross funding rate looks attractive (e.g., 0.05%/8hr = ~0.2%/day) but after accounting for fees to enter (spot + perp), exit (spot + perp), and potential rebalancing, the net return is negative or barely breakeven.

**Why it happens:**
- Focusing only on funding rate without fee modeling
- Not accounting for bid-ask spread (implicit cost)
- Bybit maker/taker fee structure misunderstood
- Forgetting withdrawal fees if moving funds between spot/derivatives
- Not considering minimum profitable holding period

**Consequences:**
- Death by a thousand cuts: every trade loses money to fees
- Positions that should be profitable show losses
- High turnover strategies (frequently opening/closing) amplify the problem
- Bot appears "busy" but loses money

**Prevention:**
- Calculate net funding rate: `net = (funding_rate * holding_periods) - (entry_fees + exit_fees)`
- Only open positions where net > minimum threshold (e.g., 0.3% profit minimum)
- Account for realistic spread costs (not just maker fees)
- Model minimum holding period: if funding is 0.05%/8hr, need to hold multiple periods to overcome ~0.1% entry+exit fees
- Track fee metrics: fees_paid / funding_collected ratio (should be << 1)
- Use maker orders when possible (lower fees)

**Detection:**
- Realized P&L negative despite collecting funding
- Fee ratio metrics show fees consuming >50% of funding income
- High frequency position turnover (multiple times per day)
- Paper trading shows profits but real trading doesn't

**Phase assignment:** Phase 2 (Position Selection Logic) — Must be validated before real money

---

### Pitfall 4: Cascade Liquidations During Extreme Volatility
**What goes wrong:** Market crashes 20%+ rapidly. Spot position loses value, but perp position gains offsetting this. However, if perp position is on high leverage and exchange margin requirements spike during volatility, you get liquidated on the perp side despite being delta neutral overall.

**Why it happens:**
- Using excessive leverage on perp side (even though delta neutral)
- Not accounting for exchange dynamic margin requirements
- Maintenance margin increases during high volatility
- Liquidation happens before you can add collateral
- Cross-margin vs isolated margin misunderstanding

**Consequences:**
- Forced liquidation of profitable perp hedge
- Left with unhedged spot position during crash
- Can lose 10-30% of capital in minutes
- Liquidation fees add insult to injury

**Prevention:**
- Use conservative leverage (2-3x max, even though 10x+ available)
- Maintain excess collateral buffer (30-50% above maintenance margin)
- Monitor margin ratio continuously — if < 50%, reduce position size
- Use isolated margin mode to prevent contagion across positions
- Set up margin ratio alerts (warn at 60%, critical at 40%)
- Have emergency protocols: auto-reduce positions if margin critical
- Test liquidation scenarios in paper trading with historical volatility data

**Detection:**
- Margin ratio dropping rapidly
- Exchange sends margin call warnings
- Position sizes approaching liquidation thresholds
- Collateral requirements increasing (exchange announcements)

**Phase assignment:** Phase 1 (Core Trading Engine) — Risk management must be built-in from start

---

### Pitfall 5: API Rate Limits Causing Missed Opportunities or Failures
**What goes wrong:** Bot makes too many API calls (checking prices, placing orders, monitoring positions) and gets rate limited by Bybit. During rate limit period, bot can't place orders, miss arbitrage opportunities, or worse — can't close positions during emergencies.

**Why it happens:**
- Polling exchange too frequently (every second for prices)
- Not using websocket streams for real-time data
- Retrying failed requests without backoff
- Running multiple bot instances that share rate limit
- Bybit rate limits are per API key across all endpoints

**Consequences:**
- 418 rate limit errors → bot can't trade
- Missed profitable opportunities
- Can't close positions during critical moments
- Account temporarily banned (worst case)

**Prevention:**
- Use websockets for real-time data (funding rates, prices, positions)
- Implement token bucket rate limiting client-side
- REST API only for state-changing operations (orders, cancellations)
- Exponential backoff on retries with jitter
- Monitor rate limit headers from exchange responses
- Cache data where appropriate (funding rates only update every 8hrs)
- Document Bybit rate limits clearly and stay at 50% of limit for safety margin

**Detection:**
- 418 HTTP errors in logs
- "Too many requests" error messages
- Increasing API call latency
- Gaps in data collection
- Order placement failures

**Phase assignment:** Phase 1 (Core Trading Engine) — API client design fundamental

---

## Moderate Pitfalls

Significant issues but recoverable with operational discipline.

### Pitfall 6: Stale Funding Rate Data
**What goes wrong:** Bot uses cached funding rate data that's hours old. Opens position based on 0.1% funding rate, but current rate is now 0.01% or even negative.

**Why it happens:**
- Funding rates update every 8 hours but bot doesn't refresh
- Caching strategy too aggressive
- Not subscribing to funding rate updates
- Time zone confusion on when funding updates

**Prevention:**
- Subscribe to funding rate websocket updates if available
- If using REST API, refresh funding rates every hour minimum
- Store timestamps with all funding data and validate freshness
- Never open positions with data >1 hour old
- Dashboard shows data freshness explicitly

**Detection:**
- Data timestamps are old
- Expected funding payments don't match actual
- Funding rates on dashboard don't match exchange website

**Phase assignment:** Phase 2 (Position Selection Logic)

---

### Pitfall 7: Overtrading on Illiquid Pairs
**What goes wrong:** Bot identifies great funding rate on obscure token (0.5%/8hr). Opens position but can't exit because liquidity dried up. Stuck in position with high funding exposure or forced to exit at massive slippage.

**Why it happens:**
- Filtering only by funding rate, ignoring volume/liquidity
- Not checking order book depth
- Assuming current liquidity will persist
- Small cap tokens have sporadic liquidity

**Prevention:**
- Filter pairs by minimum 24hr volume (e.g., $1M+)
- Check order book depth before opening (can you exit 2x position size within 1% slippage?)
- Whitelist approach: only trade top 20-30 pairs by volume
- Test exit orders in paper trading before real money
- Monitor liquidity metrics over time

**Detection:**
- Order fills taking minutes instead of seconds
- High slippage on exits
- Order book shows thin depth
- Volume metrics declining

**Phase assignment:** Phase 2 (Position Selection Logic)

---

### Pitfall 8: Position Sizing Errors
**What goes wrong:** Bot calculates position size incorrectly — either too large (risk concentration) or mismatched between spot and perp (breaks delta hedge).

**Why it happens:**
- Precision errors in float calculations
- Not accounting for exchange lot size requirements
- Rounding spot and perp independently causing mismatch
- Using notional value when exchange expects contracts

**Prevention:**
- Use Decimal library for financial calculations (not float)
- Fetch and respect exchange lot size/step size constraints
- Round both spot and perp to ensure matching notional value
- Max position size limits (e.g., 20% of capital per position)
- Pre-execution validation: assert spot_value ≈ perp_value within tolerance
- Unit tests for position sizing edge cases

**Detection:**
- Position monitor shows mismatched sizes
- Exchange rejects orders (lot size invalid)
- Delta hedge ratio deviating from 1:1

**Phase assignment:** Phase 1 (Core Trading Engine)

---

### Pitfall 9: Not Handling Funding Rate Changes Mid-Position
**What goes wrong:** Open position when funding is 0.1%/8hr (attractive). Funding rate drops to 0.01% or goes negative while position is open. Bot keeps position open, now losing money or barely profitable.

**Why it happens:**
- No monitoring of funding rates post-entry
- No exit criteria based on funding rate changes
- "Set and forget" approach

**Prevention:**
- Continuously monitor funding rates for open positions
- Define exit criteria: close if funding drops below threshold (e.g., 0.02%/8hr)
- Implement rebalancing logic: evaluate if position still worthwhile
- Consider predicted funding rate (next period) not just current

**Detection:**
- Open positions showing declining profitability
- Funding payments decreasing over time
- Funding rate trends downward in data

**Phase assignment:** Phase 3 (Position Management)

---

### Pitfall 10: Exchange Downtime / Maintenance
**What goes wrong:** Bybit goes into maintenance mode. Bot can't access positions, can't close hedges, or worse — only spot or perp side is accessible, breaking delta neutral hedge.

**Why it happens:**
- Exchange scheduled/unscheduled maintenance
- Partial outages (spot works but derivatives don't)
- Network connectivity issues

**Prevention:**
- Monitor exchange status APIs
- Set up alerts for exchange maintenance announcements
- Graceful degradation: halt new positions if exchange unstable
- Consider multi-exchange approach for redundancy (future enhancement)
- Maintain local state that doesn't depend on real-time exchange access
- Emergency procedures documented for manual intervention

**Detection:**
- API timeouts/errors
- Exchange status page shows issues
- Websocket disconnections
- Order placement failures

**Phase assignment:** Phase 4 (Monitoring & Resilience)

---

## Minor Pitfalls

Annoying but low-impact issues.

### Pitfall 11: Time Zone Confusion on Funding Timestamps
**What goes wrong:** Funding times are 00:00, 08:00, 16:00 UTC. Bot logic uses local time, causing off-by-hours errors in funding calculations or position timing.

**Prevention:**
- All internal timestamps in UTC
- Convert to local time only for display
- Test with different system time zones

**Phase assignment:** Phase 1 (Core Trading Engine)

---

### Pitfall 12: Logging Sensitive Data
**What goes wrong:** API keys, account balances, or position sizes logged to files. Security risk if logs are compromised or shared for debugging.

**Prevention:**
- Redact API keys/secrets in logs
- Use log levels appropriately (debug vs info vs error)
- Separate sensitive data into secure storage
- Review logs before sharing

**Phase assignment:** Phase 1 (Core Trading Engine)

---

### Pitfall 13: No Paper Trading Validation
**What goes wrong:** Jump straight to real money without validating bot logic. Discover critical bugs with real capital at risk.

**Prevention:**
- Mandatory paper trading phase
- Run for minimum 1-2 weeks simulated
- Validate across different market conditions
- Check all edge cases before live trading

**Phase assignment:** Phase 1 → Phase 2 transition gate

---

### Pitfall 14: Dashboard Shows Incorrect P&L
**What goes wrong:** Dashboard calculates P&L incorrectly (e.g., doesn't account for funding payments, uses wrong entry prices, ignores fees). Users make decisions based on wrong information.

**Prevention:**
- Reconcile dashboard P&L with exchange account statements
- Separate unrealized vs realized P&L clearly
- Include all costs: fees, funding, slippage
- Unit tests for P&L calculations with real scenarios

**Phase assignment:** Phase 5 (Dashboard & Monitoring)

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Phase 1: Core Trading | Incomplete delta hedging (Critical #1) | Simultaneous order placement, strict timeouts |
| Phase 1: Core Trading | Funding rate sign confusion (Critical #2) | Exchange-specific documentation, unit tests |
| Phase 1: Core Trading | API rate limits (Critical #5) | Websockets for data, REST for actions only |
| Phase 1: Core Trading | Position sizing errors (Moderate #8) | Decimal library, exchange constraints respected |
| Phase 2: Position Selection | Fee impact blindness (Critical #3) | Net funding rate calculation including all fees |
| Phase 2: Position Selection | Stale funding data (Moderate #6) | Regular refresh, timestamp validation |
| Phase 2: Position Selection | Illiquid pairs (Moderate #7) | Volume filters, liquidity checks |
| Phase 3: Position Management | Ignoring funding changes (Moderate #9) | Continuous monitoring, exit criteria |
| Phase 4: Risk Management | Cascade liquidations (Critical #4) | Conservative leverage, margin monitoring |
| Phase 4: Resilience | Exchange downtime (Moderate #10) | Status monitoring, graceful degradation |
| Phase 5: Dashboard | Incorrect P&L display (Minor #14) | Reconciliation with exchange, comprehensive cost accounting |

---

## Risk Hierarchy for Roadmap Planning

### Must Address Before Real Money (Phase 1-2)
1. Incomplete delta hedging (#1)
2. Funding rate sign confusion (#2)
3. Fee impact analysis (#3)
4. Cascade liquidations (#4)
5. API rate limits (#5)
6. Position sizing (#8)
7. Paper trading validation (#13)

### Address During Early Operation (Phase 3-4)
8. Funding rate monitoring (#9)
9. Exchange downtime handling (#10)
10. Stale data (#6)
11. Illiquid pairs (#7)

### Quality of Life (Phase 5+)
12. Time zone handling (#11)
13. Logging security (#12)
14. Dashboard accuracy (#14)

---

## Sources

**Confidence: LOW** — This document is based on training data knowledge of:
- Crypto arbitrage trading systems
- Exchange API integration patterns
- Risk management in algorithmic trading
- Common failure modes in automated trading

**Recommended verification:**
- Bybit official API documentation (funding rate conventions, rate limits)
- Crypto trading community forums (BitcoinTalk, Reddit r/algotrading)
- Post-mortems from similar projects
- Bybit-specific developer resources and known issues
- Academic papers on funding rate arbitrage
- Practitioner blogs and case studies

**Critical verification needs:**
- Bybit funding rate sign convention (is positive = longs pay shorts?)
- Bybit rate limit specifics (requests per second, burst allowance)
- Bybit margin calculation during volatility (dynamic requirements?)
- Current Bybit fee structure (maker/taker, spot vs derivatives)
- Bybit maintenance windows (frequency, duration, partial outages?)

---

## Research Methodology Note

This document was created without access to:
- WebSearch (for current community wisdom, blog posts, post-mortems)
- WebFetch (for official Bybit documentation)
- Context7 (for library-specific patterns)

All findings are based on general crypto arbitrage knowledge from training data. **Each pitfall should be validated against current Bybit documentation and practitioner experience before being considered authoritative.** The phase assignments and prevention strategies are sound in principle but may need adjustment based on Bybit-specific API capabilities and limitations discovered during validation.
