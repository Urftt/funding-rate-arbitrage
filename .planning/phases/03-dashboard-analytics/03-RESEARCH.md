# Phase 3: Dashboard & Analytics - Research

**Researched:** 2026-02-11
**Domain:** Real-time web dashboard for async Python trading bot
**Confidence:** MEDIUM-HIGH

## Summary

Phase 3 adds a web dashboard to the existing asyncio trading bot so the user can monitor positions, view funding rates, control the bot, configure strategy parameters, and analyze performance. The core challenge is embedding a web server (FastAPI) into the same asyncio event loop that runs the bot's autonomous trading cycle, then pushing real-time state updates to the browser without disrupting the trading hot path.

The recommended approach is a **server-rendered dashboard using FastAPI + Jinja2 + HTMX + Tailwind CSS**. This eliminates the complexity of a separate JavaScript build pipeline (React/Next.js), keeps the entire stack in Python, and still delivers a responsive, real-time UI through WebSocket-driven HTML fragment swaps. The existing bot components (Orchestrator, PnLTracker, PositionManager, FundingMonitor, RiskManager) already expose the data needed for all seven DASH requirements -- the dashboard layer reads from these in-memory structures and pushes updates to connected clients.

For analytics (DASH-07), Sharpe ratio, max drawdown, and win rate can be computed directly from the `PnLTracker`'s in-memory `PositionPnL` records using pure Python/Decimal math. No external analytics library (pandas, quantstats) is needed at this scale -- the bot tracks at most a handful of positions. Keeping analytics in pure Python avoids heavy dependencies and maintains Decimal precision.

**Primary recommendation:** Use FastAPI with Jinja2 templates, HTMX for dynamic updates via WebSocket, and Tailwind CSS (via CDN) for styling. Embed the FastAPI server in the bot's asyncio event loop using `lifespan` context manager. Expose bot state through a thin API layer that reads from existing in-memory components.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | >=0.115 | HTTP/WebSocket API + template serving | Async-native, Jinja2 built-in, WebSocket support, auto OpenAPI docs |
| uvicorn | >=0.30 | ASGI server | Production-grade, runs FastAPI, supports graceful shutdown |
| Jinja2 | >=3.1 | Server-side HTML templating | FastAPI's built-in template engine, async support, mature |
| htmx | 2.0.x | Client-side dynamic HTML swaps | 14KB, no build step, WebSocket extension for real-time, declarative |
| Tailwind CSS | 3.x (CDN) | Utility-first CSS styling | No build step via CDN, responsive, modern dashboard aesthetics |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sse-starlette | >=3.2 | Server-Sent Events (alternative to WS) | If SSE preferred over WebSocket for one-way updates |
| python-multipart | >=0.0.9 | Form data parsing | Required by FastAPI for form submissions (DASH-06 config) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| HTMX + Jinja2 | React + Next.js | Full SPA capability, but adds JS build pipeline, npm, separate process, more complexity for a monitoring dashboard |
| HTMX + Jinja2 | Streamlit | Even simpler, but poor real-time support, limited customization, not embeddable in existing asyncio loop |
| WebSocket (htmx ws) | SSE (sse-starlette) | SSE is simpler for server-to-client push, but WebSocket enables bidirectional (needed for DASH-04 start/stop, DASH-06 config) |
| Tailwind CDN | Tailwind + PostCSS build | Smaller CSS payload, but adds build step complexity unnecessary for single-user dashboard |
| Pure Python analytics | quantstats/pandas | Rich visualizations, but adds heavy dependencies for simple metrics on <10 positions |

**Installation:**
```bash
pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "python-multipart>=0.0.9"
```

Note: Jinja2 is already a dependency of FastAPI. HTMX and Tailwind CSS are loaded via CDN in templates (no pip install).

## Architecture Patterns

