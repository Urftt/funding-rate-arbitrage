# Project Research Summary

**Project:** Crypto Funding Rate Arbitrage Bot
**Domain:** Cryptocurrency derivatives arbitrage (spot-perpetual delta neutral strategy)
**Researched:** 2026-02-11
**Confidence:** MEDIUM

## Executive Summary

This project aims to build an automated trading bot that profits from funding rate arbitrage on cryptocurrency perpetual futures. The strategy is delta-neutral: simultaneously holding long spot positions and short perpetual positions to collect funding payments paid by longs to shorts every 8 hours. Experts build these systems using Python 3.11+ with asyncio for concurrent API handling, event-driven architectures for real-time market data processing, and strict risk management to maintain delta neutrality.

The recommended approach is to start with a paper trading MVP that validates core trading logic before risking real capital. Focus Phase 1 on the critical path: exchange API integration, simultaneous order execution to maintain delta neutrality, and basic position tracking. Phase 2 adds multi-pair ranking and real money trading with comprehensive risk controls. Phase 3 introduces advanced position management and analytics. This staged approach allows early validation of the most critical pitfalls (incomplete delta hedging, funding rate sign confusion, fee impact) before they can cause significant losses.

Key risks center on maintaining delta neutrality during volatile markets, correctly interpreting funding rate signs, and ensuring fees don't exceed funding income. Prevention requires simultaneous order placement with strict timeouts, exchange-specific testing of funding conventions, and comprehensive fee modeling before opening positions. The technical stack (Python asyncio, PostgreSQL with TimescaleDB, FastAPI) is well-suited to handle multiple concurrent market connections while maintaining reliable transaction history. Conservative leverage (2-3x maximum) and continuous margin monitoring prevent cascade liquidations during extreme volatility.

## Key Findings

### Recommended Stack

Python 3.11+ with asyncio forms the foundation, providing 15-60% better async performance than previous versions and the best crypto library ecosystem. The core stack prioritizes reliability for financial operations: PostgreSQL with TimescaleDB extension for ACID-compliant transaction history and time-series funding rate data, asyncpg for high-performance async database access, and the Decimal library (not floats) for all monetary calculations to prevent precision errors.

