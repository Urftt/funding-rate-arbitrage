# Funding Rate Arbitrage Bot

## What This Is

A fully automated funding rate arbitrage bot for Bybit that exploits the spread between spot and perpetual futures markets. It scans all trading pairs for favorable funding rates, opens delta-neutral positions (long spot + short perp), collects funding payments, and exits when conditions deteriorate. Built primarily as a learning project with real profit potential.

## Core Value

The bot correctly identifies funding rate opportunities and executes delta-neutral positions that collect funding payments without taking directional risk.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Scan all Bybit pairs and rank by funding rate opportunity
- [ ] Open delta-neutral positions (buy spot + short perp) automatically
- [ ] Monitor open positions and collect funding payments
- [ ] Close positions when funding rate turns unprofitable
- [ ] Paper trading mode that simulates the full lifecycle without real orders
- [ ] Web dashboard with live positions, funding rates, trade history, P&L, and bot controls
- [ ] Configurable risk parameters (position sizing, minimum funding rate thresholds)

### Out of Scope

- Cross-exchange arbitrage — keeping it single-exchange (Bybit) for simplicity
- Mobile app — web dashboard is sufficient
- Telegram/Discord notifications — dashboard covers monitoring needs for v1
- Leverage optimization — moderate fixed approach first, tuning later
- Multiple strategy types — funding rate arb only

## Context

- **Strategy:** Spot-perp delta neutral. When perpetual funding rate is positive, short perp + long spot. Collect funding payments every 8 hours while maintaining market-neutral exposure.
- **Exchange:** Bybit only. Single exchange simplifies execution — no transfer delays, unified account, single API.
- **Capital progression:** Paper trading first to validate logic. Then $100-500 real capital. Scale up if consistently profitable.
- **Deployment progression:** Local development on laptop first. Future migration to Docker containers on home server for 24/7 uptime.
- **Learning goals:** Exchange API integration, real-time data handling, position management, risk management, web dashboard development.

## Constraints

- **Tech stack**: Python — ecosystem strength for trading (ccxt, pandas, async)
- **Exchange**: Bybit only — no multi-exchange complexity
- **Risk**: Moderate — reasonable position sizes, some tolerance for temporary funding dips, but exit on sustained unfavorable conditions
- **v1 scope**: Paper trading must work before any real money integration

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single exchange (Bybit) | Reduces complexity, faster to build and learn | — Pending |
| Paper trading first | Validate logic before risking capital | — Pending |
| Python | Best ecosystem for trading bots (ccxt, pandas, async support) | — Pending |
| Web dashboard over CLI | Need visual overview of positions, rates, and P&L | — Pending |
| Spot-perp delta neutral | Simpler than cross-exchange, proven strategy | — Pending |

---
*Last updated: 2026-02-11 after initialization*
