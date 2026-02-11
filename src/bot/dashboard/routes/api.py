"""JSON API endpoints for dashboard data (DASH-01 through DASH-07)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bot.analytics import metrics as analytics_metrics
from bot.pnl.tracker import PositionPnL

log = structlog.get_logger(__name__)

router = APIRouter()


def _decimal_to_str(obj: Any) -> Any:
    """Recursively convert Decimal values to strings for JSON serialization."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_str(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_str(item) for item in obj]
    return obj


@router.get("/positions")
async def get_positions(request: Request) -> JSONResponse:
    """DASH-01: JSON list of open positions with P&L breakdown."""
    position_manager = request.app.state.position_manager
    pnl_tracker = request.app.state.pnl_tracker
    positions = position_manager.get_open_positions()

    result = []
    for pos in positions:
        pnl = pnl_tracker.get_total_pnl(pos.id)
        result.append({
            "id": pos.id,
            "spot_symbol": pos.spot_symbol,
            "perp_symbol": pos.perp_symbol,
            "quantity": str(pos.quantity),
            "spot_entry_price": str(pos.spot_entry_price),
            "perp_entry_price": str(pos.perp_entry_price),
            "unrealized_pnl": str(pnl["unrealized_pnl"]),
            "total_funding": str(pnl["total_funding"]),
            "total_fees": str(pnl["total_fees"]),
            "net_pnl": str(pnl["net_pnl"]),
        })

    return JSONResponse(content=result)


@router.get("/funding-rates")
async def get_funding_rates(request: Request) -> JSONResponse:
    """DASH-02: JSON list of all funding rates sorted by rate descending."""
    funding_monitor = request.app.state.funding_monitor
    rates = funding_monitor.get_all_funding_rates()

    result = []
    for fr in rates:
        result.append({
            "symbol": fr.symbol,
            "rate": str(fr.rate),
            "volume_24h": str(fr.volume_24h),
            "next_funding_time": fr.next_funding_time,
            "interval_hours": fr.interval_hours,
            "mark_price": str(fr.mark_price),
        })

    return JSONResponse(content=result)


@router.get("/trade-history")
async def get_trade_history(request: Request) -> JSONResponse:
    """DASH-03: JSON list of closed positions with realized P&L."""
    pnl_tracker = request.app.state.pnl_tracker
    closed = pnl_tracker.get_closed_positions()[:50]

    result = []
    for pos in closed:
        total_funding = sum(
            (fp.amount for fp in pos.funding_payments),
            Decimal("0"),
        )
        total_fees = pos.entry_fee + pos.exit_fee
        net_pnl = total_funding - total_fees

        result.append({
            "position_id": pos.position_id,
            "perp_symbol": pos.perp_symbol,
            "opened_at": pos.opened_at,
            "closed_at": pos.closed_at,
            "total_funding": str(total_funding),
            "total_fees": str(total_fees),
            "net_pnl": str(net_pnl),
        })

    return JSONResponse(content=result)


@router.get("/status")
async def get_status(request: Request) -> JSONResponse:
    """DASH-04: JSON bot status."""
    orchestrator = request.app.state.orchestrator
    status = orchestrator.get_status()
    return JSONResponse(content=_decimal_to_str(status))


@router.get("/balance")
async def get_balance(request: Request) -> JSONResponse:
    """DASH-05: JSON portfolio summary (balance breakdown)."""
    pnl_tracker = request.app.state.pnl_tracker
    portfolio = pnl_tracker.get_portfolio_summary()
    return JSONResponse(content=_decimal_to_str(portfolio))


@router.get("/analytics")
async def get_analytics(request: Request) -> JSONResponse:
    """DASH-07: JSON analytics (Sharpe, drawdown, win rate)."""
    pnl_tracker = request.app.state.pnl_tracker
    all_pnls = pnl_tracker.get_all_position_pnls()
    closed_pnls = [p for p in all_pnls if p.closed_at is not None]

    sharpe = analytics_metrics.sharpe_ratio(closed_pnls)
    dd = analytics_metrics.max_drawdown(closed_pnls)
    wr = analytics_metrics.win_rate(closed_pnls)

    return JSONResponse(content={
        "sharpe_ratio": str(sharpe) if sharpe is not None else None,
        "max_drawdown": str(dd) if dd is not None else None,
        "win_rate": str(wr) if wr is not None else None,
    })