**Core technologies:**
- **Python 3.11+ with asyncio**: Native async/await for handling multiple websocket connections and concurrent API calls to exchanges
- **pybit 5.x or ccxt 4.x**: Exchange API client (start with pybit as Bybit's official SDK, fallback to ccxt if needed)
- **PostgreSQL 15+ with TimescaleDB**: ACID-compliant storage for trade history with time-series optimizations for funding rate analytics
- **FastAPI 0.109+ with uvicorn**: Modern async web framework for dashboard API with automatic validation and WebSocket support for live updates
- **React 18.2+ with Next.js 14+**: Frontend framework for real-time trading dashboard with TanStack Query for data synchronization
- **structlog + prometheus-client**: Structured logging with JSON output and time-series metrics for monitoring bot performance
- **Decimal (stdlib)**: Mandatory for all monetary calculations to prevent floating-point precision errors that cause losses

**Critical warnings from stack research:**
- Never use Python floats for money calculations (use Decimal)
- Don't block the async event loop with synchronous API calls
- Use websockets for market data, REST only for state-changing operations (orders)
- Avoid Celery complexity — asyncio + APScheduler sufficient for single-bot architecture
- All package versions need verification against current PyPI/official docs (research based on training data)

### Expected Features

Research identifies clear feature tiers based on arbitrage requirements and competitive differentiation.

**Must have (table stakes):**
- Automated position opening/closing (spot + perp simultaneously)
- Real-time funding rate monitoring across pairs
- Position size calculation respecting balance and leverage limits
- Basic risk controls (max position size, max pairs, emergency stop)
- Paper trading mode for risk-free validation
- Position dashboard showing pair, size, P&L, funding collected
- Trade history with timestamps for audit trail
- Transaction fee accounting (entry/exit fees reduce net profit)
- Minimum funding threshold filter (only enter profitable opportunities)
- Bot start/stop controls with clean shutdown

**Should have (competitive differentiators):**
- Multi-pair ranking system (automatically find best opportunities)
- Dynamic position management (rebalance to highest-yielding pairs)
- Liquidity analysis (avoid pairs with insufficient depth)
- Historical performance analytics (Sharpe ratio, max drawdown by pair)
- Webhook/Telegram alerts for position events and errors
- Configurable strategy parameters (thresholds, risk limits, filters)
- Funding rate heatmap visualization across pairs
- Slippage protection (reject trades with excessive expected slippage)

**Defer (v2+):**
- Funding rate prediction using ML/statistical models (requires historical data pipeline)
- Backtesting engine (complex historical data requirements)
- Multi-exchange support (very high complexity, different APIs)
- Auto-compounding (nice-to-have enhancement)
- Tax loss harvesting (jurisdiction-specific complexity)

**Explicit anti-features (do NOT build):**
- High-frequency trading (not funding arbitrage's strength — 8hr cycles tolerate minute-scale latency)
- Leveraged spot positions (massively increases risk — keep spot unleveraged)
- Social/copy trading features (legal/regulatory complexity)
- Automatic capital injection from external wallets (prevents runaway allocation)

### Architecture Approach

Event-driven architecture with explicit state machine for bot lifecycle management. Components communicate via async events rather than direct calls to handle real-time market data, order fills, and funding updates. The Bot Orchestrator manages strategy execution through well-defined states (INITIALIZING → SCANNING → OPENING → MONITORING → CLOSING → IDLE, with ERROR/RECOVERING paths).

**Major components:**
1. **Exchange Adapter Layer** — Abstracts Bybit API (rate limiting, websocket management, authentication), ensures single point for exchange-specific logic
2. **Data Feed Manager** — Ingests market data via websockets, normalizes and distributes to strategy components
3. **Bot Orchestrator** — Main strategy loop implementing state machine, coordinates all components
4. **Risk Manager** — Pre-trade validation (position limits, exposure checks, delta neutrality validation)
5. **Execution Engine** — Order placement via async queue, handles fills tracking and slippage management
6. **Position Manager** — Tracks open position state, runs reconciliation loop (every 30s) to detect discrepancies with exchange
7. **P&L Engine** — Calculates realized/unrealized P&L, tracks funding collection, generates performance metrics
8. **Web Dashboard** — FastAPI backend with React frontend, WebSocket updates for real-time position monitoring

**Critical patterns:**
- Circuit Breaker for exchange API (automatically stops calls when error rate exceeds threshold)
- Delta Neutrality Validator (continuous validation that spot + perp positions maintain neutrality within 2% drift)
- Async Queue-Based Execution (prevents race conditions in concurrent order placement)
- Position Reconciliation Loop (periodic comparison with exchange state to catch missed messages)

**Build order implications:** Phase 1 must establish foundation layer (Config Manager, Persistence, Exchange Adapter) before Phase 2 data layer (Data Feed, Position Manager), which enables Phase 3 logic layer (Risk Manager, Execution Engine, P&L), culminating in Phase 4 orchestration and Phase 5 interface layer.

### Critical Pitfalls

Research identified 14 pitfalls across criticality levels; top 5 require prevention before real money trading:

1. **Incomplete Delta Hedge During Volatile Moves** — Opening spot position followed by perp hedge creates directional exposure window. A 1-second delay during volatility can cause 1-5% slippage, wiping out weeks of funding profits. Prevention: simultaneous order placement via async calls, strict 1-3s timeout, immediate cancellation if either side fails/times out, monitor fill ratios and close unhedged portions immediately.

2. **Funding Rate Sign Confusion** — Misinterpreting funding rate sign (Bybit convention: positive = longs pay shorts) causes opening positions backwards, paying funding instead of collecting. Prevention: document exchange conventions in code, normalize to internal representation, unit tests with both positive/negative scenarios, paper trading validation, assertion checks linking funding direction to position side.

3. **Ignoring Exchange Fee Impact** — Gross funding rate looks attractive but net return after entry/exit fees is negative. A 0.05%/8hr funding rate requires multiple holding periods to overcome ~0.1% total fees. Prevention: calculate net funding rate including all fees before opening, set minimum net profit threshold (e.g., 0.3%), model minimum holding period, track fee/funding ratio metrics.

4. **Cascade Liquidations During Extreme Volatility** — Delta-neutral position gets liquidated on perp side despite offsetting spot gains, due to high leverage or spiking margin requirements during volatility. Prevention: conservative leverage (2-3x max), maintain 30-50% excess collateral buffer, continuous margin monitoring with alerts at 60%/40%, use isolated margin mode, emergency position reduction protocols.

5. **API Rate Limits Causing Failures** — Excessive API polling triggers rate limits, preventing critical operations like closing positions during emergencies. Prevention: websockets for real-time data (funding rates, prices), REST only for state-changing operations, client-side token bucket rate limiting, exponential backoff with jitter, stay at 50% of exchange limit for safety margin.

## Implications for Roadmap

Based on research, suggested 5-phase structure prioritizing risk mitigation and early validation:

### Phase 1: Core Trading Engine (Paper Trading)
**Rationale:** Foundation layer must work correctly before building higher-level features. Delta hedging, funding sign interpretation, and position sizing are critical pitfalls that require early validation. Paper trading mode allows risk-free testing of core logic.

**Delivers:**
- Exchange API integration (Bybit via pybit/ccxt)
- Market data ingestion (websockets for funding rates, prices)
- Simultaneous order execution (spot + perp with timeout protection)
- Basic position tracking and delta neutrality validation
- Paper trading mode (simulated execution, virtual balances)
- Configuration management (pydantic for type-safe config)
- Structured logging (structlog with JSON output)

**Addresses (from FEATURES.md):**
- Real-time funding rate monitoring (single pair initially)
- Position size calculation with Decimal precision
- Automated position opening/closing in paper mode
- Basic position dashboard (minimal UI)
- Bot start/stop controls
- Trade history logging

**Avoids (from PITFALLS.md):**
- Critical #1: Incomplete delta hedge (simultaneous orders, timeouts)
- Critical #2: Funding rate sign confusion (exchange-specific tests)
- Critical #5: API rate limits (websockets for data, rate limiter implementation)
- Moderate #8: Position sizing errors (Decimal library, lot size constraints)
- Minor #11: Time zone issues (all UTC internally)
- Minor #12: Logging sensitive data (redaction patterns)

**Stack elements:**
- Python 3.11+, asyncio, pybit, asyncpg, PostgreSQL, structlog, pydantic

### Phase 2: Multi-Pair Real Money Trading
**Rationale:** After paper trading validates core logic (minimum 1-2 weeks), expand to multi-pair ranking and enable real money mode. Fee analysis and liquidity checks prevent unprofitable trades. Risk controls (position limits, margin monitoring) prevent cascade liquidations.

**Delivers:**
- Multi-pair ranking system (scan all markets, rank by net yield after fees)
- Fee impact calculation (entry + exit fees vs expected funding)
- Minimum profitability thresholds (only enter if net > 0.3%)
- Liquidity analysis (filter by volume, check order book depth)
- Real money mode toggle (validated by paper trading success)
- Comprehensive risk controls (max position size per pair, max total pairs, leverage limits)
- Margin monitoring with alerts (warn at 60%, critical at 40%)
- Balance tracking (available vs allocated capital)
- Funding collection tracking per position

**Addresses:**
- Multi-pair ranking (differentiator)
- Risk controls (position limits, stop loss)
- Real money mode
- Balance and funding tracking
- Error handling with retries

**Avoids:**
- Critical #3: Fee impact blindness (net funding calculation)
- Critical #4: Cascade liquidations (conservative leverage, margin monitoring)
- Moderate #6: Stale funding data (regular refresh, timestamp validation)
- Moderate #7: Illiquid pairs (volume filters, depth checks)

**Stack elements:**
- pandas for analysis (cold path only), numpy for calculations, APScheduler for periodic tasks

### Phase 3: Dynamic Position Management
**Rationale:** With multi-pair real trading stable, add intelligence to rebalance capital toward best opportunities. Continuous funding rate monitoring enables closing positions when rates drop or go negative.

**Delivers:**
- Continuous funding rate monitoring for open positions
- Exit criteria based on funding rate changes (close if below threshold)
- Dynamic rebalancing (evaluate if position still worthwhile, shift capital to better pairs)
- Position reconciliation loop (every 30s, detect exchange state discrepancies)
- Enhanced error recovery (state transitions, notification on critical errors)
- Performance analytics (Sharpe ratio, max drawdown by pair, win rate)

**Addresses:**
- Dynamic position management (differentiator)
- Performance analytics (differentiator)

**Avoids:**
- Moderate #9: Ignoring funding changes mid-position
- Improves resilience against missed websocket messages via reconciliation

**Stack elements:**
- polars for high-performance analytics, circuit breaker pattern for API resilience

### Phase 4: Monitoring & Resilience
**Rationale:** Production hardening to handle edge cases and operational issues. Exchange downtime, network issues, and system errors need graceful handling.

**Delivers:**
- Exchange status monitoring (detect maintenance, outages)
- Graceful degradation (halt new positions if exchange unstable)
- Circuit breaker for API calls (auto-stop when error rate spikes)
- Emergency shutdown procedures (documented manual intervention paths)
- Prometheus metrics export (funding rate deltas, position count, API latency, margin ratio)
- Grafana dashboards (time-series visualization of bot health)
- Alert system integration (critical errors, margin warnings, API failures)

**Addresses:**
- Notification manager component from architecture

**Avoids:**
- Moderate #10: Exchange downtime causing stuck positions
- Improves error detection and recovery

**Stack elements:**
- prometheus-client, Grafana, APScheduler for health checks

### Phase 5: Advanced Dashboard & User Experience
**Rationale:** With core trading and monitoring stable, enhance user interface for better control and insights.

**Delivers:**
- Full-featured React dashboard (Next.js with TanStack Query)
- Real-time WebSocket updates (position changes, funding collections, alerts)
- Configurable strategy parameters UI (thresholds, risk limits, pair filters)
- Funding rate heatmap visualization (rates across all pairs over time)
- Telegram webhook alerts (position opens/closes, errors, funding collections)
- Detailed trade history view (filterable, exportable)
- Backtesting capability (test strategy on historical data)

**Addresses:**
- Configurable parameters (differentiator)
- Telegram alerts (differentiator)
- Funding rate heatmap (differentiator)
- Enhanced dashboard visualizations

**Avoids:**
- Minor #14: Dashboard P&L inaccuracy (reconciliation with exchange, comprehensive costs)

**Stack elements:**
- FastAPI, React, Next.js, TanStack Query, shadcn/ui, Recharts

### Phase Ordering Rationale

- **Foundation-first approach:** Phase 1 establishes Exchange Adapter, Config Manager, Persistence before anything else — these have no dependencies but everything depends on them
- **Early risk validation:** Phases 1-2 address all 5 critical pitfalls before real money trading, using paper trading as validation gate
- **Dependency-driven sequencing:** Data layer (Phase 2) requires foundation, logic layer (Phase 3) requires data layer, orchestration (Phase 4) coordinates all, UI (Phase 5) visualizes everything
- **Incremental value delivery:** Each phase delivers working functionality (paper trading → real trading → smart rebalancing → production hardening → enhanced UX)
- **Defer complexity:** ML prediction, backtesting engine, multi-exchange to v2+ (high complexity, not core to proving strategy viability)

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 1:** Bybit API specifics (current rate limits, websocket specifications, funding rate endpoint details, authentication flows) — use `/gsd:research-phase` to verify against official docs
- **Phase 2:** Exchange fee structures (current maker/taker fees, spot vs derivatives, any volume discounts) — verify pricing before fee calculations
- **Phase 3:** Bybit margin calculation methods (how maintenance margin changes during volatility, isolated vs cross margin behavior) — critical for liquidation prevention

**Phases with standard patterns (skip research-phase):**
- **Phase 4:** Prometheus + Grafana monitoring (well-documented, established patterns)
- **Phase 5:** React + FastAPI dashboard (standard web stack, extensive examples available)

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Python asyncio, PostgreSQL, FastAPI are established patterns for trading bots; specific library versions (pybit 5.x, ccxt 4.x) need verification against current PyPI/official docs |
| Features | MEDIUM-LOW | Table stakes features based on arbitrage fundamentals are sound; competitive landscape and differentiators not verified against current 2026 market |
| Architecture | MEDIUM | Event-driven architecture, state machines, circuit breakers are industry-standard for trading systems; Bybit-specific API behaviors need verification |
| Pitfalls | LOW-MEDIUM | Core pitfalls (delta hedging, funding sign, fees) are fundamental to arbitrage; specific Bybit behaviors (margin calculations, rate limits) based on training data not current docs |

**Overall confidence:** MEDIUM

Research provides solid foundation for roadmap planning based on established trading system patterns and arbitrage strategy fundamentals. However, all Bybit-specific details (API endpoints, rate limits, fee structures, funding conventions, margin calculations) require verification against current official documentation before implementation. Stack technology choices are sound but versions need confirmation.

### Gaps to Address

**During Phase 1 planning:**
- Verify Bybit API v5 rate limits for funding rate endpoints, order placement, position queries
- Confirm funding rate sign convention (positive = longs pay shorts?) via official docs and test trades
- Check pybit vs ccxt current status — which has better Bybit support in 2026?
- Validate websocket reliability for funding rate updates vs polling frequency requirements

**During Phase 2 planning:**
- Confirm current Bybit fee structure (maker/taker percentages, any VIP tiers, spot vs perp differences)
- Verify order book depth API for liquidity analysis
- Test margin requirement calculations for delta-neutral positions (does exchange offer favorable margin treatment?)

**During Phase 3 planning:**
- Understand Bybit maintenance window schedules (frequency, duration, which services affected)
- Test behavior during partial outages (can spot and perp become temporarily unhedged?)

**General gaps:**
- No competitor analysis (what features do commercial funding bots offer in 2026?)
- Regulatory considerations unknown (any automated trading restrictions on Bybit?)
- Community best practices not researched (what mistakes do first-time builders make?)
- Historical profitability data unavailable (what funding rates are realistic to expect?)

## Sources

### Research Methodology

**IMPORTANT:** All four research files (STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md) were generated based on training data knowledge (cutoff January 2025) without access to:
- Web search for current community wisdom and 2026 best practices
- Official Bybit API documentation verification
- Context7 library research capabilities
- Competitor analysis or market research

This means:
- **Architecture patterns** are sound (event-driven systems, state machines, circuit breakers are timeless)
- **Feature categorization** is logical (table stakes vs differentiators based on arbitrage fundamentals)
- **Technology choices** are reasonable (Python async, PostgreSQL, FastAPI are established patterns)
- **Specific details** need verification (Bybit API behaviors, library versions, current fee structures)

### Confidence by Source Type

**HIGH confidence (domain fundamentals):**
- Delta-neutral arbitrage mechanics (spot long + perp short to collect funding)
- Python asyncio patterns for concurrent operations
- PostgreSQL for ACID-compliant financial transaction storage
- Decimal library requirement for monetary calculations
- Event-driven architecture for trading systems

**MEDIUM confidence (established patterns):**
- Python 3.11+ performance improvements for async
- FastAPI + React stack for trading dashboards
- Prometheus + Grafana for monitoring
- Common trading bot pitfalls (delta hedging timing, fee impact, liquidations)

**LOW confidence (needs verification):**
- pybit 5.x vs ccxt 4.x current status
- Bybit-specific API rate limits and behaviors
- Current Bybit fee structures
- Funding rate sign conventions (positive = longs pay shorts?)
- TimescaleDB version compatibility with Postgres 15+
- shadcn/ui installation method (rapidly evolving)

### Recommended Validation Sources

Before implementation, verify against:
- **Bybit Official API Docs** (https://bybit-exchange.github.io/docs/) — rate limits, endpoints, websocket specs, funding conventions
- **PyPI** (https://pypi.org) — current package versions for pybit, ccxt, FastAPI, pydantic
- **GitHub Repositories** — search for "funding rate arbitrage bot" to find current implementations and patterns
- **Crypto Trading Communities** — Reddit r/algotrading, BitcoinTalk for practitioner experiences and pitfalls
- **Bybit Community/Discord** — current trader experiences with API, known issues, maintenance schedules

---
*Research completed: 2026-02-11*
*Ready for roadmap: yes*
*Phase structure: 5 phases suggested (Core Trading → Multi-Pair Real Money → Dynamic Management → Monitoring → Dashboard)*
*Critical validation needed: Bybit API specifics, library versions, fee structures*
