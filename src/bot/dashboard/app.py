"""FastAPI dashboard application factory with Jinja2 templates and WebSocket hub."""

from __future__ import annotations

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
    app.state.templates = templates

    # Store WebSocket hub on app state for access from route handlers
    app.state.hub = hub

    # Register routers
    app.include_router(pages.router)
    app.include_router(api.router, prefix="/api")
    app.include_router(actions.router, prefix="/actions")
    app.include_router(ws.router)

    return app