### Recommended Project Structure
```
src/
├── bot/
│   ├── dashboard/           # NEW: Dashboard package
│   │   ├── __init__.py
│   │   ├── app.py           # FastAPI app factory, lifespan, ASGI setup
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── pages.py     # Full-page HTML routes (GET /)
│   │   │   ├── api.py       # JSON REST endpoints for data
│   │   │   ├── ws.py        # WebSocket endpoint for real-time updates
│   │   │   └── actions.py   # POST endpoints (start/stop, config update)
│   │   ├── templates/
│   │   │   ├── base.html         # Layout with htmx, tailwind CDN
│   │   │   ├── index.html        # Main dashboard page
│   │   │   ├── partials/         # HTMX-swappable HTML fragments
│   │   │   │   ├── positions.html
│   │   │   │   ├── funding_rates.html
│   │   │   │   ├── trade_history.html
│   │   │   │   ├── bot_status.html
│   │   │   │   ├── balance.html
│   │   │   │   ├── config_form.html
│   │   │   │   └── analytics.html
│   │   │   └── components/       # Reusable template components
│   │   │       ├── position_row.html
│   │   │       └── metric_card.html
│   │   └── static/               # Optional static assets
│   │       └── dashboard.css     # Custom styles (if any beyond Tailwind)
│   ├── analytics/           # NEW: Performance analytics calculations
│   │   ├── __init__.py
│   │   └── metrics.py       # Sharpe, drawdown, win rate calculations
│   ├── orchestrator.py      # MODIFIED: expose state for dashboard
│   ├── config.py            # MODIFIED: add DashboardSettings, runtime updates
│   └── main.py              # MODIFIED: start FastAPI alongside orchestrator
├── ...existing modules...
```

### Pattern 1: Shared Event Loop (FastAPI + Bot)
**What:** Run FastAPI's ASGI server and the bot's orchestrator loop in the same asyncio event loop.
**When to use:** Single-process Python app that needs both a web server and background tasks.
**Why:** The bot already runs on asyncio. Running FastAPI in the same loop means dashboard routes can directly read bot state (PositionManager, PnLTracker, etc.) without IPC.
**Example:**
```python
# bot/main.py -- modified to run both
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start bot orchestrator as background task, stop on shutdown."""
    # Wire all bot components (existing logic)
    orchestrator = _build_orchestrator(settings)
    # Store references on app.state for route handlers
    app.state.orchestrator = orchestrator
    app.state.pnl_tracker = pnl_tracker
    app.state.position_manager = position_manager
    app.state.funding_monitor = funding_monitor
    # ...etc

    # Start bot as background task
    bot_task = asyncio.create_task(orchestrator.start())
    yield
    # Shutdown
    await orchestrator.stop()
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

app = create_dashboard_app(lifespan=lifespan)

async def run():
    config = uvicorn.Config(app, host="0.0.0.0", port=8080)
    server = uvicorn.Server(config)
    await server.serve()

def main():
    asyncio.run(run())
```

### Pattern 2: WebSocket Hub for Real-Time Updates
**What:** A connection manager that broadcasts HTML fragments to all connected dashboard clients.
**When to use:** DASH-01, DASH-02, DASH-04, DASH-05 -- any data that changes in real-time.
**Why:** HTMX's WebSocket extension (`hx-ext="ws"`) swaps received HTML directly into the DOM by element ID. Server pushes pre-rendered Jinja2 fragments.
**Example:**
```python
# bot/dashboard/routes/ws.py
class DashboardHub:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)

    async def broadcast(self, html: str):
        """Send HTML fragment to all connected clients."""
        for ws in self.connections[:]:
            try:
                await ws.send_text(html)
            except Exception:
                self.connections.remove(ws)
```

### Pattern 3: Periodic State Push via Background Task
**What:** A background asyncio task that periodically renders and broadcasts updated HTML fragments.
**When to use:** Dashboard real-time updates every 5-10 seconds.
**Why:** Instead of each component pushing on every change (noisy), a periodic push batches updates.
**Example:**
```python
async def dashboard_update_loop(app_state, hub, templates):
    """Runs as asyncio task, pushes updates to all connected clients."""
    while True:
        await asyncio.sleep(5)  # 5-second update interval
        positions_html = templates.render("partials/positions.html",
            positions=app_state.position_manager.get_open_positions(),
            pnl_tracker=app_state.pnl_tracker)
        await hub.broadcast(positions_html)
        # ...broadcast other partials...
```

