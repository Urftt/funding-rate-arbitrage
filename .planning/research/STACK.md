# Technology Stack

**Project:** Crypto Funding Rate Arbitrage Bot
**Researched:** 2026-02-11
**Overall Confidence:** MEDIUM (based on training data, not verified with current official sources)

## Recommended Stack

### Core Framework & Language
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.11+ | Runtime environment | Async/await performance improvements, best crypto library support, rich data science ecosystem |
| asyncio | stdlib | Async orchestration | Native async/await for handling multiple websocket connections and concurrent API calls |

**Rationale:** Python 3.11+ provides significant performance improvements for async workloads (15-60% faster than 3.10). Crypto trading requires handling real-time websocket streams from multiple markets simultaneously - asyncio is the foundation for this. Python's ecosystem dominates crypto tooling.

**Confidence:** HIGH (established standard)

---

### Exchange API Client
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pybit | 5.x | Bybit official API wrapper | Official Bybit Python SDK, handles authentication, rate limiting, websocket reconnection |
| ccxt | 4.x | Fallback/multi-exchange | Industry standard for crypto exchange APIs, use if pybit proves insufficient |

**Rationale:** Start with `pybit` as it's Bybit's official library with native support for their latest API versions. It handles the complexity of V5 unified trading API, websocket subscriptions, and authentication. CCXT is the industry standard fallback if you need multi-exchange support later or if pybit lacks features.

**Do NOT use:** Custom REST/websocket implementations from scratch. Exchange APIs have subtle authentication requirements, rate limiting, and websocket reconnection logic that's error-prone to reimplement.

**Confidence:** MEDIUM (training data suggests pybit is official, but version/currency not verified)

---

### Database
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| PostgreSQL | 15+ | Persistent storage | ACID compliance for trade history, supports JSONB for flexible schema, excellent time-series support |
| asyncpg | 0.29+ | Async PostgreSQL driver | Fastest PostgreSQL driver for Python, native async support, connection pooling |
| TimescaleDB | 2.13+ extension | Time-series optimization | Hypertables for efficient funding rate history queries, continuous aggregates for analytics |

**Rationale:**
- **PostgreSQL** is the gold standard for financial data (ACID transactions critical for money). TimescaleDB extension provides time-series optimizations without leaving Postgres ecosystem.
- **asyncpg** is 3-5x faster than psycopg2 and natively async (critical when your bot is handling real-time data).
- **Alternative considered:** SQLite - too risky for production money (file locking issues under high concurrency). Redis - not ACID compliant, better as cache layer.

**Confidence:** HIGH (established pattern for financial applications)

---

### Data Processing & Analysis
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pandas | 2.1+ | Data analysis | Industry standard for funding rate calculations, backtesting, P&L analysis |
| numpy | 1.26+ | Numerical computation | Fast array operations for position sizing, risk calculations |
| polars | 0.20+ | High-performance alternative | 5-10x faster than pandas for large datasets, consider for backtesting |

**Rationale:** Pandas is the standard for financial data analysis. However, for real-time bot logic, avoid pandas - use native Python/numpy for hot path to minimize latency. Reserve pandas for batch analysis and dashboard data preparation.

**When to use:** Pandas for analytics/backtesting. Native Python for trade execution logic.

**Confidence:** HIGH (industry standard)

---

### Web Dashboard
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| FastAPI | 0.109+ | Backend API | Modern async framework, auto-generated OpenAPI docs, WebSocket support for live updates |
| uvicorn | 0.27+ | ASGI server | Production-grade async server, supports graceful shutdown |
| React | 18.2+ | Frontend UI | Component architecture, rich ecosystem for trading dashboards |
| Next.js | 14+ | React framework | SSR, API routes, TypeScript support, production optimizations |
| TanStack Query | 5.x | Data fetching | Real-time data sync, caching, WebSocket integration |
| shadcn/ui | latest | UI components | Modern, accessible components; popular for trading dashboards |
| Recharts | 2.10+ | Charts/graphs | React-native charts for P&L, funding rate visualizations |

