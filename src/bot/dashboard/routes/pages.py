"""Page routes serving the main dashboard HTML template."""

from __future__ import annotations

from decimal import Decimal

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bot.analytics import metrics as analytics_metrics
from bot.pnl.tracker import PositionPnL

log = structlog.get_logger(__name__)

router = APIRouter()


def _compute_analytics(closed_pnls: list[PositionPnL]) -> dict:
    """Compute analytics from closed position P&L records.

    Args:
        closed_pnls: List of closed PositionPnL records.

    Returns:
        Dict with sharpe, max_drawdown, win_rate keys.
    """
    return {
        "sharpe": analytics_metrics.sharpe_ratio(closed_pnls),
        "max_drawdown": analytics_metrics.max_drawdown(closed_pnls),
        "win_rate": analytics_metrics.win_rate(closed_pnls),
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request) -> HTMLResponse:
    """Main dashboard page. Gathers all data from app.state and renders index.html."""
    templates: Jinja2Templates = request.app.state.templates
    orchestrator = request.app.state.orchestrator

    # Bot status
    status = orchestrator.get_status()

    # Open positions with P&L breakdown
    position_manager = request.app.state.position_manager
    pnl_tracker = request.app.state.pnl_tracker
    positions = position_manager.get_open_positions()
    positions_with_pnl = []
    for pos in positions:
        pnl = pnl_tracker.get_total_pnl(pos.id)
        positions_with_pnl.append({
            "position": pos,
            "pnl": pnl,
        })

    # Funding rates (top 50 by rate)
    funding_monitor = request.app.state.funding_monitor
    funding_rates = funding_monitor.get_all_funding_rates()[:50]

    # Trade history (last 50 closed positions)
    closed = pnl_tracker.get_closed_positions()[:50]

    # Portfolio summary
    portfolio = pnl_tracker.get_portfolio_summary()

    # Analytics from closed positions
    all_pnls = pnl_tracker.get_all_position_pnls()
    closed_pnls = [p for p in all_pnls if p.closed_at is not None]
    analytics_data = _compute_analytics(closed_pnls)

    # Current settings for config form
    settings = orchestrator._settings

    # Data status for historical data widget (may be None if feature disabled)
    data_store = getattr(request.app.state, "data_store", None)
    if data_store is not None:
        data_status = await data_store.get_data_status()
        fetch_progress = orchestrator.data_fetch_progress
    else:
        data_status = None
        fetch_progress = None

    context = {
        "request": request,
        "status": status,
        "positions_with_pnl": positions_with_pnl,
        "funding_rates": funding_rates,
        "closed_positions": closed,
        "portfolio": portfolio,
        "analytics": analytics_data,
        "settings": settings,
        "data_status": data_status,
        "fetch_progress": fetch_progress,
    }

    return templates.TemplateResponse("index.html", context)


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request) -> HTMLResponse:
    """Backtest page with configuration form, equity curve, and heatmap (BKTS-04)."""
    templates: Jinja2Templates = request.app.state.templates

    # Get list of tracked pairs from data store for the symbol dropdown
    data_store = getattr(request.app.state, "data_store", None)
    tracked_pairs: list[dict] = []
    if data_store is not None:
        tracked_pairs = await data_store.get_tracked_pairs(active_only=True)

    return templates.TemplateResponse("backtest.html", {
        "request": request,
        "tracked_pairs": tracked_pairs,
    })
