"""Periodic WebSocket update loop for real-time dashboard refresh.

Renders all partial templates with current data and broadcasts them
as OOB-swap HTML fragments to all connected WebSocket clients.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import structlog
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from bot.analytics import metrics as analytics_metrics

log = structlog.get_logger(__name__)


async def dashboard_update_loop(app: FastAPI) -> None:
    """Periodically render and broadcast all dashboard partials via WebSocket.

    Runs until the application shuts down. Each iteration:
    1. Sleeps for the configured update interval
    2. Gathers current data from app.state components
    3. Renders each partial template
    4. Wraps each in OOB swap divs
    5. Broadcasts the concatenated HTML to all WebSocket clients

    Args:
        app: The FastAPI application with state containing hub, templates,
             orchestrator, position_manager, pnl_tracker, funding_monitor.
    """
    update_interval = getattr(app.state, "update_interval", 5)

    log.info("dashboard_update_loop_started", interval=update_interval)

    while True:
        try:
            await asyncio.sleep(update_interval)

            hub = app.state.hub
            if not hub.connections:
                continue

            templates: Jinja2Templates = app.state.templates
            orchestrator = app.state.orchestrator
            position_manager = app.state.position_manager
            pnl_tracker = app.state.pnl_tracker
            funding_monitor = app.state.funding_monitor

            # Gather data
            status = orchestrator.get_status()
            positions = position_manager.get_open_positions()
            positions_with_pnl = []
            for pos in positions:
                pnl = pnl_tracker.get_total_pnl(pos.id)
                positions_with_pnl.append({"position": pos, "pnl": pnl})

            funding_rates = funding_monitor.get_all_funding_rates()[:50]
            closed_positions = pnl_tracker.get_closed_positions()[:50]
            portfolio = pnl_tracker.get_portfolio_summary()

            all_pnls = pnl_tracker.get_all_position_pnls()
            closed_pnls = [p for p in all_pnls if p.closed_at is not None]
            analytics_data = {
                "sharpe": analytics_metrics.sharpe_ratio(closed_pnls),
                "max_drawdown": analytics_metrics.max_drawdown(closed_pnls),
                "win_rate": analytics_metrics.win_rate(closed_pnls),
            }

            settings = orchestrator._settings

            # Build a fake request-like context for template rendering
            # Jinja2Templates.env.get_template() + render() avoids needing a Request
            env = templates.env

            fragments = []

            # Bot status partial
            tpl = env.get_template("partials/bot_status.html")
            html = tpl.render(status=status, positions_count=len(positions))
            fragments.append(
                f'<div id="bot-status-panel" hx-swap-oob="true">{html}</div>'
            )

            # Balance partial
            tpl = env.get_template("partials/balance.html")
            html = tpl.render(portfolio=portfolio)
            fragments.append(
                f'<div id="balance-panel" hx-swap-oob="true">{html}</div>'
            )

            # Analytics partial
            tpl = env.get_template("partials/analytics.html")
            html = tpl.render(analytics=analytics_data)
            fragments.append(
                f'<div id="analytics-panel" hx-swap-oob="true">{html}</div>'
            )

            # Positions partial
            tpl = env.get_template("partials/positions.html")
            html = tpl.render(positions_with_pnl=positions_with_pnl)
            fragments.append(
                f'<div id="positions-panel" hx-swap-oob="true">{html}</div>'
            )

            # Decision contexts for enhanced funding rates panel (Phase 11)
            decision_engine = getattr(app.state, "decision_engine", None)
            decision_contexts = {}
            if decision_engine is not None:
                try:
                    decision_contexts = await decision_engine.get_all_decision_contexts()
                except Exception:
                    log.debug("decision_contexts_unavailable", exc_info=True)

            # Funding rates partial
            tpl = env.get_template("partials/funding_rates.html")
            html = tpl.render(funding_rates=funding_rates, decision_contexts=decision_contexts)
            fragments.append(
                f'<div id="funding-rates-panel" hx-swap-oob="true">{html}</div>'
            )

            # Trade history partial
            tpl = env.get_template("partials/trade_history.html")
            html = tpl.render(closed_positions=closed_positions)
            fragments.append(
                f'<div id="trade-history-panel" hx-swap-oob="true">{html}</div>'
            )

            # Data status partial (v1.1 historical data widget)
            data_store = getattr(app.state, "data_store", None)
            if data_store is not None:
                data_status = await data_store.get_data_status()
                fetch_progress = orchestrator.data_fetch_progress
            else:
                data_status = None
                fetch_progress = None

            tpl = env.get_template("partials/data_status.html")
            html = tpl.render(data_status=data_status, fetch_progress=fetch_progress)
            fragments.append(
                f'<div id="data-status-panel" hx-swap-oob="true">{html}</div>'
            )

            # Config form partial (no message/error during periodic updates)
            tpl = env.get_template("partials/config_form.html")
            html = tpl.render(settings=settings, message="", error="")
            fragments.append(
                f'<div id="config-form-panel" hx-swap-oob="true">{html}</div>'
            )

            # Broadcast all fragments as single HTML payload
            payload = "\n".join(fragments)
            await hub.broadcast(payload)

        except asyncio.CancelledError:
            log.info("dashboard_update_loop_cancelled")
            break
        except Exception:
            log.warning("dashboard_update_loop_error", exc_info=True)
            # Continue loop on error -- don't crash the update loop
            await asyncio.sleep(1)