**Rationale:**
- **FastAPI** is the modern Python standard for APIs - native async, automatic validation, WebSocket support for pushing live position updates to dashboard.
- **React/Next.js** provides the richest ecosystem for building real-time trading dashboards. TanStack Query (formerly React Query) handles the complexity of real-time data synchronization.
- **Alternative considered:** Streamlit/Dash - too limiting for custom trading UI, poor real-time update story.

**Confidence:** MEDIUM-HIGH (FastAPI is established; React stack is standard but specific libraries need verification)

---

### Task Scheduling & Background Jobs
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| asyncio.create_task | stdlib | Concurrent tasks | Native async task spawning for bot loops (market scanner, position manager) |
| APScheduler | 3.10+ | Scheduled tasks | Cron-like scheduling for periodic tasks (funding collection, rebalancing checks) |

**Rationale:** Don't overcomplicate with Celery for a single-instance bot. Use asyncio for concurrent event loops and APScheduler for time-based triggers. Celery adds Redis/RabbitMQ dependency that's unnecessary here.

**Do NOT use:** Celery (overkill for single-bot architecture, adds message broker complexity)

**Confidence:** HIGH (appropriate for project scale)

---

### Configuration & Secrets Management
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pydantic | 2.5+ | Config validation | Type-safe config with validation, env var loading, excellent error messages |
| pydantic-settings | 2.1+ | Settings management | Load config from env vars, .env files, with validation |
| python-dotenv | 1.0+ | .env file loading | Load environment variables from .env files in development |

**Rationale:** Pydantic v2 provides runtime type checking for configuration - critical for avoiding misconfigurations that could lose money. Catch invalid API keys, malformed trade sizes, etc. at startup, not when placing orders.

**Confidence:** HIGH (industry best practice)

---

### Logging & Monitoring
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| structlog | 24.1+ | Structured logging | JSON logs with context (trade_id, pair, side), queryable, integration-ready |
| prometheus-client | 0.19+ | Metrics | Time-series metrics (funding rate deltas, position count, API latency) |
| Grafana | 10+ | Metrics visualization | Industry standard for time-series dashboards |

**Rationale:**
- **structlog** outputs JSON logs with structured context - critical for debugging failed trades. Can add trade_id, pair, timestamp to every log line.
- **Prometheus + Grafana** is the standard for monitoring trading bots - track metrics like "funding rate vs actual collected", "API error rate", "position count over time".

**Alternative considered:** Python logging module - lacks structured logging, hard to query production logs.

**Confidence:** HIGH (established monitoring stack)

---

### Testing
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pytest | 7.4+ | Test framework | Industry standard, excellent async support, rich plugin ecosystem |
| pytest-asyncio | 0.23+ | Async test support | Run async tests with pytest |
| pytest-mock | 3.12+ | Mocking | Mock exchange API responses for deterministic testing |
| pytest-cov | 4.1+ | Coverage reporting | Track test coverage |
| hypothesis | 6.98+ | Property-based testing | Fuzz test position sizing, funding calculations |

**Rationale:** Testing is critical for money-handling code. Mock exchange responses to test bot logic without live API calls. Use hypothesis for property-based testing of mathematical calculations (position sizing should never exceed balance).

**Confidence:** HIGH (pytest is Python standard)

---

### Code Quality
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| ruff | 0.1+ | Linting & formatting | 10-100x faster than pylint/black, combines linting + formatting |
| mypy | 1.8+ | Type checking | Static type checking prevents runtime errors in trading logic |
| pre-commit | 3.6+ | Git hooks | Auto-run formatters and linters before commits |

**Rationale:**
- **ruff** has replaced black + isort + flake8 as the modern standard - single tool, 100x faster.
- **mypy** prevents type errors in critical code paths (calculating position sizes, parsing API responses).