### Pattern 4: Configuration Runtime Update (DASH-06)
**What:** Dashboard form submits new settings; bot picks them up on next cycle.
**When to use:** DASH-06 -- user changes funding thresholds, risk limits.
**Why:** Pydantic BaseSettings is immutable by default. Need a mutable runtime config overlay.
**Example:**
```python
# Mutable runtime config that overlays BaseSettings
@dataclass
class RuntimeConfig:
    min_funding_rate: Decimal | None = None
    max_position_size_per_pair: Decimal | None = None
    exit_funding_rate: Decimal | None = None
    max_simultaneous_positions: int | None = None
    # ...other mutable fields

    def apply_to(self, settings: AppSettings) -> None:
        """Apply overrides to settings. Only non-None fields are applied."""
        if self.min_funding_rate is not None:
            settings.trading.min_funding_rate = self.min_funding_rate
        # ...etc
```

### Anti-Patterns to Avoid
- **Separate process for dashboard:** Running FastAPI in a separate process requires IPC (Redis, sockets) to share bot state. Massive complexity for a single-user tool. Keep everything in one asyncio loop.
- **Blocking the event loop in routes:** Dashboard routes MUST be async. Never do synchronous I/O (file reads, DB queries) in route handlers without `asyncio.to_thread()`.
- **Polling from frontend instead of push:** Don't use `setInterval` + fetch for real-time data. Use WebSocket push with HTMX `hx-ext="ws"` for efficient updates.
- **Complex SPA for a monitoring dashboard:** React/Next.js is overkill for a dashboard that primarily displays read-only data with a few control buttons. Server-rendered HTMX is simpler, faster to build, and has zero JS build complexity.
- **Mutating BaseSettings directly:** Pydantic BaseSettings are frozen by default. Use a separate mutable `RuntimeConfig` dataclass that overlays settings at read time.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket connection management | Custom reconnect/heartbeat | HTMX ws extension | Auto-reconnect with exponential backoff built in |
| HTML templating | String concatenation | Jinja2 templates | XSS prevention, template inheritance, partials |
| CSS styling | Custom stylesheets from scratch | Tailwind CSS utility classes | Consistent design system, responsive, dark mode |
| ASGI server | Custom HTTP server | uvicorn | Production-grade, handles graceful shutdown |
| Form validation | Manual input parsing | Pydantic models + FastAPI | Automatic validation, error messages, type coercion |
| Sharpe ratio math | External quantstats library | Pure Decimal-based calculation | 10 lines of code, avoids pandas/numpy dependency, preserves Decimal precision |

**Key insight:** The dashboard is a thin read layer over existing bot state. The heavy lifting (trading, risk, P&L) is already done. Don't over-engineer the view layer.

## Common Pitfalls

### Pitfall 1: Blocking the Trading Loop
**What goes wrong:** Dashboard route handlers or template rendering blocks the asyncio event loop, causing the orchestrator to miss scan cycles or order timeouts.
**Why it happens:** Jinja2 rendering is synchronous by default; large template renders or accidental sync I/O in routes stalls the loop.
**How to avoid:** Keep templates small (use partials). Ensure all route handlers are `async def`. Profile with asyncio debug mode if latency increases.
**Warning signs:** Orchestrator logs show `orchestrator_cycle_error` with increasing frequency; scan intervals drift.

### Pitfall 2: WebSocket Connection Leak
**What goes wrong:** Dashboard clients disconnect (browser close, network drop) but server doesn't clean up, accumulating dead connections and failed `send_text()` calls.
**Why it happens:** No disconnect detection or error handling in broadcast loop.
**How to avoid:** Wrap `send_text()` in try/except; remove connection on any error. Use HTMX's built-in reconnect (client side) and connection timeout (server side).
**Warning signs:** Growing memory usage, increasing exception count in broadcast.

### Pitfall 3: Race Conditions on Config Update
**What goes wrong:** User updates config via dashboard while orchestrator is mid-cycle reading the same config values, causing inconsistent behavior.
**Why it happens:** Shared mutable state without synchronization.
**How to avoid:** Use an `asyncio.Lock` around config reads/writes, or apply config changes only between orchestrator cycles (check at cycle start). The orchestrator already has `_cycle_lock` -- config updates should acquire the same lock.
**Warning signs:** Positions opened with stale or partially-updated thresholds.

