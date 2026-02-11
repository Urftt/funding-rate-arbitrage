"""POST endpoints for bot control and config updates (DASH-04, DASH-06)."""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bot.config import RuntimeConfig

log = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/bot/stop", response_class=HTMLResponse)
async def stop_bot(request: Request) -> HTMLResponse:
    """DASH-04: Stop the bot and return updated bot_status.html partial."""
    templates: Jinja2Templates = request.app.state.templates
    orchestrator = request.app.state.orchestrator

    try:
        await orchestrator.stop()
        log.info("bot_stopped_via_dashboard")
    except Exception as e:
        log.error("bot_stop_failed", error=str(e))

    status = orchestrator.get_status()
    position_manager = request.app.state.position_manager
    positions = position_manager.get_open_positions()
    return templates.TemplateResponse("partials/bot_status.html", {
        "request": request,
        "status": status,
        "positions_count": len(positions),
    })


@router.post("/bot/start", response_class=HTMLResponse)
async def start_bot(request: Request) -> HTMLResponse:
    """DASH-04: Start/restart the bot and return updated bot_status.html partial."""
    templates: Jinja2Templates = request.app.state.templates
    orchestrator = request.app.state.orchestrator

    try:
        await orchestrator.restart()
        log.info("bot_started_via_dashboard")
    except Exception as e:
        log.error("bot_start_failed", error=str(e))

    status = orchestrator.get_status()
    position_manager = request.app.state.position_manager
    positions = position_manager.get_open_positions()
    return templates.TemplateResponse("partials/bot_status.html", {
        "request": request,
        "status": status,
        "positions_count": len(positions),
    })


@router.post("/config", response_class=HTMLResponse)
async def update_config(request: Request) -> HTMLResponse:
    """DASH-06: Update RuntimeConfig from form data and return updated config_form.html partial."""
    templates: Jinja2Templates = request.app.state.templates
    orchestrator = request.app.state.orchestrator
    settings = orchestrator._settings

    form = await request.form()
    message = ""
    error = ""

    try:
        rc = RuntimeConfig()

        # Parse each field only if non-empty
        val = form.get("min_funding_rate", "")
        if val and str(val).strip():
            rc.min_funding_rate = Decimal(str(val).strip())

        val = form.get("max_position_size_usd", "")
        if val and str(val).strip():
            rc.max_position_size_usd = Decimal(str(val).strip())

        val = form.get("exit_funding_rate", "")
        if val and str(val).strip():
            rc.exit_funding_rate = Decimal(str(val).strip())

        val = form.get("max_simultaneous_positions", "")
        if val and str(val).strip():
            rc.max_simultaneous_positions = int(str(val).strip())

        val = form.get("max_position_size_per_pair", "")
        if val and str(val).strip():
            rc.max_position_size_per_pair = Decimal(str(val).strip())

        val = form.get("min_volume_24h", "")
        if val and str(val).strip():
            rc.min_volume_24h = Decimal(str(val).strip())

        val = form.get("scan_interval", "")
        if val and str(val).strip():
            rc.scan_interval = int(str(val).strip())

        orchestrator.runtime_config = rc
        message = "Configuration updated successfully."
        log.info("config_updated_via_dashboard", config=str(rc))

    except (InvalidOperation, ValueError) as e:
        error = f"Invalid value: {e}"
        log.error("config_update_validation_error", error=str(e))
    except Exception as e:
        error = f"Error updating config: {e}"
        log.error("config_update_failed", error=str(e))

    return templates.TemplateResponse("partials/config_form.html", {
        "request": request,
        "settings": settings,
        "message": message,
        "error": error,
    })
