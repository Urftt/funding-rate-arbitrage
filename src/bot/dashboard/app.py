"""FastAPI dashboard application factory with Jinja2 templates and WebSocket hub."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from bot.dashboard.routes import actions, api, pages, ws
from bot.dashboard.routes.ws import hub

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _format_decimal(value: Any) -> str:
    """Format Decimal values to string without Decimal('...') wrapper."""
    return str(value) if value is not None else "0"


def _timestamp_to_date(value: int | None) -> str:
    """Convert millisecond timestamp to short date string (e.g., 'Jan 2025')."""
    if value is None:
        return "N/A"
    dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return dt.strftime("%b %Y")


def _time_ago(value: int | None) -> str:
    """Convert millisecond timestamp to relative time string (e.g., '2m ago')."""
    if value is None:
        return "N/A"
    now_ms = int(time.time() * 1000)
    diff_seconds = (now_ms - value) / 1000
    if diff_seconds < 60:
        return "just now"
    if diff_seconds < 3600:
        minutes = int(diff_seconds / 60)
        return f"{minutes}m ago"
    if diff_seconds < 86400:
        hours = int(diff_seconds / 3600)
        return f"{hours}h ago"
    days = int(diff_seconds / 86400)
    return f"{days}d ago"


def create_dashboard_app(lifespan: Any = None) -> FastAPI:
    """Create and configure the FastAPI dashboard application.

    Args:
        lifespan: Optional async context manager for application lifespan events.
                  Used by main.py to inject startup/shutdown logic.

    Returns:
        Configured FastAPI application with templates, WebSocket hub, and routes.
    """
    app = FastAPI(
        title="Funding Rate Arbitrage Dashboard",
        lifespan=lifespan,
    )

    # Configure Jinja2 templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["format_decimal"] = _format_decimal
    templates.env.filters["timestamp_to_date"] = _timestamp_to_date
    templates.env.filters["time_ago"] = _time_ago
    app.state.templates = templates

    # Store WebSocket hub on app state for access from route handlers
    app.state.hub = hub

    # Backtest task storage for background execution (BKTS-04)
    app.state.backtest_tasks: dict = {}
    app.state.historical_db_path = "data/historical.db"

    # Pair analyzer for pair explorer (Phase 8) -- wired by main.py lifespan
    app.state.pair_analyzer = None

    # Register routers
    app.include_router(pages.router)
    app.include_router(api.router, prefix="/api")
    app.include_router(actions.router, prefix="/actions")
    app.include_router(ws.router)

    return app
