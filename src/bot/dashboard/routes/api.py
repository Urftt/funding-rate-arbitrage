"""JSON API endpoints for dashboard data (DASH-01 through DASH-07), backtest (BKTS-04), pair explorer (Phase 8), and strategy presets (Phase 10)."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bot.analytics import metrics as analytics_metrics
from bot.backtest.models import BacktestConfig
from bot.backtest.presets import STRATEGY_PRESETS
from bot.backtest.runner import run_backtest, run_comparison
from bot.pnl.tracker import PositionPnL

# Optional: ParameterSweep may not be available if 06-03 hasn't been executed yet
try:
    from bot.backtest.sweep import ParameterSweep

    _SWEEP_AVAILABLE = True
except ImportError:
    _SWEEP_AVAILABLE = False

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


@router.get("/data-status")
async def get_data_status(request: Request) -> JSONResponse:
    """Data status for historical data widget."""
    data_store = getattr(request.app.state, "data_store", None)
    if data_store is None:
        return JSONResponse(content={"enabled": False})

    status = await data_store.get_data_status()
    orchestrator = request.app.state.orchestrator
    progress = orchestrator.data_fetch_progress

    result = {
        "enabled": True,
        **_decimal_to_str(status),
    }
    if progress:
        result["fetch_progress"] = progress

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# Pair Explorer API endpoints (Phase 8)
# ---------------------------------------------------------------------------


def _range_to_since_ms(range_str: str) -> int | None:
    """Convert date range string to since_ms timestamp.

    Args:
        range_str: One of "7d", "30d", "90d", "all".

    Returns:
        Millisecond timestamp for the start of the range, or None for "all".
    """
    if range_str == "all":
        return None
    days = {"7d": 7, "30d": 30, "90d": 90}.get(range_str)
    if days is None:
        return None
    return int(time.time() * 1000) - days * 86400 * 1000


@router.get("/pairs/ranking")
async def get_pair_ranking(request: Request, range: str = "all") -> JSONResponse:
    """Phase 8: Get all tracked pairs ranked by annualized yield descending.

    Query params:
        range: Date range filter -- "7d", "30d", "90d", or "all" (default).

    Returns:
        JSON array of PairStats objects sorted by yield.
    """
    pair_analyzer = getattr(request.app.state, "pair_analyzer", None)
    if pair_analyzer is None:
        return JSONResponse(
            content={"error": "Pair analysis not available"}, status_code=501
        )

    since_ms = _range_to_since_ms(range)
    ranking = await pair_analyzer.get_pair_ranking(since_ms=since_ms)
    return JSONResponse(content=[s.to_dict() for s in ranking])


@router.get("/pairs/{symbol:path}/stats")
async def get_pair_stats(
    request: Request, symbol: str, range: str = "all"
) -> JSONResponse:
    """Phase 8: Get detailed statistics and time series for a single pair.

    Path params:
        symbol: Trading pair symbol (e.g., "BTC/USDT:USDT").

    Query params:
        range: Date range filter -- "7d", "30d", "90d", or "all" (default).

    Returns:
        JSON object with stats and time_series arrays.
    """
    pair_analyzer = getattr(request.app.state, "pair_analyzer", None)
    if pair_analyzer is None:
        return JSONResponse(
            content={"error": "Pair analysis not available"}, status_code=501
        )

    since_ms = _range_to_since_ms(range)
    try:
        detail = await pair_analyzer.get_pair_stats(symbol, since_ms=since_ms)
        return JSONResponse(content=detail.to_dict())
    except Exception as e:
        log.error("pair_stats_error", symbol=symbol, error=str(e))
        return JSONResponse(
            content={"error": f"No data found for {symbol}"}, status_code=404
        )


# ---------------------------------------------------------------------------
# Backtest API endpoints (BKTS-04)
# ---------------------------------------------------------------------------


@router.get("/backtest/presets")
async def get_strategy_presets(request: Request) -> JSONResponse:
    """Phase 10: Return available strategy preset configurations."""
    return JSONResponse(content=STRATEGY_PRESETS)


def _parse_dates(start_date: str, end_date: str) -> tuple[int, int]:
    """Convert YYYY-MM-DD date strings to millisecond timestamps.

    Args:
        start_date: Start date string in YYYY-MM-DD format.
        end_date: End date string in YYYY-MM-DD format.

    Returns:
        Tuple of (start_ms, end_ms).

    Raises:
        ValueError: If date format is invalid or range is empty.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    if end_ms <= start_ms:
        raise ValueError(f"End date ({end_date}) must be after start date ({start_date})")
    return start_ms, end_ms