**Confidence:** HIGH (ruff/mypy are current best practices)

---

### Deployment & Containerization
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Docker | 24+ | Containerization | Reproducible deployments, isolate dependencies |
| docker-compose | 2.23+ | Multi-container orchestration | Define bot + postgres + grafana stack in one file |
| Python virtual env | stdlib | Dependency isolation | Local development isolation |

**Rationale:** Docker ensures your bot runs identically in dev and prod. docker-compose defines the full stack (bot, database, monitoring) for one-command startup.

**Do NOT use:** Kubernetes for a single bot - massive overkill. Docker Compose is sufficient.

**Confidence:** HIGH (standard practice)

---

## Supporting Libraries

### Position & Risk Management
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| decimal | stdlib | Precise decimal math | ALL monetary calculations - never use float for money |
| pydantic | 2.5+ | Data validation | Validate API responses, trade parameters before execution |

**Rationale:** **CRITICAL** - Never use Python floats for money. Use `Decimal` for all price, quantity, balance calculations. Floating point errors can cause losses (e.g., 0.1 + 0.2 = 0.30000000000000004).

**Confidence:** HIGH (fundamental best practice)

---

### WebSocket Management
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| websockets | 12+ | WebSocket client | If pybit's websocket client is insufficient |
| aiohttp | 3.9+ | Async HTTP client | Alternative to requests for async REST calls |

**Rationale:** Use exchange library's websocket client first (pybit). Only drop to raw websockets if you need custom reconnection logic or the SDK is buggy.

**Confidence:** MEDIUM (dependent on pybit quality)

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Language | Python 3.11+ | JavaScript/Node.js | Weaker typing, less robust numerical libraries, fewer exchange SDKs |
| Language | Python 3.11+ | Rust | Overkill for strategy complexity, slower development, learning curve |
| Database | PostgreSQL + TimescaleDB | MongoDB | No ACID transactions, poor for financial data |
| Database | PostgreSQL + TimescaleDB | SQLite | File locking issues under concurrent writes, not production-ready for money |
| API Framework | FastAPI | Flask | No native async, no automatic validation, older paradigm |
| API Framework | FastAPI | Django | Too heavyweight, admin UI unnecessary, slower for async workloads |
| Task Queue | asyncio | Celery | Adds Redis/RabbitMQ complexity, unnecessary for single-instance bot |
| Dashboard | React + FastAPI | Streamlit | Poor real-time support, limited customization, not production-grade |
| Dashboard | React + FastAPI | Dash (Plotly) | Callback hell for complex UIs, React ecosystem richer |
| Formatting | ruff | black + isort + flake8 | Slower, requires multiple tools |

---

## Installation

### Core Dependencies

```bash
# Exchange API
pip install pybit  # Bybit official SDK

# Database
pip install asyncpg psycopg2-binary  # Postgres drivers
pip install SQLAlchemy alembic  # ORM and migrations (optional but recommended)

# Data processing
pip install pandas numpy polars  # Data analysis

# Web framework
pip install "fastapi[all]" uvicorn[standard]  # API + server

# Configuration & validation
pip install pydantic pydantic-settings python-dotenv

# Logging & monitoring
pip install structlog prometheus-client

# Task scheduling
pip install APScheduler

# Utilities
# (decimal is stdlib, no install needed)
```

### Dev Dependencies

```bash
pip install -D pytest pytest-asyncio pytest-mock pytest-cov hypothesis  # Testing
pip install -D ruff mypy pre-commit  # Code quality
pip install -D ipython jupyter  # Interactive development
```

### Frontend (Next.js Dashboard)

```bash
npx create-next-app@latest dashboard --typescript --tailwind --app
cd dashboard
npm install @tanstack/react-query recharts
npx shadcn-ui@latest init
```

---

## Architecture Integration Notes

### Hot Path vs Cold Path