### Pitfall 4: Decimal Serialization in JSON/Templates
**What goes wrong:** Decimal values render as `Decimal('0.0003')` in templates or fail JSON serialization.
**Why it happens:** Python's default `str()` for Decimal includes the class name in repr; JSON encoder doesn't handle Decimal.
**How to avoid:** Use Jinja2 filters (e.g., `{{ value | format_decimal }}`). For JSON APIs, use FastAPI's built-in Pydantic serialization which handles Decimal as string, or configure a custom JSON encoder.
**Warning signs:** `Decimal('...')` appearing in rendered HTML; `TypeError: Object of type Decimal is not JSON serializable`.

### Pitfall 5: Stale Data in Dashboard After Bot Stop
**What goes wrong:** User stops the bot via dashboard, but dashboard continues showing old positions/funding rates because the data source is in-memory and goes stale.
**Why it happens:** FundingMonitor stops polling, so cached rates freeze. No "data is stale" indicator.
**How to avoid:** Show "bot stopped" status prominently. Include data age timestamps in templates. Grey out or annotate stale data sections.
**Warning signs:** Users see outdated funding rates and think they're live.

### Pitfall 6: Analytics on Empty/Insufficient Data
**What goes wrong:** Sharpe ratio or max drawdown computed with zero or one data points, causing division by zero or meaningless results.
**Why it happens:** Bot just started, no closed positions yet.
**How to avoid:** Guard analytics calculations with minimum data requirements. Show "insufficient data" message instead of NaN/infinity.
**Warning signs:** `ZeroDivisionError` or `Decimal('Infinity')` in analytics rendering.

## Code Examples

Verified patterns for this specific codebase:

### FastAPI App Factory with Bot State
```python
# bot/dashboard/app.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

def create_dashboard_app(lifespan=None) -> FastAPI:
    app = FastAPI(
        title="Funding Rate Arbitrage Dashboard",
        lifespan=lifespan,
    )
    templates = Jinja2Templates(directory="src/bot/dashboard/templates")
    app.state.templates = templates
    # Register routes
    from bot.dashboard.routes import pages, api, ws, actions
    app.include_router(pages.router)
    app.include_router(api.router, prefix="/api")
    app.include_router(ws.router)
    app.include_router(actions.router, prefix="/actions")
    return app
```

### Reading Existing Bot State in Routes
```python
# bot/dashboard/routes/api.py
from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/positions")
async def get_positions(request: Request):
    """DASH-01: Return open positions with P&L data."""
    pm = request.app.state.position_manager
    pnl = request.app.state.pnl_tracker
    positions = pm.get_open_positions()
    result = []
    for pos in positions:
        pnl_data = pnl.get_total_pnl(pos.id)
        result.append({
            "id": pos.id,
            "pair": pos.perp_symbol,
            "entry_price": str(pos.perp_entry_price),
            "size": str(pos.quantity),
            "unrealized_pnl": str(pnl_data["unrealized_pnl"]),
            "funding_collected": str(pnl_data["total_funding"]),
            "net_pnl": str(pnl_data["net_pnl"]),
        })
    return result
```

### HTMX WebSocket Pattern in Template
```html
<!-- templates/base.html -->
<head>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://unpkg.com/htmx-ext-ws@2.0.4/ws.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body hx-ext="ws" ws-connect="/ws">
    <div id="positions-panel">
        {% include "partials/positions.html" %}
    </div>
    <div id="status-panel">
        {% include "partials/bot_status.html" %}
    </div>
</body>
```

### Analytics: Sharpe Ratio with Decimal
```python
# bot/analytics/metrics.py
from decimal import Decimal
from bot.pnl.tracker import PositionPnL

def sharpe_ratio(
    closed_positions: list[PositionPnL],
    risk_free_rate: Decimal = Decimal("0"),
    annualization_factor: Decimal = Decimal("1095"),  # 3 funding periods/day * 365
) -> Decimal | None:
    """Calculate annualized Sharpe ratio from closed position returns.

    Returns None if fewer than 2 positions (can't compute std dev).
    """
    if len(closed_positions) < 2:
        return None

    returns = []
    for p in closed_positions:
        total_funding = sum((fp.amount for fp in p.funding_payments), Decimal("0"))
        total_fees = p.entry_fee + p.exit_fee
        net_return = total_funding - total_fees
        returns.append(net_return)

    n = Decimal(str(len(returns)))
    mean_return = sum(returns) / n
    variance = sum((r - mean_return) ** 2 for r in returns) / (n - 1)
    std_dev = variance.sqrt()

    if std_dev == 0:
        return None

    sharpe = ((mean_return - risk_free_rate) / std_dev) * annualization_factor.sqrt()
    return sharpe
```