async def _run_backtest_task(
    task_id: str, app_state: Any, config: BacktestConfig, db_path: str
) -> None:
    """Run a single backtest as a background task and store the result.

    Args:
        task_id: Unique identifier for this task.
        app_state: FastAPI app.state object for storing results.
        config: Backtest configuration.
        db_path: Path to the historical database.
    """
    try:
        result = await run_backtest(config, db_path)
        app_state.backtest_tasks[task_id]["result"] = result.to_dict()
        app_state.backtest_tasks[task_id]["status"] = "complete"
    except Exception as e:
        log.error("backtest_task_error", task_id=task_id, error=str(e))
        app_state.backtest_tasks[task_id]["result"] = {"error": str(e)}
        app_state.backtest_tasks[task_id]["status"] = "error"


async def _run_comparison_task(
    task_id: str,
    app_state: Any,
    config_simple: BacktestConfig,
    config_composite: BacktestConfig,
    db_path: str,
) -> None:
    """Run a v1.0 vs v1.1 comparison as a background task.

    Args:
        task_id: Unique identifier for this task.
        app_state: FastAPI app.state object for storing results.
        config_simple: Config for simple (v1.0) strategy.
        config_composite: Config for composite (v1.1) strategy.
        db_path: Path to the historical database.
    """
    try:
        simple_result, composite_result = await run_comparison(
            config_simple, config_composite, db_path
        )
        app_state.backtest_tasks[task_id]["result"] = {
            "simple": simple_result.to_dict(),
            "composite": composite_result.to_dict(),
        }
        app_state.backtest_tasks[task_id]["status"] = "complete"
    except Exception as e:
        log.error("comparison_task_error", task_id=task_id, error=str(e))
        app_state.backtest_tasks[task_id]["result"] = {"error": str(e)}
        app_state.backtest_tasks[task_id]["status"] = "error"


async def _run_sweep_task(
    task_id: str,
    app_state: Any,
    config: BacktestConfig,
    param_grid: dict,
    db_path: str,
) -> None:
    """Run a parameter sweep as a background task.

    Args:
        task_id: Unique identifier for this task.
        app_state: FastAPI app.state object for storing results.
        config: Base backtest configuration.
        param_grid: Parameter grid for the sweep.
        db_path: Path to the historical database.
    """
    try:
        sweep = ParameterSweep(db_path=db_path)
        result = await sweep.run(config, param_grid)
        app_state.backtest_tasks[task_id]["result"] = result.to_dict()
        app_state.backtest_tasks[task_id]["status"] = "complete"
    except Exception as e:
        log.error("sweep_task_error", task_id=task_id, error=str(e))
        app_state.backtest_tasks[task_id]["result"] = {"error": str(e)}
        app_state.backtest_tasks[task_id]["status"] = "error"


def _build_config_from_body(body: dict, start_ms: int, end_ms: int) -> BacktestConfig:
    """Build a BacktestConfig from the request body with date timestamps.

    Extracts known fields from the body dict and constructs a BacktestConfig.
    Unknown fields are silently ignored.

    Args:
        body: Parsed JSON request body.
        start_ms: Start timestamp in milliseconds.
        end_ms: End timestamp in milliseconds.

    Returns:
        BacktestConfig with values from body and computed timestamps.
    """
    kwargs: dict[str, Any] = {
        "symbol": body["symbol"],
        "start_ms": start_ms,
        "end_ms": end_ms,
    }

    # Optional fields with type conversion
    if "strategy_mode" in body:
        kwargs["strategy_mode"] = body["strategy_mode"]
    if "initial_capital" in body:
        kwargs["initial_capital"] = Decimal(str(body["initial_capital"]))

    # Simple strategy params
    for field in ("min_funding_rate", "exit_funding_rate"):
        if field in body and body[field] is not None:
            kwargs[field] = Decimal(str(body[field]))

    # Composite strategy params
    for field in (
        "entry_threshold",
        "exit_threshold",
        "weight_rate_level",
        "weight_trend",
        "weight_persistence",
        "weight_basis",
    ):
        if field in body and body[field] is not None:
            kwargs[field] = Decimal(str(body[field]))

    return BacktestConfig(**kwargs)