**Hot Path (sub-second latency required):**
- Market data websocket handling
- Funding rate calculations
- Trade execution decisions
- Position sizing

**Stack:** Pure Python with asyncio, numpy for calculations, NO pandas, NO database writes in critical path.

**Cold Path (can tolerate seconds of latency):**
- Persisting trade history to database
- Dashboard data queries
- Analytics and backtesting
- Logging

**Stack:** Pandas for analysis, database writes, JSON serialization for API responses.

---

### Deployment Phases

**Phase 1: Local Development**
- Python venv
- Local PostgreSQL via Docker
- .env file for config
- Simple logging to stdout

**Phase 2: Production (Single Server)**
- Docker Compose (bot + postgres + grafana)
- Structured logging to files + stdout
- Prometheus metrics
- Automated restart on crash

**Phase 3: Enhanced (If Scaling)**
- Separate database server
- Log aggregation (e.g., Loki)
- Alerting (e.g., AlertManager)

---

## Version Verification Needed

**CONFIDENCE CAVEAT:** The following need verification against official sources before implementation:

| Library | Stated Version | Why Uncertain |
|---------|---------------|---------------|
| pybit | 5.x | Training data may be outdated; verify current Bybit SDK version |
| ccxt | 4.x | CCXT updates frequently; check latest stable |
| FastAPI | 0.109+ | Verify current stable release |
| pydantic | 2.5+ | v2 was major rewrite; confirm current best practices |
| shadcn/ui | latest | Rapidly evolving; check current installation method |
| TimescaleDB | 2.13+ | Verify compatibility with Postgres 15+ |

**Action Required:** Before finalizing stack, verify versions via:
1. Official GitHub repositories (check latest releases)
2. PyPI for Python packages (latest stable versions)
3. Official documentation sites

---

## Critical Warnings

### Don't Use Floats for Money
```python
# WRONG
price = 0.1
quantity = 0.2
total = price + quantity  # 0.30000000000000004

# CORRECT
from decimal import Decimal
price = Decimal("0.1")
quantity = Decimal("0.2")
total = price + quantity  # Decimal('0.3')
```

### Don't Block the Event Loop
```python
# WRONG - blocks async loop
def get_funding_rate():
    return requests.get(url)  # synchronous call blocks everything

# CORRECT
async def get_funding_rate():
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()
```

### Don't Skip Input Validation
```python
# WRONG
def open_position(size: str):  # size could be "abc" or negative
    exchange.place_order(size=size)

# CORRECT
class PositionParams(BaseModel):
    size: Decimal = Field(gt=0)  # pydantic validates > 0

def open_position(params: PositionParams):
    exchange.place_order(size=params.size)
```

---

## Sources

**Confidence Assessment:** MEDIUM overall

Due to tool restrictions, this research is based on training data (knowledge cutoff January 2025) rather than verified current sources. The stack represents established patterns in the Python crypto trading space, but specific version numbers and library recommendations should be verified via:

- **PyPI** (https://pypi.org) - Current Python package versions
- **Bybit API Docs** (https://bybit-exchange.github.io/docs/) - Official pybit SDK documentation
- **FastAPI Docs** (https://fastapi.tiangolo.com/) - Current best practices
- **TimescaleDB Docs** (https://docs.timescale.com/) - Postgres extension setup

**Recommendations:**
1. Verify all package versions via PyPI before installation
2. Check Bybit's official documentation for current SDK recommendations
3. Review FastAPI changelog for breaking changes since v0.109
4. Confirm TimescaleDB compatibility with chosen Postgres version

**Areas of HIGH confidence** (unlikely to have changed):
- Python 3.11+ for async performance
- PostgreSQL for financial data (ACID compliance)
- Decimal for monetary calculations
- asyncio for concurrent operations
- pytest for testing

**Areas requiring verification:**
- Specific library versions
- pybit vs ccxt for Bybit integration
- Current React/Next.js best practices
- shadcn/ui installation method