### Bot Start/Stop via Dashboard (DASH-04)
```python
# bot/dashboard/routes/actions.py
from fastapi import APIRouter, Request

router = APIRouter()

@router.post("/bot/stop")
async def stop_bot(request: Request):
    """DASH-04: Stop the bot gracefully."""
    orchestrator = request.app.state.orchestrator
    await orchestrator.stop()
    # Return updated status partial for HTMX swap
    return request.app.state.templates.TemplateResponse(
        "partials/bot_status.html",
        {"request": request, "status": orchestrator.get_status()},
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| React SPA + REST polling | HTMX + WebSocket push | 2024-2025 | Eliminates JS build pipeline for server-rendered apps |
| FastAPI `on_event("startup")` | FastAPI `lifespan` context manager | FastAPI 0.93+ | Cleaner startup/shutdown, proper async context |
| Separate dashboard process | Embedded in bot's event loop | N/A (architectural) | No IPC needed, direct in-memory state access |
| Pydantic v1 settings | Pydantic v2 BaseSettings | pydantic-settings 2.x | Better performance, stricter validation |

**Deprecated/outdated:**
- `@app.on_event("startup")` / `@app.on_event("shutdown")`: Deprecated in favor of `lifespan` context manager in FastAPI
- Raw WebSocket JavaScript: HTMX ws extension handles connection management, reconnect, DOM swapping declaratively

## Existing Codebase Integration Points

This section documents exactly what data is already available from existing components and what must be added.

### Data Already Available (no changes needed)
| Requirement | Source Component | Method/Property | Data Format |
|-------------|-----------------|-----------------|-------------|
| DASH-01: Open positions | `PositionManager` | `get_open_positions()` | `list[Position]` -- id, spot/perp symbol, quantity, entry prices, opened_at |
| DASH-01: P&L per position | `PnLTracker` | `get_total_pnl(id)` | `dict` -- unrealized_pnl, total_funding, total_fees, net_pnl |
| DASH-02: Funding rates | `FundingMonitor` | `get_all_funding_rates()` | `list[FundingRateData]` -- symbol, rate, volume, next_funding_time |
| DASH-04: Bot status | `Orchestrator` | `get_status()` | `dict` -- running, open_positions_count, mode, portfolio_summary |
| DASH-04: Emergency status | `EmergencyController` | `.triggered` | `bool` |
| DASH-05: Portfolio summary | `PnLTracker` | `get_portfolio_summary()` | `dict` -- total_funding_collected, total_fees_paid, net_portfolio_pnl |

### Data That Needs New Code
| Requirement | What's Missing | Where to Add |
|-------------|---------------|--------------|
| DASH-01: Unrealized P&L | `get_unrealized_pnl()` is async, needs prices -- currently has placeholder | Fix `PnLTracker.get_unrealized_pnl()` to use correct symbol lookup |
| DASH-03: Trade history | Closed positions are removed from `PositionManager._positions` on close | Keep closed positions in separate `_closed_positions` list |
| DASH-03: Cumulative profit | No time-series of P&L snapshots | Add periodic P&L snapshots to PnLTracker |
| DASH-05: Available vs allocated | No balance tracking beyond exchange | Add capital allocation tracking (total equity, allocated, available) |
| DASH-06: Runtime config | Settings are immutable BaseSettings | Add `RuntimeConfig` overlay with asyncio.Lock |
| DASH-07: Analytics | No Sharpe/drawdown/win-rate calculations | New `analytics/metrics.py` module |
| DASH-04: Start bot | `Orchestrator` only has `stop()`, no `restart()` | Add method to re-enter the run loop |

### Configuration Required
| Setting | Default | Environment Variable | Purpose |
|---------|---------|---------------------|---------|
| `dashboard_host` | `"0.0.0.0"` | `DASHBOARD_HOST` | Dashboard bind address |
| `dashboard_port` | `8080` | `DASHBOARD_PORT` | Dashboard port |
| `dashboard_enabled` | `true` | `DASHBOARD_ENABLED` | Enable/disable dashboard |
| `update_interval` | `5` | `DASHBOARD_UPDATE_INTERVAL` | Seconds between WebSocket pushes |

## Open Questions

1. **Persistence of trade history across restarts**
   - What we know: Currently all state is in-memory. When the bot restarts, trade history is lost.
   - What's unclear: Whether the user wants persistent storage (SQLite/PostgreSQL) or is OK with in-memory-only for v1.
   - Recommendation: Start with in-memory-only for Phase 3. Add persistence as a future enhancement. The dashboard shows "since last restart" data. This keeps Phase 3 scope manageable and avoids adding a database dependency.

2. **Authentication for the dashboard**
   - What we know: This is a single-user bot running locally or on a personal server.
   - What's unclear: Whether basic auth is needed, or if the dashboard is assumed to be on a private network.
   - Recommendation: No authentication for v1. Document that the dashboard should only be exposed on localhost or behind a VPN. Add a note in the UI. Can add basic auth later.

3. **Dark mode / theme**
   - What we know: Trading dashboards are traditionally dark-themed for extended viewing.
   - What's unclear: User preference.
   - Recommendation: Default to dark theme using Tailwind's dark mode utilities. Single theme for simplicity.

## Sources

### Primary (HIGH confidence)
- Existing codebase analysis: `src/bot/` -- all component interfaces, data models, and patterns verified by reading source files
- [FastAPI Official Docs - WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) -- WebSocket endpoint patterns
- [FastAPI Official Docs - Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) -- lifespan context manager pattern
- [HTMX Official Docs - WebSocket Extension](https://htmx.org/extensions/ws/) -- ws-connect, auto-reconnect, OOB swaps
- [FastAPI PyPI](https://pypi.org/project/fastapi/) -- version 0.128.7 confirmed current
- [sse-starlette PyPI](https://pypi.org/project/sse-starlette/) -- version 3.2.0 confirmed current
- [Jinja2 PyPI](https://pypi.org/project/Jinja2/) -- version 3.1.6 confirmed current

### Secondary (MEDIUM confidence)
- [FastAPI + HTMX + Tailwind IoT Dashboard](https://github.com/volfpeter/fastapi-htmx-tailwind-example) -- architecture reference for FastAPI + HTMX + Tailwind
- [HTMX vs React comparison](https://dualite.dev/blog/htmx-vs-react) -- tradeoff analysis for dashboard use case
- [FastAPI + HTMX DaisyUI Guide](https://sunscrapers.com/blog/modern-web-dev-fastapi-htmx-daisyui/) -- production patterns for HTMX with FastAPI
- [SSE vs WebSocket for dashboards](https://medium.com/codetodeploy/why-server-sent-events-beat-websockets-for-95-of-real-time-cloud-applications-830eff5a1d7c) -- SSE sufficient for most real-time but we need bidirectional for controls

### Tertiary (LOW confidence)
- [QuantStats library](https://github.com/ranaroussi/quantstats) -- reference for analytics formulas (we implement our own with Decimal)
- HTMX 4.0 upcoming -- fetch()-based internals replacing XMLHttpRequest; not yet released, 2.0.x is current stable

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM-HIGH -- FastAPI, HTMX, Jinja2 are well-established; specific version combinations verified via PyPI
- Architecture: HIGH -- Embedding FastAPI in asyncio loop is a documented pattern; existing codebase already provides all data interfaces
- Pitfalls: MEDIUM -- Based on common patterns in asyncio web apps and trading dashboard experience; some may not apply to this specific scale
- Analytics: HIGH -- Sharpe ratio, drawdown, win rate are standard formulas easily implemented in Decimal

**Research date:** 2026-02-11
**Valid until:** 2026-03-11 (30 days -- stable domain, no fast-moving dependencies)