@router.post("/backtest/run")
async def run_backtest_endpoint(request: Request) -> JSONResponse:
    """Start a single backtest as a background task (BKTS-04).

    Expects JSON body with: symbol, start_date, end_date, strategy_mode,
    and optional parameter overrides.

    Returns:
        JSON with task_id and status="running".
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"error": "Invalid JSON body"}, status_code=400
        )

    # Validate required fields
    for field in ("symbol", "start_date", "end_date"):
        if field not in body:
            return JSONResponse(
                content={"error": f"Missing required field: {field}"}, status_code=400
            )

    try:
        start_ms, end_ms = _parse_dates(body["start_date"], body["end_date"])
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)

    config = _build_config_from_body(body, start_ms, end_ms)
    db_path = getattr(request.app.state, "historical_db_path", "data/historical.db")

    task_id = str(uuid.uuid4())[:8]
    request.app.state.backtest_tasks[task_id] = {
        "task": None,
        "type": "backtest",
        "status": "running",
        "result": None,
    }
    task = asyncio.create_task(
        _run_backtest_task(task_id, request.app.state, config, db_path)
    )
    request.app.state.backtest_tasks[task_id]["task"] = task

    return JSONResponse(content={"task_id": task_id, "status": "running"})


@router.post("/backtest/sweep")
async def run_sweep_endpoint(request: Request) -> JSONResponse:
    """Start a parameter sweep as a background task (BKTS-04).

    Expects JSON body with: symbol, start_date, end_date, strategy_mode,
    and optional param_grid dict.

    Returns:
        JSON with task_id and status="running", or error if sweep not available.
    """
    if not _SWEEP_AVAILABLE:
        return JSONResponse(
            content={"error": "Parameter sweep module not available. Run plan 06-03 first."},
            status_code=501,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"error": "Invalid JSON body"}, status_code=400
        )

    for field in ("symbol", "start_date", "end_date"):
        if field not in body:
            return JSONResponse(
                content={"error": f"Missing required field: {field}"}, status_code=400
            )

    try:
        start_ms, end_ms = _parse_dates(body["start_date"], body["end_date"])
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)

    config = _build_config_from_body(body, start_ms, end_ms)
    db_path = getattr(request.app.state, "historical_db_path", "data/historical.db")

    # Use provided param_grid or generate default
    param_grid = body.get("param_grid")
    if param_grid is None:
        strategy_mode = body.get("strategy_mode", "simple")
        param_grid = ParameterSweep.generate_default_grid(strategy_mode)

    task_id = str(uuid.uuid4())[:8]
    request.app.state.backtest_tasks[task_id] = {
        "task": None,
        "type": "sweep",
        "status": "running",
        "result": None,
    }
    task = asyncio.create_task(
        _run_sweep_task(task_id, request.app.state, config, param_grid, db_path)
    )
    request.app.state.backtest_tasks[task_id]["task"] = task

    return JSONResponse(content={"task_id": task_id, "status": "running"})


@router.post("/backtest/compare")
async def run_compare_endpoint(request: Request) -> JSONResponse:
    """Start a v1.0 vs v1.1 comparison as a background task (BKTS-04).

    Expects JSON body with: symbol, start_date, end_date.

    Returns:
        JSON with task_id and status="running".
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"error": "Invalid JSON body"}, status_code=400
        )

    for field in ("symbol", "start_date", "end_date"):
        if field not in body:
            return JSONResponse(
                content={"error": f"Missing required field: {field}"}, status_code=400
            )

    try:
        start_ms, end_ms = _parse_dates(body["start_date"], body["end_date"])
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)

    config_simple = _build_config_from_body(
        {**body, "strategy_mode": "simple"}, start_ms, end_ms
    )
    config_composite = _build_config_from_body(
        {**body, "strategy_mode": "composite"}, start_ms, end_ms
    )
    db_path = getattr(request.app.state, "historical_db_path", "data/historical.db")

    task_id = str(uuid.uuid4())[:8]
    request.app.state.backtest_tasks[task_id] = {
        "task": None,
        "type": "compare",
        "status": "running",
        "result": None,
    }
    task = asyncio.create_task(
        _run_comparison_task(
            task_id, request.app.state, config_simple, config_composite, db_path
        )
    )
    request.app.state.backtest_tasks[task_id]["task"] = task

    return JSONResponse(content={"task_id": task_id, "status": "running"})


@router.get("/backtest/status/{task_id}")
async def get_backtest_status(request: Request, task_id: str) -> JSONResponse:
    """Check the status of a running backtest/sweep/compare task.

    Returns the task status and result when complete.

    Args:
        request: FastAPI request.
        task_id: Unique task identifier returned by the run/sweep/compare endpoint.

    Returns:
        JSON with status and optional result.
    """
    tasks = request.app.state.backtest_tasks
    if task_id not in tasks:
        return JSONResponse(
            content={"error": "Task not found"}, status_code=404
        )

    entry = tasks[task_id]
    status = entry["status"]

    if status == "running":
        return JSONResponse(content={"task_id": task_id, "status": "running"})

    # Complete or error -- return result and clean up task reference
    result = entry["result"]
    entry["task"] = None  # Release the asyncio.Task reference

    return JSONResponse(
        content={
            "task_id": task_id,
            "status": status,
            "type": entry["type"],
            "result": result,
        }
    )
